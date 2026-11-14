"""Daily monitoring (PLAN.md F1–F4): re-fetch approved sources, diff changed text,
triage the change with the LLM, and record a change event for admin review."""

import difflib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.coverage import refresh_coverage
from app.fetcher import FetchResult
from app.llm import LLMNotConfigured, LLMProvider, get_provider, run_structured
from app.models import (
    ChangeEvent,
    JobRun,
    JobStatus,
    Jurisdiction,
    Snapshot,
    Source,
    SourceHealth,
    SourceStatus,
)
from app.pipeline import UPLOAD_SCHEME, ingest_source
from app.storage import get_store

log = logging.getLogger(__name__)

TRIAGE_VERSION = "triage_v1"
TRIAGE_PROMPT = (Path(__file__).parent / "prompts" / f"{TRIAGE_VERSION}.md").read_text()
MAX_DIFF_CHARS = 30_000
SIZE_SWING = 0.5  # flag pages whose text grew or shrank by more than half
UNHEALTHY = (SourceHealth.NOT_FOUND, SourceHealth.BLOCKED, SourceHealth.ERROR)

TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["mep_relevant", "summary", "proposed_actions"],
    "properties": {
        "mep_relevant": {"type": "boolean"},
        "summary": {"type": "string"},
        "proposed_actions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["action", "title", "detail"],
            "properties": {
                "action": {"type": "string", "enum": ["add", "update", "remove"]},
                "title": {"type": "string"},
                "detail": {"type": "string"},
            },
        }},
    },
}


def diff_text(old: str, new: str, max_chars: int = MAX_DIFF_CHARS) -> str:
    """Line diff of two normalized texts with two lines of context, truncated."""
    lines = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=2)
    out = "\n".join(line for line in lines if not line.startswith(("---", "+++")))
    if len(out) > max_chars:
        out = out[:max_chars] + "\n… (diff truncated)"
    return out


def _latest_snapshot(session: Session, source_id: int) -> Snapshot | None:
    return session.scalars(select(Snapshot).where(Snapshot.source_id == source_id)
                           .order_by(Snapshot.id.desc())).first()


def triage(
    session: Session, provider: LLMProvider, source: Source, diff: str, event_ref: int | None
) -> dict[str, Any]:
    jur = session.get(Jurisdiction, source.jurisdiction_id)
    label = f"{jur.name}, {jur.state_code}" if jur else "?"
    result = run_structured(
        session, provider, kind="triage", prompt_version=TRIAGE_VERSION,
        system="You are a careful regulatory analyst. Output only what the diff supports.",
        user=TRIAGE_PROMPT.format(jurisdiction=label, title=source.title or source.domain,
                                  url=source.url, diff=diff),
        schema_name="triage", schema=TRIAGE_SCHEMA, ref_type="source", ref_id=event_ref,
        max_output_tokens=1500,
    )
    return result.data


def check_source(
    session: Session, source: Source, *,
    fetch_fn: Callable[[str], FetchResult] | None = None,
    provider: LLMProvider | None = None,
) -> ChangeEvent | None:
    """Fetch one approved source. A source with no snapshot yet (its first fetch failed)
    is ingested and extracted as if newly approved; otherwise a text change becomes a
    change event. Returns the event, if any."""
    prev = _latest_snapshot(session, source.id)
    if prev is None:
        ingest_source(session, source, fetch_fn=fetch_fn, provider=provider)
        return None

    result = ingest_source(session, source, extract=False, fetch_fn=fetch_fn)
    if not result.changed or result.snapshot_id is None:
        return None
    new = session.get(Snapshot, result.snapshot_id)
    assert new is not None
    store = get_store()
    old_text = store.get(prev.blob_text).decode()
    new_text = store.get(new.blob_text).decode()
    diff = diff_text(old_text, new_text)
    if not diff.strip():
        return None

    event = ChangeEvent(source_id=source.id, prev_snapshot_id=prev.id, new_snapshot_id=new.id,
                        diff_text=diff)
    notes = []
    if prev.char_count and abs(new.char_count - prev.char_count) / prev.char_count > SIZE_SWING:
        notes.append(f"Page text changed size a lot ({prev.char_count:,} → "
                     f"{new.char_count:,} characters); it may have moved or been replaced.")
    try:
        data = triage(session, provider or get_provider(), source, diff, source.id)
        event.mep_relevant = bool(data["mep_relevant"])
        event.ai_summary = " ".join([*notes, data["summary"]]).strip()
        event.proposed_actions = data["proposed_actions"]
    except LLMNotConfigured as exc:
        log.warning("change on source %s not triaged: %s", source.id, exc)
        event.ai_summary = " ".join([*notes, "Not triaged: the AI model is not configured."])
    if notes:
        event.mep_relevant = True  # a big swing always gets a human look
    session.add(event)
    refresh_coverage(session, source.jurisdiction_id)
    session.commit()
    return event


@dataclass
class DailyResult:
    run: JobRun
    events: list[ChangeEvent] = field(default_factory=list)
    unhealthy: list[Source] = field(default_factory=list)


def run_daily(
    session: Session, *, fetch_fn: Callable[[str], FetchResult] | None = None,
    provider: LLMProvider | None = None,
) -> DailyResult:
    run = JobRun(job="daily_monitor", status=JobStatus.RUNNING)
    session.add(run)
    session.commit()
    sources = list(session.scalars(
        select(Source).where(Source.status == SourceStatus.APPROVED,
                             ~Source.url.startswith(UPLOAD_SCHEME))
        .order_by(Source.domain, Source.id)
    ))
    run.total = len(sources)
    result = DailyResult(run)
    errors: list[dict[str, Any]] = []
    for src in sources:
        try:
            event = check_source(session, src, fetch_fn=fetch_fn, provider=provider)
            if event is not None:
                result.events.append(event)
        except Exception as exc:  # one bad source must not stop the run
            log.exception("daily check failed for source %s", src.id)
            session.rollback()
            errors.append({"source_id": src.id, "error": repr(exc)[:500]})
        run.done += 1
        run.sources_checked = run.done
        session.commit()
    result.unhealthy = [s for s in sources if s.health in UNHEALTHY]
    run.changes_found = len(result.events)
    run.errors = errors or None
    run.summary = {
        "relevant_changes": sum(1 for e in result.events if e.mep_relevant is not False),
        "unhealthy_sources": len(result.unhealthy),
    }
    # A run fails only when every source errored; individual errors show in the digest.
    all_failed = bool(sources) and len(errors) == len(sources)
    run.status = JobStatus.FAILED if all_failed else JobStatus.SUCCEEDED
    run.finished_at = datetime.now(UTC)
    session.commit()
    return result
