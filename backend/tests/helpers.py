"""Small builders shared by the week 5–8 tests."""

from dataclasses import dataclass
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap import seed_taxonomy
from app.models import (
    Jurisdiction,
    JurisdictionType,
    Origin,
    PlaceCounty,
    Rule,
    RuleStatus,
    Source,
    SourceStatus,
    Taxonomy,
    TaxonomyKind,
)


@dataclass
class World:
    state: Jurisdiction
    county: Jurisdiction
    city: Jurisdiction


def make_world(session: Session) -> World:
    seed_taxonomy(session)
    state = Jurisdiction(fips="01", name="Alabama", type=JurisdictionType.STATE, state_code="AL",
                         is_pilot=True)
    session.add(state)
    session.flush()
    county = Jurisdiction(fips="01125", name="Tuscaloosa County", type=JurisdictionType.COUNTY,
                          state_code="AL", parent_id=state.id, is_pilot=True,
                          pilot_metro="tuscaloosa")
    city = Jurisdiction(fips="0177256", name="Tuscaloosa city", type=JurisdictionType.CITY,
                        state_code="AL", parent_id=state.id, is_pilot=True,
                        pilot_metro="tuscaloosa")
    session.add_all([county, city])
    session.flush()
    session.add(PlaceCounty(place_id=city.id, county_id=county.id))
    session.commit()
    return World(state, county, city)


def tax_id(session: Session, kind: TaxonomyKind, key: str) -> int:
    tid = session.scalars(select(Taxonomy.id).where(Taxonomy.kind == kind,
                                                    Taxonomy.key == key)).first()
    assert tid is not None
    return tid


def add_rule(
    session: Session, j: Jurisdiction, title: str, *, code: str | None = None,
    edition: str | None = None, status: RuleStatus = RuleStatus.PENDING,
    category: str = "adopted_code", discipline: str = "plumbing",
    effective: date | None = None, grounded: bool | None = True,
    source: Source | None = None,
) -> Rule:
    r = Rule(jurisdiction_id=j.id, title=title, summary=f"{title}.", excerpt=f"Quote for {title}",
             code_ref=code, code_edition=edition, status=status, origin=Origin.AI,
             category_id=tax_id(session, TaxonomyKind.CATEGORY, category),
             discipline_id=tax_id(session, TaxonomyKind.DISCIPLINE, discipline),
             effective_on=effective, grounded=grounded, source_id=source.id if source else None)
    session.add(r)
    session.commit()
    return r


def add_source(session: Session, j: Jurisdiction, url: str,
               status: SourceStatus = SourceStatus.APPROVED) -> Source:
    s = Source(jurisdiction_id=j.id, url=url, url_hash=url, domain=url.split("/")[2],
               status=status, origin=Origin.ADMIN, title=f"Page {url}")
    session.add(s)
    session.commit()
    return s


def login(c: TestClient) -> None:
    assert c.post("/api/admin/login", json={"passcode": "test-pass"}).status_code == 200
