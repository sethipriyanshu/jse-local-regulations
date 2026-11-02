"""Pilot metros for the MVP (PLAN.md §5) and the special cases the Census data
doesn't capture on its own."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Metro:
    key: str
    label: str
    jurisdictions: list[str]  # FIPS: states, counties, places
    place_counties: dict[str, list[str]] = field(default_factory=dict)


METROS: list[Metro] = [
    Metro(
        "atlanta", "Atlanta",
        ["13", "13121", "13089", "13135", "13067", "1304000"],
        {"1304000": ["13121", "13089"]},
    ),
    Metro("charlotte", "Charlotte", ["37", "37119", "3712000"], {"3712000": ["37119"]}),
    Metro(
        "dallas", "Dallas",
        ["48", "48113", "4819000"],
        {"4819000": ["48113", "48085", "48121", "48257", "48397"]},
    ),
    Metro(
        "houston", "Houston",
        ["48", "48201", "4835000"],
        {"4835000": ["48201", "48157", "48339"]},
    ),
    Metro("denver", "Denver", ["08", "08031", "0820000"], {"0820000": ["08031"]}),
    Metro("tampa", "Tampa", ["12", "12057", "1271000"], {"1271000": ["12057"]}),
    Metro("dc", "Washington DC", ["11", "11001"]),
    Metro(
        "tuscaloosa", "Tuscaloosa",
        ["01", "01125", "0177256", "0155200"],
        {"0177256": ["01125"], "0155200": ["01125"]},
    ),
]

# City-county consolidations: the place and the county are one government, so the
# jurisdiction stack shows only the county. Extend as new metros are added.
CONSOLIDATED_PLACES: dict[str, str] = {
    "0820000": "08031",  # Denver
}

# Washington DC is both the state- and county-level unit.
DISTRICT_FIPS = {"11", "11001"}
