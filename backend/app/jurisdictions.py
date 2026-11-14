"""Loading the US jurisdiction list and assembling jurisdiction stacks.

A *stack* is the set of governments whose rules apply at a location, outermost
first: state → county → city. See PLAN.md §1.3.
"""

import csv
import logging
from pathlib import Path

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.models import Jurisdiction, JurisdictionType, PlaceCounty
from app.pilots import CONSOLIDATED_PLACES, DISTRICT_FIPS, METROS

log = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
BATCH = 1000


def _read(name: str) -> list[dict[str, str]]:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _type_for(fips: str, default: JurisdictionType) -> JurisdictionType:
    if fips in DISTRICT_FIPS:
        return JurisdictionType.DISTRICT
    if fips in CONSOLIDATED_PLACES or fips in CONSOLIDATED_PLACES.values():
        return JurisdictionType.CONSOLIDATED
    return default


def load_jurisdictions(session: Session) -> int:
    """Insert any states, counties, and incorporated places that are missing, then
    apply pilot flags and pilot place→county links. Idempotent."""
    existing = set(session.scalars(select(Jurisdiction.fips)))
    added = 0

    def bulk(rows: list[dict[str, object]]) -> None:
        nonlocal added
        for i in range(0, len(rows), BATCH):
            session.execute(insert(Jurisdiction), rows[i : i + BATCH])
        added += len(rows)
        session.flush()

    states = _read("states.csv")
    bulk([
        {"fips": r["GEOID"], "name": r["NAME"], "state_code": r["STUSPS"],
         "type": _type_for(r["GEOID"], JurisdictionType.STATE)}
        for r in states if r["GEOID"] not in existing
    ])
    state_ids = dict(session.execute(
        select(Jurisdiction.fips, Jurisdiction.id).where(Jurisdiction.type.in_(
            [JurisdictionType.STATE, JurisdictionType.DISTRICT]))
    ).all())

    # Counties and places hang off their state; a place's counties go in place_counties.
    for filename, default in (("counties.csv", JurisdictionType.COUNTY),
                              ("places.csv", JurisdictionType.CITY)):
        bulk([
            {"fips": r["GEOID"], "name": r["NAME"], "state_code": r["STUSPS"],
             "type": _type_for(r["GEOID"], default), "parent_id": state_ids.get(r["GEOID"][:2])}
            for r in _read(filename) if r["GEOID"] not in existing
        ])

    _apply_pilots(session)
    session.commit()
    if added:
        log.info("jurisdictions added: %d", added)
    return added


def _apply_pilots(session: Session) -> None:
    by_fips = {
        j.fips: j
        for j in session.scalars(
            select(Jurisdiction).where(Jurisdiction.fips.in_(
                {f for m in METROS for f in m.jurisdictions}
                | {c for m in METROS for cs in m.place_counties.values() for c in cs}
            ))
        )
    }
    for metro in METROS:
        for fips in metro.jurisdictions:
            j = by_fips.get(fips)
            if j is None:
                log.warning("pilot %s: FIPS %s not found in Census data", metro.key, fips)
                continue
            j.is_pilot = True
            # A state can serve several metros (Texas); only local units get a metro tag.
            if j.type not in (JurisdictionType.STATE,):
                j.pilot_metro = metro.key
        for place_fips, county_fips_list in metro.place_counties.items():
            place = by_fips.get(place_fips)
            for county_fips in county_fips_list:
                county = by_fips.get(county_fips)
                if place and county:
                    link_place_county(session, place.id, county.id)


def link_place_county(session: Session, place_id: int, county_id: int) -> None:
    if session.get(PlaceCounty, (place_id, county_id)) is None:
        session.add(PlaceCounty(place_id=place_id, county_id=county_id))


def build_stack(
    session: Session, county: Jurisdiction | None, place: Jurisdiction | None = None,
    state: Jurisdiction | None = None,
) -> list[Jurisdiction]:
    """Outermost-first list of governments for a location, with special cases folded:
    a consolidated city-county shows once, and DC shows once."""
    anchor = county or place or state
    if anchor is None:
        return []
    if state is None and anchor.parent_id is not None:
        state = session.get(Jurisdiction, anchor.parent_id)

    stack: list[Jurisdiction] = []
    if state and not (county and county.type == JurisdictionType.DISTRICT):
        stack.append(state)
    if county:
        stack.append(county)
    if place and not (county and CONSOLIDATED_PLACES.get(place.fips) == county.fips):
        stack.append(place)
    return stack


def places_in_county(session: Session, county: Jurisdiction) -> list[Jurisdiction]:
    """Known cities in a county (pilots plus any learned from geocoding), pilots first."""
    rows = session.scalars(
        select(Jurisdiction)
        .join(PlaceCounty, PlaceCounty.place_id == Jurisdiction.id)
        .where(PlaceCounty.county_id == county.id)
        .order_by(Jurisdiction.is_pilot.desc(), Jurisdiction.name)
    ).all()
    return [p for p in rows if CONSOLIDATED_PLACES.get(p.fips) != county.fips]


def counties_for_place(session: Session, place: Jurisdiction) -> list[Jurisdiction]:
    return list(session.scalars(
        select(Jurisdiction)
        .join(PlaceCounty, PlaceCounty.county_id == Jurisdiction.id)
        .where(PlaceCounty.place_id == place.id)
        .order_by(Jurisdiction.name)
    ))


def default_stack(session: Session, j: Jurisdiction) -> list[Jurisdiction]:
    """The stack shown for a jurisdiction selected without an address. A city that spans
    several counties gets no county layer, since which one applies depends on the address."""
    if len(j.fips) == 5:
        return build_stack(session, county=j)
    if len(j.fips) == 7:
        counties = counties_for_place(session, j)
        return build_stack(session, county=counties[0] if len(counties) == 1 else None, place=j)
    return [j]
