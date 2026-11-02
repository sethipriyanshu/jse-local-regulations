#!/usr/bin/env bash
# Regenerate map boundaries and jurisdiction lists from Census Bureau files.
# Outputs are committed, so this only needs to run when updating the vintage.
#
#   ./scripts/build_geo.sh            # uses VINTAGE=2023
#
# Writes:
#   frontend/public/geo/us.topo.json   states + counties (1:20m cartographic boundaries)
#   backend/data/states.csv            GEOID,NAME,STUSPS
#   backend/data/counties.csv          GEOID,NAME,STUSPS
#   backend/data/places.csv            GEOID,NAME,STUSPS,LSAD (incorporated places only)
set -euo pipefail

VINTAGE="${VINTAGE:-2023}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
BASE="https://www2.census.gov/geo/tiger/GENZ${VINTAGE}/shp"
MAPSHAPER="npx -y mapshaper@0.7.101"

echo "==> Downloading Census ${VINTAGE} files"
curl -sfL -o "$WORK/states.zip" "$BASE/cb_${VINTAGE}_us_state_20m.zip"
curl -sfL -o "$WORK/counties.zip" "$BASE/cb_${VINTAGE}_us_county_20m.zip"
curl -sfL -o "$WORK/places.zip" \
  "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/${VINTAGE}_Gazetteer/${VINTAGE}_Gaz_place_national.zip"
(cd "$WORK" && unzip -q -o states.zip -d states && unzip -q -o counties.zip -d counties \
  && unzip -q -o places.zip -d places)

mkdir -p "$ROOT/frontend/public/geo" "$ROOT/backend/data"

echo "==> Building TopoJSON"
$MAPSHAPER -i "$WORK/states/cb_${VINTAGE}_us_state_20m.shp" "$WORK/counties/cb_${VINTAGE}_us_county_20m.shp" \
  combine-files \
  -rename-layers states,counties \
  -filter-fields GEOID,NAME,STUSPS target=states \
  -filter-fields GEOID,NAMELSAD,STUSPS,STATE_NAME target=counties \
  -rename-fields NAME=NAMELSAD target=counties \
  -proj wgs84 target=* \
  -simplify 40% keep-shapes target=* \
  -o "$ROOT/frontend/public/geo/us.topo.json" format=topojson quantization=1e5 target=*

echo "==> Writing jurisdiction CSVs"
$MAPSHAPER -i "$WORK/states/cb_${VINTAGE}_us_state_20m.shp" -filter-fields GEOID,NAME,STUSPS \
  -o "$ROOT/backend/data/states.csv" format=csv
$MAPSHAPER -i "$WORK/counties/cb_${VINTAGE}_us_county_20m.shp" -filter-fields GEOID,NAMELSAD,STUSPS \
  -rename-fields NAME=NAMELSAD -sort GEOID -o "$ROOT/backend/data/counties.csv" format=csv

# Gazetteer is tab-separated with padded headers. Keep places with a functioning
# government (FUNCSTAT A = active, B = active + statistical, C = consolidated);
# CDPs (S) have no permitting authority.
python3 - "$WORK/places/${VINTAGE}_Gaz_place_national.txt" "$ROOT/backend/data/places.csv" <<'PY'
import csv, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="latin-1") as f, open(dst, "w", newline="", encoding="utf-8") as out:
    rows = csv.DictReader(f, delimiter="\t")
    rows.fieldnames = [h.strip() for h in rows.fieldnames]
    w = csv.writer(out)
    w.writerow(["GEOID", "NAME", "STUSPS", "LSAD"])
    n = 0
    for r in rows:
        if r["FUNCSTAT"].strip() in {"A", "B", "C"}:
            w.writerow([r["GEOID"].strip(), r["NAME"].strip(), r["USPS"].strip(), r["LSAD"].strip()])
            n += 1
print(f"places: {n}")
PY

ls -la "$ROOT/frontend/public/geo/us.topo.json" "$ROOT/backend/data/"
