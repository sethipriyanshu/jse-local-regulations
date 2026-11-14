"""AI extraction: snapshot text → pending rules and code adoptions, each with a
verbatim excerpt that is checked against the snapshot (PLAN.md §6)."""

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.coverage import refresh_coverage
from app.llm import LLMProvider, run_structured
from app.models import (
    CodeAdoption,
    Jurisdiction,
    Origin,
    Rule,
    RuleStatus,
    Snapshot,
    Source,
    Taxonomy,
    TaxonomyKind,
)
from app.taxonomy import CATEGORIES, DISCIPLINES

log = logging.getLogger(__name__)

PROMPT_VERSION = "extract_v1"
PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md").read_text()
CHUNK_CHARS = 40_000
CHUNK_OVERLAP = 1_500
MAX_CHUNKS = 8  # cost cap per document (~100 pages of dense text)
GROUNDED_SCORE = 95
MIN_CONFIDENCE = 0.3

CODES = ["IBC", "IRC", "IMC", "IPC", "IFGC", "IECC", "IFC", "IEBC", "NEC", "NFPA 13",
         "NFPA 72", "NFPA 101", "ASHRAE 90.1", "UPC", "UMC", "OTHER"]


def _schema() -> dict[str, Any]:
    disciplines = [k for k, _ in DISCIPLINES]
    categories = [k for k, _ in CATEGORIES if k != "adopted_code"]
    s = {"type": "string"}
    num = {"type": "number"}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["code_adoptions", "rules"],
        "properties": {
            "code_adoptions": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["code", "edition", "amendments_summary", "effective_on",
                             "excerpt", "confidence"],
                "properties": {"code": {"type": "string", "enum": CODES}, "edition": s,
                               "amendments_summary": s, "effective_on": s, "excerpt": s,
                               "confidence": num},
            }},
            "rules": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["title", "summary", "discipline", "category", "code_ref",
                             "effective_on", "excerpt", "confidence"],
                "properties": {"title": s, "summary": s,
                               "discipline": {"type": "string", "enum": disciplines},
                               "category": {"type": "string", "enum": categories},
                               "code_ref": s, "effective_on": s, "excerpt": s,
                               "confidence": num},
            }},
        },
    }


SCHEMA = _schema()


def chunk_text(text: str) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text) and len(chunks) < MAX_CHUNKS:
        chunks.append(text[start : start + CHUNK_CHARS])
        start += CHUNK_CHARS - CHUNK_OVERLAP
    return chunks


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


SEGMENT_WINDOW = 1_500  # chars within which multi-line excerpt pieces must appear


def is_grounded(excerpt: str, text: str) -> bool:
    """True if the excerpt appears in the text verbatim, allowing whitespace/quote
    differences and tiny OCR-level noise. A multi-line excerpt also counts when each
    line appears verbatim, in order, close together; models often quote a list
    heading with one of its items ("companion codes adopted:\\n2021 IPC")."""
    e, t = _norm(excerpt), _norm(text)
    if len(e) < 12:
        return False
    if e in t or fuzz.partial_ratio(e, t, score_cutoff=GROUNDED_SCORE) >= GROUNDED_SCORE:
        return True
    segments = [_norm(s) for s in excerpt.splitlines() if len(s.strip()) >= 6]
    if len(segments) < 2:
        return False
    pos = t.find(segments[0])
    start = pos
    for seg in segments[1:]:
        if pos < 0:
            return False
        pos = t.find(seg, pos + 1)
    return pos >= 0 and pos - start <= SEGMENT_WINDOW


def _date(s: str) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("|".join(_norm(p) for p in parts).encode()).hexdigest()


@dataclass
class ExtractStats:
    chunks: int = 0
    rules_added: int = 0
    adoptions_added: int = 0
    ungrounded: int = 0
    skipped_duplicates: int = 0


def extract_snapshot(
    session: Session, provider: LLMProvider, source: Source, snapshot: Snapshot, text: str
) -> ExtractStats:
    jur = session.get(Jurisdiction, source.jurisdiction_id)
    assert jur is not None
    tax = {(t.kind, t.key): t.id for t in session.scalars(select(Taxonomy))}
    adopted_cat = tax.get((TaxonomyKind.CATEGORY, "adopted_code"))

    # Fingerprints of what this source already produced, so re-extraction doesn't duplicate.
    existing = list(session.scalars(select(Rule).where(Rule.source_id == source.id)))
    seen = {_fingerprint(r.title, r.excerpt or "") for r in existing}
    # One adoption per (code, edition) per source, however many passages mention it.
    seen |= {_adoption_key(r.code_ref or "", r.code_edition or "")
             for r in existing if r.category_id == adopted_cat}
    stats = ExtractStats()
    jur_label = f"{jur.name}, {jur.state_code} ({jur.type.value})"

    for chunk in chunk_text(text):
        stats.chunks += 1
        result = run_structured(
            session, provider, kind="extract", prompt_version=PROMPT_VERSION,
            system="You are a careful regulatory analyst. Output only what the page supports.",
            user=PROMPT.format(jurisdiction=jur_label, url=source.url, text=chunk),
            schema_name="extraction", schema=SCHEMA, ref_type="snapshot", ref_id=snapshot.id,
        )

        for a in result.data.get("code_adoptions", []):
            if a["confidence"] < MIN_CONFIDENCE or not a["edition"]:
                continue
            title = f"{a['code']} {a['edition']} adopted"
            key = _adoption_key(a["code"], a["edition"])
            if key in seen:
                stats.skipped_duplicates += 1
                continue
            seen.add(key)
            grounded = is_grounded(a["excerpt"], chunk)
            stats.ungrounded += not grounded
            rule = Rule(
                jurisdiction_id=jur.id, category_id=adopted_cat,
                discipline_id=tax.get((TaxonomyKind.DISCIPLINE, _discipline_for_code(a["code"]))),
                title=title,
                summary=a["amendments_summary"] or f"Adopts {a['code']} {a['edition']}.",
                excerpt=a["excerpt"], code_ref=a["code"], code_edition=a["edition"][:32],
                effective_on=_date(a["effective_on"]), status=RuleStatus.PENDING, origin=Origin.AI,
                source_id=source.id, snapshot_id=snapshot.id, confidence=a["confidence"],
                grounded=grounded,
            )
            session.add(rule)
            session.flush()
            session.add(CodeAdoption(
                jurisdiction_id=jur.id, code=a["code"], edition=a["edition"][:32],
                amendments_summary=a["amendments_summary"] or None,
                effective_on=_date(a["effective_on"]), rule_id=rule.id, status=RuleStatus.PENDING,
            ))
            stats.adoptions_added += 1

        for r in result.data.get("rules", []):
            if r["confidence"] < MIN_CONFIDENCE:
                continue
            fp = _fingerprint(r["title"], r["excerpt"])
            if fp in seen:
                stats.skipped_duplicates += 1
                continue
            seen.add(fp)
            grounded = is_grounded(r["excerpt"], chunk)
            stats.ungrounded += not grounded
            session.add(Rule(
                jurisdiction_id=jur.id,
                discipline_id=tax.get((TaxonomyKind.DISCIPLINE, r["discipline"])),
                category_id=tax.get((TaxonomyKind.CATEGORY, r["category"])),
                title=r["title"][:512], summary=r["summary"], excerpt=r["excerpt"],
                code_ref=(r["code_ref"] or None) and r["code_ref"][:255],
                effective_on=_date(r["effective_on"]), status=RuleStatus.PENDING,
                origin=Origin.AI, source_id=source.id, snapshot_id=snapshot.id,
                confidence=r["confidence"], grounded=grounded,
            ))
            stats.rules_added += 1
        session.commit()

    refresh_coverage(session, jur.id)
    session.commit()
    log.info("extracted source %s snapshot %s: %s", source.id, snapshot.id, stats)
    return stats


def _adoption_key(code: str, edition: str) -> str:
    return "adopt|" + _norm(code) + "|" + _norm(edition)[:32]


def _discipline_for_code(code: str) -> str:
    return {
        "IMC": "mechanical", "UMC": "mechanical", "NEC": "electrical", "IPC": "plumbing",
        "UPC": "plumbing", "IFGC": "fuel_gas", "IECC": "energy", "ASHRAE 90.1": "energy",
        "NFPA 13": "fire_protection", "NFPA 72": "fire_protection", "IFC": "fire_protection",
        "NFPA 101": "fire_protection",
    }.get(code, "general")
