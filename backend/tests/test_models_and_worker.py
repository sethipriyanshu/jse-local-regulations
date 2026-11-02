import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.bootstrap import CATEGORIES, DISCIPLINES, seed_taxonomy
from app.models import (
    JobStatus,
    Jurisdiction,
    JurisdictionType,
    Origin,
    Source,
    SourceStatus,
    Taxonomy,
)
from app.worker import run_daily


def _county(session: Session) -> Jurisdiction:
    state = Jurisdiction(fips="01", name="Alabama", type=JurisdictionType.STATE, state_code="AL")
    county = Jurisdiction(
        fips="01125", name="Tuscaloosa County", type=JurisdictionType.COUNTY,
        state_code="AL", parent=state, is_pilot=True, pilot_metro="Tuscaloosa",
    )
    session.add(county)
    session.commit()
    return county


def test_jurisdiction_parent_chain(session: Session) -> None:
    county = _county(session)
    assert county.parent is not None and county.parent.fips == "01"


def test_source_url_unique_per_jurisdiction(session: Session) -> None:
    county = _county(session)
    for _ in range(2):
        session.add(Source(
            jurisdiction_id=county.id, url="https://example.gov/codes", url_hash="a" * 64,
            domain="example.gov", status=SourceStatus.SUBMITTED, origin=Origin.USER,
        ))
    with pytest.raises(IntegrityError):
        session.commit()


def test_enum_columns_reject_unknown_values(session: Session) -> None:
    county = _county(session)
    session.add(Source(
        jurisdiction_id=county.id, url="https://x.gov", url_hash="b" * 64, domain="x.gov",
        status="bogus", origin=Origin.USER,  # type: ignore[arg-type]
    ))
    with pytest.raises(StatementError):
        session.commit()


def test_seed_taxonomy_is_idempotent(session: Session) -> None:
    assert seed_taxonomy(session) == len(DISCIPLINES) + len(CATEGORIES)
    assert seed_taxonomy(session) == 0
    assert len(session.scalars(select(Taxonomy)).all()) == len(DISCIPLINES) + len(CATEGORIES)


def test_daily_worker_records_job_run(session: Session) -> None:
    run = run_daily(session)
    assert run.status == JobStatus.SUCCEEDED
    assert run.finished_at is not None
