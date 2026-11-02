"""Address → state / county / place FIPS via the US Census Geocoder (free, no key).
https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html
"""

from dataclasses import dataclass

import httpx

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
LAYERS = "States,Counties,Incorporated Places"


@dataclass
class GeocodeMatch:
    matched_address: str
    lng: float
    lat: float
    state_fips: str | None
    county_fips: str | None
    place_fips: str | None  # None means unincorporated


class GeocodeError(Exception):
    pass


def _first_geoid(geographies: dict[str, list[dict[str, str]]], layer: str) -> str | None:
    items = geographies.get(layer) or []
    return items[0]["GEOID"] if items else None


def parse_census_response(body: dict) -> GeocodeMatch | None:
    matches = (body.get("result") or {}).get("addressMatches") or []
    if not matches:
        return None
    m = matches[0]
    geo = m.get("geographies") or {}
    return GeocodeMatch(
        matched_address=m["matchedAddress"],
        lng=float(m["coordinates"]["x"]),
        lat=float(m["coordinates"]["y"]),
        state_fips=_first_geoid(geo, "States"),
        county_fips=_first_geoid(geo, "Counties"),
        place_fips=_first_geoid(geo, "Incorporated Places"),
    )


def geocode_address(address: str, client: httpx.Client | None = None) -> GeocodeMatch | None:
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": LAYERS,
        "format": "json",
    }
    owns = client is None
    client = client or httpx.Client(timeout=15)
    try:
        res = client.get(CENSUS_URL, params=params)
        res.raise_for_status()
        return parse_census_response(res.json())
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise GeocodeError(f"Census geocoder failed: {exc}") from exc
    finally:
        if owns:
            client.close()
