"""Jurisdiction loading, stacks, search, and address resolution against the real
Census lists in backend/data (loads in about a second on SQLite)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import geocode
from app.geocode import GeocodeMatch, parse_census_response
from app.jurisdictions import load_jurisdictions
from app.models import Jurisdiction, PlaceCounty


@pytest.fixture
def loaded(session: Session) -> Session:
    load_jurisdictions(session)
    return session


def _names(stack: list[dict]) -> list[str]:
    return [j["name"] for j in stack]


def test_load_is_idempotent_and_flags_pilots(loaded: Session) -> None:
    total = loaded.scalar(select(func.count()).select_from(Jurisdiction))
    assert total is not None and total > 20_000
    assert load_jurisdictions(loaded) == 0
    tusc = loaded.scalars(select(Jurisdiction).where(Jurisdiction.fips == "01125")).one()
    assert tusc.is_pilot and tusc.pilot_metro == "tuscaloosa"
    assert loaded.scalar(select(func.count()).select_from(PlaceCounty)) >= 15


@pytest.mark.parametrize(
    ("fips", "stack", "extra_key", "extra"),
    [
        ("13121", ["Georgia", "Fulton County"], "places", ["Atlanta city"]),
        # A city spanning two counties: the stack skips the county, which is listed separately.
        ("1304000", ["Georgia", "Atlanta city"], "counties", ["DeKalb County", "Fulton County"]),
        # Consolidated city-county shows once.
        ("0820000", ["Colorado", "Denver County"], "counties", ["Denver County"]),
        ("08031", ["Colorado", "Denver County"], "places", []),
        # DC is both state and county.
        ("11001", ["District of Columbia"], "places", []),
    ],
)
def test_detail_stacks(
    client: TestClient, loaded: Session, fips: str, stack: list[str], extra_key: str,
    extra: list[str],
) -> None:
    body = client.get(f"/api/jurisdictions/{fips}").json()
    assert _names(body["stack"]) == stack
    assert [j["name"] for j in body[extra_key]] == extra


def test_detail_unknown_fips_404(client: TestClient, loaded: Session) -> None:
    assert client.get("/api/jurisdictions/99999").status_code == 404


def test_search_prefers_pilots_and_accepts_state_suffix(
    client: TestClient, loaded: Session
) -> None:
    names = [j["name"] for j in client.get("/api/jurisdictions/search?q=tusca").json()]
    assert names[:2] == ["Tuscaloosa County", "Tuscaloosa city"]
    dallas = client.get("/api/jurisdictions/search?q=dallas, tx").json()
    assert {j["state_code"] for j in dallas} == {"TX"}
    assert client.get("/api/jurisdictions/search?q=%%").json() == []


def test_coverage_lists_pilots(client: TestClient, loaded: Session) -> None:
    fips = {c["fips"] for c in client.get("/api/jurisdictions/coverage").json()}
    assert {"13121", "37119", "48201", "08031", "12057", "11001", "01125"} <= fips


def _fake_match(place: str | None) -> GeocodeMatch:
    return GeocodeMatch("1 MAIN ST, NORTHPORT, AL", -87.6, 33.2, "01", "01125", place)


def test_resolve_city_address_learns_link(
    client: TestClient, loaded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import jurisdictions as api_mod

    # Moundville is in Hale and Tuscaloosa counties and not a pilot, so no link exists yet.
    monkeypatch.setattr(api_mod, "geocode_address", lambda _a: _fake_match("0151648"))
    body = client.get("/api/resolve", params={"address": "1 Main St, Moundville AL"}).json()
    assert _names(body["stack"]) == ["Alabama", "Tuscaloosa County", "Moundville town"]
    assert body["unincorporated"] is False
    county = client.get("/api/jurisdictions/01125").json()
    assert "Moundville town" in [p["name"] for p in county["places"]]


def test_resolve_unincorporated(
    client: TestClient, loaded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import jurisdictions as api_mod

    monkeypatch.setattr(api_mod, "geocode_address", lambda _a: _fake_match(None))
    body = client.get("/api/resolve", params={"address": "1 Rural Rd, AL"}).json()
    assert _names(body["stack"]) == ["Alabama", "Tuscaloosa County"]
    assert body["unincorporated"] is True


def test_resolve_no_match_and_upstream_failure(
    client: TestClient, loaded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import jurisdictions as api_mod

    monkeypatch.setattr(api_mod, "geocode_address", lambda _a: None)
    assert client.get("/api/resolve", params={"address": "nowhere 123"}).status_code == 404

    def boom(_a: str) -> None:
        raise geocode.GeocodeError("down")

    monkeypatch.setattr(api_mod, "geocode_address", boom)
    assert client.get("/api/resolve", params={"address": "nowhere 123"}).status_code == 502


def test_parse_census_response() -> None:
    body = {"result": {"addressMatches": [{
        "matchedAddress": "2201 PAUL W BRYANT DR, TUSCALOOSA, AL, 35401",
        "coordinates": {"x": -87.56, "y": 33.2},
        "geographies": {
            "States": [{"GEOID": "01"}],
            "Counties": [{"GEOID": "01125"}],
            "Incorporated Places": [{"GEOID": "0177256"}],
        },
    }]}}
    m = parse_census_response(body)
    assert m is not None
    assert (m.state_fips, m.county_fips, m.place_fips) == ("01", "01125", "0177256")
    assert parse_census_response({"result": {"addressMatches": []}}) is None
