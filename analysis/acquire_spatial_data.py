"""Pin 2020 Census tract geometry and ACS income data for the Step 3 analysis."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / "data" / "external" / "census-tracts-2020"
NYC_COUNTIES = {
    "005": "Bronx",
    "047": "Kings",
    "061": "New York",
    "081": "Queens",
    "085": "Richmond",
}
TRACT_LAYER = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/"
    "TIGERweb/tigerWMS_Census2020/MapServer/6"
)
ACS_BULK_BASE = (
    "https://www2.census.gov/programs-surveys/acs/summary_file/"
    "2020/prototype/5YRData"
)
USER_AGENT = "MSDS-NYPD-Shooting-Data/1.0 (reproducible research snapshot)"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_url(base: str, parameters: dict[str, str]) -> str:
    return f"{base}?{urllib.parse.urlencode(parameters)}"


def request_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Download failed ({error.code}) for {url}: {detail}") from error


def validate_existing() -> bool:
    manifest_path = DESTINATION / "manifest.json"
    if not manifest_path.exists():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        path = DESTINATION / entry["name"]
        if not path.exists() or sha256_file(path) != entry["sha256"]:
            return False
    return bool(manifest.get("files"))


def validate_tract_geojson(payload: bytes) -> dict[str, object]:
    document = json.loads(payload)
    features = document.get("features", [])
    if document.get("type") != "FeatureCollection" or not 1_500 <= len(features) <= 3_000:
        raise ValueError("Unexpected NYC Census tract GeoJSON response.")
    geoids = {feature.get("properties", {}).get("GEOID") for feature in features}
    if None in geoids or len(geoids) != len(features):
        raise ValueError("Census tract geometry contains missing or duplicate GEOIDs.")
    counties = {feature.get("properties", {}).get("COUNTY") for feature in features}
    if counties != set(NYC_COUNTIES):
        raise ValueError(f"Unexpected counties in tract geometry: {sorted(counties)}")
    return document


def parse_bulk_table(payload: bytes, table: str) -> dict[str, dict[str, str]]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")), delimiter="|")
    estimate = f"{table}_E001"
    margin = f"{table}_M001"
    if reader.fieldnames != ["GEO_ID", estimate, margin]:
        raise ValueError(f"Unexpected {table} bulk-file header: {reader.fieldnames}")

    rows: dict[str, dict[str, str]] = {}
    for row in reader:
        geo_id = row["GEO_ID"]
        if not geo_id.startswith("1400000US36"):
            continue
        geoid = geo_id.removeprefix("1400000US")
        county = geoid[2:5]
        if county in NYC_COUNTIES:
            rows[geoid] = {"estimate": row[estimate], "margin": row[margin]}
    if not 1_500 <= len(rows) <= 3_000:
        raise ValueError(f"Unexpected NYC tract count in {table}: {len(rows):,}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Replace the pinned snapshot intentionally.")
    args = parser.parse_args()

    if not args.force and validate_existing():
        print("Verified existing 2020 Census/ACS spatial snapshot.")
        return

    DESTINATION.mkdir(parents=True, exist_ok=True)
    tract_url = build_url(
        f"{TRACT_LAYER}/query",
        {
            "where": "STATE='36' AND COUNTY IN ('005','047','061','081','085')",
            "outFields": "GEOID,STATE,COUNTY,TRACT,BASENAME,NAME,AREALAND,AREAWATER,POP100",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        },
    )
    tract_payload = request_bytes(tract_url)
    validate_tract_geojson(tract_payload)

    population_url = f"{ACS_BULK_BASE}/acsdt5y2020-b01003.dat"
    income_url = f"{ACS_BULK_BASE}/acsdt5y2020-b19013.dat"
    population_rows = parse_bulk_table(request_bytes(population_url), "B01003")
    income_rows = parse_bulk_table(request_bytes(income_url), "B19013")
    if population_rows.keys() != income_rows.keys():
        raise ValueError("Population and income tables do not contain the same NYC tracts.")

    acs_rows: list[dict[str, object]] = []
    for geoid in sorted(population_rows):
        county = geoid[2:5]
        tract = geoid[5:]
        acs_rows.append(
            {
                "geoid": geoid,
                "name": f"Census Tract {tract[:4]}.{tract[4:]}, {NYC_COUNTIES[county]} County, New York",
                "state": geoid[:2],
                "county": county,
                "county_name": NYC_COUNTIES[county],
                "tract": tract,
                "population_acs5_2020": population_rows[geoid]["estimate"],
                "population_moe_acs5_2020": population_rows[geoid]["margin"],
                "median_household_income_acs5_2020": income_rows[geoid]["estimate"],
                "median_household_income_moe_acs5_2020": income_rows[geoid]["margin"],
            }
        )

    geoids = [str(row["geoid"]) for row in acs_rows]
    if len(geoids) != len(set(geoids)) or not 1_500 <= len(geoids) <= 3_000:
        raise ValueError("Unexpected ACS tract count or duplicate GEOID.")

    tract_path = DESTINATION / "nyc_census_tracts_2020.geojson"
    acs_path = DESTINATION / "nyc_tract_acs5_2020.csv"
    tract_path.write_bytes(tract_payload)
    with acs_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(acs_rows[0]))
        writer.writeheader()
        writer.writerows(sorted(acs_rows, key=lambda row: str(row["geoid"])))

    manifest = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "geography_vintage": "2020 Census tracts, January 1 2020 vintage",
        "estimate_vintage": "2020 ACS 5-year estimates",
        "nyc_counties": NYC_COUNTIES,
        "variables": {
            "B01003_001E": "Total population estimate",
            "B01003_001M": "Total population margin of error",
            "B19013_001E": "Median household income estimate",
            "B19013_001M": "Median household income margin of error",
        },
        "source_urls": [tract_url, population_url, income_url],
        "files": [
            {
                "name": tract_path.name,
                "sha256": sha256_file(tract_path),
                "rows": len(json.loads(tract_payload)["features"]),
            },
            {
                "name": acs_path.name,
                "sha256": sha256_file(acs_path),
                "rows": len(acs_rows),
            },
        ],
        "api_key_required": False,
    }
    (DESTINATION / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Pinned {len(acs_rows):,} NYC tract records under {DESTINATION.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
