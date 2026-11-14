from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap import seed_taxonomy
from app.extract import chunk_text, extract_snapshot, is_grounded
from app.llm import LLMResult
from app.models import (
    AiRun,
    CodeAdoption,
    Jurisdiction,
    JurisdictionType,
    Origin,
    Rule,
    Snapshot,
    Source,
    SourceStatus,
)

PAGE = """Effective July 1, 2022, the Division will adopt the 2021 International Building Code.
The following companion codes are also adopted:
2021 International Existing Building Code
2021 International Plumbing Code
2020 National Electrical Code (NFPA 70)
Permit applications for commercial work must include sealed MEP drawings."""


@pytest.mark.parametrize(
    ("excerpt", "ok"),
    [
        ("the Division will adopt the 2021 International Building Code.", True),
        ("the  division will ADOPT the 2021   International Building Code", True),  # whitespace/case
        ("The following companion codes are also adopted:\n2021 International Plumbing Code", True),
        ("The following companion codes are also adopted:\n2024 International Plumbing Code", False),
        ("2021 International Plumbing Code\nThe following companion codes are also adopted:", False),
        ("The city adopted the 2023 NEC with no amendments.", False),  # fabricated
        ("short", False),
    ],
)
def test_is_grounded(excerpt: str, ok: bool) -> None:
    assert is_grounded(excerpt, PAGE) is ok


def test_chunk_text_overlaps_and_caps() -> None:
    chunks = chunk_text("x" * 100_000)
    assert len(chunks) == 3
    assert all(len(c) <= 40_000 for c in chunks)


class FakeProvider:
    name = "fake"

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.calls = 0

    def structured(self, system: str, user: str, schema_name: str, schema: dict[str, Any],
                   max_output_tokens: int = 4000) -> LLMResult:
        self.calls += 1
        assert "<page>" in user and "Plumbing" in user
        return LLMResult(self.data, input_tokens=1000, output_tokens=200, model="fake-1")


EXTRACTION = {
    "code_adoptions": [
        {"code": "IPC", "edition": "2021", "amendments_summary": "", "effective_on": "2022-07-01",
         "excerpt": "The following companion codes are also adopted:\n2021 International Plumbing Code",
         "confidence": 0.95},
        {"code": "NEC", "edition": "", "amendments_summary": "", "effective_on": "",
         "excerpt": "2020 National Electrical Code", "confidence": 0.9},  # no edition → dropped
    ],
    "rules": [
        {"title": "Sealed MEP drawings required", "summary": "Commercial permits need sealed MEP sets.",
         "discipline": "general", "category": "permit_submittal", "code_ref": "",
         "effective_on": "", "confidence": 0.8,
         "excerpt": "Permit applications for commercial work must include sealed MEP drawings."},
        {"title": "Made up", "summary": "x", "discipline": "electrical", "category": "fees",
         "code_ref": "", "effective_on": "not a date", "confidence": 0.7,
         "excerpt": "Electrical permits cost $500."},  # kept but flagged ungrounded
        {"title": "Low confidence", "summary": "x", "discipline": "electrical", "category": "fees",
         "code_ref": "", "effective_on": "", "confidence": 0.1, "excerpt": "whatever text here"},
    ],
}


@pytest.fixture
def source_and_snapshot(session: Session) -> tuple[Source, Snapshot]:
    seed_taxonomy(session)
    j = Jurisdiction(fips="01", name="Alabama", type=JurisdictionType.STATE, state_code="AL")
    session.add(j)
    session.flush()
    src = Source(jurisdiction_id=j.id, url="https://x.gov/a", url_hash="h" * 64, domain="x.gov",
                 status=SourceStatus.APPROVED, origin=Origin.ADMIN)
    session.add(src)
    session.flush()
    snap = Snapshot(source_id=src.id, content_hash="c" * 64, blob_raw="r", blob_text="t",
                    char_count=len(PAGE))
    session.add(snap)
    session.commit()
    return src, snap


def test_extract_persists_pending_items_with_grounding(
    session: Session, source_and_snapshot: tuple[Source, Snapshot]
) -> None:
    src, snap = source_and_snapshot
    stats = extract_snapshot(session, FakeProvider(EXTRACTION), src, snap, PAGE)
    assert (stats.adoptions_added, stats.rules_added, stats.ungrounded) == (1, 2, 1)

    rules = {r.title: r for r in session.scalars(select(Rule))}
    assert rules["IPC 2021 adopted"].grounded is True
    assert str(rules["IPC 2021 adopted"].effective_on) == "2022-07-01"
    assert rules["Sealed MEP drawings required"].grounded is True
    assert rules["Made up"].grounded is False and rules["Made up"].effective_on is None
    assert all(r.status.value == "pending" and r.origin == Origin.AI for r in rules.values())

    adoption = session.scalars(select(CodeAdoption)).one()
    assert (adoption.code, adoption.edition) == ("IPC", "2021")
    run = session.scalars(select(AiRun)).one()
    assert run.cost_usd and run.cost_usd > 0 and run.prompt_version == "extract_v1"


def test_reextract_does_not_duplicate(
    session: Session, source_and_snapshot: tuple[Source, Snapshot]
) -> None:
    src, snap = source_and_snapshot
    extract_snapshot(session, FakeProvider(EXTRACTION), src, snap, PAGE)
    stats = extract_snapshot(session, FakeProvider(EXTRACTION), src, snap, PAGE)
    assert stats.rules_added == 0 and stats.adoptions_added == 0
    assert stats.skipped_duplicates == 3


def test_same_adoption_quoted_twice_is_one_row(session: Session) -> None:
    from app.extract import extract_snapshot
    from tests.helpers import add_source, make_world

    w = make_world(session)
    src = add_source(session, w.city, "https://city.gov/codes")
    snap = Snapshot(source_id=src.id, content_hash="h", blob_raw="r", blob_text="t", char_count=10)
    session.add(snap)
    session.commit()
    text = "Residential: the 2015 IECC applies. Commercial: ASHRAE 90.1 2013 or the 2015 IECC."

    class Twice:
        name = "fake"

        def structured(self, *_a: object, **_k: object) -> LLMResult:
            a = {"code": "IECC", "edition": "2015", "amendments_summary": "",
                 "effective_on": "", "confidence": 0.9}
            return LLMResult({"code_adoptions": [
                {**a, "excerpt": "Residential: the 2015 IECC applies."},
                {**a, "excerpt": "Commercial: ASHRAE 90.1 2013 or the 2015 IECC."},
            ], "rules": []}, 10, 10, "f")

    stats = extract_snapshot(session, Twice(), src, snap, text)
    assert stats.adoptions_added == 1 and stats.skipped_duplicates == 1
    again = extract_snapshot(session, Twice(), src, snap, text)
    assert again.adoptions_added == 0
