from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import case, or_, select, true
from sqlalchemy.orm import Session

from app.db import get_session
from app.geocode import GeocodeError, geocode_address
from app.jurisdictions import (
    build_stack,
    counties_for_place,
    default_stack,
    link_place_county,
    places_in_county,
)
from app.models import Coverage, Jurisdiction, JurisdictionType, PlaceCounty

router = APIRouter(tags=["jurisdictions"])
SessionDep = Annotated[Session, Depends(get_session)]


class JurisdictionOut(BaseModel):
    id: int
    fips: str
    name: str
    type: JurisdictionType
    state_code: str
    coverage: Coverage
    is_pilot: bool
    pilot_metro: str | None

    model_config = {"from_attributes": True}


class JurisdictionDetail(BaseModel):
    jurisdiction: JurisdictionOut
    stack: list[JurisdictionOut]  # outermost first, ending with this jurisdiction
    places: list[JurisdictionOut]  # for a county: known cities inside it
    counties: list[JurisdictionOut]  # for a city: the counties it spans


class ResolveOut(BaseModel):
    matched_address: str
    lng: float
    lat: float
    county_fips: str | None
    stack: list[JurisdictionOut]
    unincorporated: bool


class CoverageItem(BaseModel):
    fips: str
    coverage: Coverage
    is_pilot: bool
    pilot_metro: str | None


def _out(items: list[Jurisdiction]) -> list[JurisdictionOut]:
    return [JurisdictionOut.model_validate(j) for j in items]


def _by_fips(session: Session, fips: str | None) -> Jurisdiction | None:
    if not fips:
        return None
    return session.scalars(select(Jurisdiction).where(Jurisdiction.fips == fips)).first()


@router.get("/jurisdictions/search", response_model=list[JurisdictionOut])
def search(
    session: SessionDep,
    q: Annotated[str, Query(min_length=2, max_length=80)],
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> list[Jurisdiction]:
    term = q.strip().replace("%", "").replace("_", "")
    # Optional trailing state, e.g. "Tuscaloosa, AL" or "dallas tx".
    state = None
    parts = term.replace(",", " ").split()
    if len(parts) > 1 and len(parts[-1]) == 2 and parts[-1].isalpha():
        state, term = parts[-1].upper(), " ".join(parts[:-1])
    if len(term) < 2:
        return []

    stmt = select(Jurisdiction).where(
        or_(Jurisdiction.name.like(f"{term}%"), Jurisdiction.name.like(f"% {term}%"))
    )
    if state:
        stmt = stmt.where(Jurisdiction.state_code == state)
    type_rank = case(
        (Jurisdiction.type.in_([JurisdictionType.STATE, JurisdictionType.DISTRICT]), 0),
        (Jurisdiction.type.in_([JurisdictionType.COUNTY, JurisdictionType.CONSOLIDATED]), 1),
        else_=2,
    )
    starts = case((Jurisdiction.name.like(f"{term}%"), 0), else_=1)
    stmt = stmt.order_by(
        Jurisdiction.is_pilot.desc(), starts, type_rank, Jurisdiction.name
    ).limit(limit)
    return list(session.scalars(stmt))


@router.get("/jurisdictions/coverage", response_model=list[CoverageItem])
def coverage(session: SessionDep) -> list[CoverageItem]:
    """Jurisdictions the map should shade: pilots and anything with data. The map only
    draws counties, so a county with no data of its own shows as partial when one of
    its cities has data."""
    rows = session.scalars(
        select(Jurisdiction).where(
            or_(Jurisdiction.is_pilot == true(), Jurisdiction.coverage != Coverage.NONE)
        )
    ).all()
    items = {j.fips: CoverageItem(fips=j.fips, coverage=j.coverage, is_pilot=j.is_pilot,
                                  pilot_metro=j.pilot_metro) for j in rows}
    covered_places = [j.id for j in rows if len(j.fips) == 7 and j.coverage != Coverage.NONE]
    if covered_places:
        county_rows = session.scalars(
            select(Jurisdiction).join(PlaceCounty, PlaceCounty.county_id == Jurisdiction.id)
            .where(PlaceCounty.place_id.in_(covered_places))
        ).all()
        for c in county_rows:
            item = items.get(c.fips)
            if item is None:
                items[c.fips] = CoverageItem(fips=c.fips, coverage=Coverage.PARTIAL,
                                             is_pilot=c.is_pilot, pilot_metro=c.pilot_metro)
            elif item.coverage == Coverage.NONE:
                item.coverage = Coverage.PARTIAL
    return list(items.values())


@router.get("/jurisdictions/{fips}", response_model=JurisdictionDetail)
def detail(fips: str, session: SessionDep) -> JurisdictionDetail:
    j = _by_fips(session, fips)
    if j is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No jurisdiction with FIPS {fips}")

    places = places_in_county(session, j) if len(j.fips) == 5 else []
    counties = counties_for_place(session, j) if len(j.fips) == 7 else []
    return JurisdictionDetail(
        jurisdiction=JurisdictionOut.model_validate(j),
        stack=_out(default_stack(session, j)),
        places=_out(places),
        counties=_out(counties),
    )


@router.get("/resolve", response_model=ResolveOut)
def resolve(
    session: SessionDep, address: Annotated[str, Query(min_length=5, max_length=300)]
) -> ResolveOut:
    try:
        match = geocode_address(address)
    except GeocodeError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Address lookup is unavailable right now"
        ) from exc
    if match is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No US address match. Include street, city, and state.",
        )

    state = _by_fips(session, match.state_fips)
    county = _by_fips(session, match.county_fips)
    place = _by_fips(session, match.place_fips)
    if place and county:
        # Learn city→county links as addresses are looked up.
        link_place_county(session, place.id, county.id)
        session.commit()

    return ResolveOut(
        matched_address=match.matched_address,
        lng=match.lng,
        lat=match.lat,
        county_fips=match.county_fips,
        stack=_out(build_stack(session, county=county, place=place, state=state)),
        unincorporated=match.place_fips is None,
    )
