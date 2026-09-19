"""Acquire and validate the contextual datasets used in Step 4.

The checked-in snapshot is deliberately narrow: daily Central Park weather,
the federal holiday calendar, nationally salient championship-game dates, and
independently documented New York City political crowd events.  Running this
script without ``--force`` verifies the pinned files and does not contact the
network.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "external" / "contextual"
MANIFEST = OUT / "manifest.json"
START_YEAR = 2006
END_YEAR = 2025
NYC_TZ = ZoneInfo("America/New_York")

NOAA_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
CCC_DATAVERSE_FILES = (
    {
        "phase": "2017-2020",
        "doi": "doi:10.7910/DVN/6OPP7H",
        "version": "1.1",
        "file_id": 10808404,
        "separator": "\t",
    },
    {
        "phase": "2021-2024",
        "doi": "doi:10.7910/DVN/9MMYDI",
        "version": "2.1",
        "file_id": 10822959,
        "separator": "\t",
    },
    {
        "phase": "2025",
        "doi": "doi:10.7910/DVN/RI9JFU",
        "version": "18.0",
        "file_id": 14226873,
        "separator": ",",
    },
)
DATAVERSE_FILE_URL = "https://dataverse.harvard.edu/api/access/datafile/{file_id}"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(
    url: str,
    params: dict[str, object] | None = None,
    attempts: int = 3,
    headers: dict[str, str] | None = None,
) -> bytes:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers=headers or {})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return response.read()
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("unreachable")


def frame_to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")


def write_frame(frame: pd.DataFrame, name: str) -> dict[str, object]:
    payload = frame_to_csv_bytes(frame)
    path = OUT / name
    path.write_bytes(payload)
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "rows": len(frame),
        "sha256": sha256_bytes(payload),
    }


def acquire_weather() -> tuple[pd.DataFrame, dict[str, object]]:
    params = {
        "dataset": "daily-summaries",
        "stations": "USW00094728",
        "startDate": f"{START_YEAR}-01-01",
        "endDate": f"{END_YEAR}-12-31",
        "dataTypes": "TAVG,TMAX,TMIN,PRCP,SNOW,SNWD",
        "format": "csv",
        "units": "metric",
        "includeAttributes": "false",
        "includeStationName": "true",
    }
    source_url = f"{NOAA_URL}?{urllib.parse.urlencode(params)}"
    payload = fetch(NOAA_URL, params)
    source = pd.read_csv(io.BytesIO(payload), low_memory=False)
    required = {"STATION", "NAME", "DATE", "TMAX", "TMIN", "PRCP"}
    if not required.issubset(source.columns):
        raise ValueError(f"NOAA response is missing columns: {sorted(required - set(source.columns))}")
    source["DATE"] = pd.to_datetime(source["DATE"], errors="raise")
    for column in ("TAVG", "TMAX", "TMIN", "PRCP", "SNOW", "SNWD"):
        if column not in source:
            source[column] = pd.NA
        source[column] = pd.to_numeric(source[column], errors="coerce")
    source["TAVG"] = source["TAVG"].fillna((source["TMAX"] + source["TMIN"]) / 2)
    weather = source.rename(
        columns={
            "STATION": "station_id",
            "NAME": "station_name",
            "DATE": "date",
            "TAVG": "tavg_c",
            "TMAX": "tmax_c",
            "TMIN": "tmin_c",
            "PRCP": "precip_mm",
            "SNOW": "snow_mm",
            "SNWD": "snow_depth_mm",
        }
    )[
        [
            "station_id",
            "station_name",
            "date",
            "tavg_c",
            "tmax_c",
            "tmin_c",
            "precip_mm",
            "snow_mm",
            "snow_depth_mm",
        ]
    ].sort_values("date")
    expected = pd.date_range(f"{START_YEAR}-01-01", f"{END_YEAR}-12-31", freq="D")
    if weather["date"].duplicated().any() or not weather["date"].isin(expected).all():
        raise ValueError("NOAA weather dates are duplicated or outside the requested period.")
    if weather["date"].min() != expected.min() or weather["date"].max() != expected.max():
        raise ValueError("NOAA weather response does not cover the requested endpoints.")
    weather["date"] = weather["date"].dt.date.astype(str)
    meta = {
        "source_url": source_url,
        "source_sha256": sha256_bytes(payload),
        "station": "GHCND:USW00094728, NY City Central Park",
        "units": "metric as explicitly requested from the NCEI Access Data Service",
        "coverage": f"{weather['date'].min()} through {weather['date'].max()}",
        "tavg_imputation": "When TAVG was absent, arithmetic mean of TMAX and TMIN was used.",
        "missing_tavg_after_imputation": int(weather["tavg_c"].isna().sum()),
    }
    return weather, meta


def nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (occurrence - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def observed_date(actual: date) -> date:
    if actual.weekday() == 5:
        return actual - timedelta(days=1)
    if actual.weekday() == 6:
        return actual + timedelta(days=1)
    return actual


def holiday_calendar() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year in range(START_YEAR, END_YEAR + 1):
        holidays = [
            ("New Year's Day", date(year, 1, 1)),
            ("Birthday of Martin Luther King, Jr.", nth_weekday(year, 1, 0, 3)),
            ("Washington's Birthday", nth_weekday(year, 2, 0, 3)),
            ("Memorial Day", last_weekday(year, 5, 0)),
            ("Independence Day", date(year, 7, 4)),
            ("Labor Day", nth_weekday(year, 9, 0, 1)),
            ("Columbus Day", nth_weekday(year, 10, 0, 2)),
            ("Veterans Day", date(year, 11, 11)),
            ("Thanksgiving Day", nth_weekday(year, 11, 3, 4)),
            ("Christmas Day", date(year, 12, 25)),
        ]
        if year >= 2021:
            holidays.insert(4, ("Juneteenth National Independence Day", date(year, 6, 19)))
        for name, actual in holidays:
            observed = observed_date(actual)
            rows.append(
                {
                    "holiday_name": name,
                    "actual_date": actual.isoformat(),
                    "observed_date": observed.isoformat(),
                    "observed_differs": observed != actual,
                    "calendar_year": year,
                }
            )
    frame = pd.DataFrame(rows).sort_values(["actual_date", "holiday_name"]).reset_index(drop=True)
    if frame.duplicated(["holiday_name", "actual_date"]).any():
        raise ValueError("Generated holiday calendar contains duplicate named dates.")
    return frame


def event_headlines(event: dict[str, object]) -> list[str]:
    competitions = event.get("competitions") or []
    if not competitions:
        return []
    notes = competitions[0].get("notes") or []
    return [str(note.get("headline", "")) for note in notes]


def espn_championships() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    requests: list[dict[str, object]] = []
    definitions = (
        ("basketball", "nba", "NBA Finals", 1000),
        ("football", "nfl", "Super Bowl", 1000),
    )
    for sport, league, series, limit in definitions:
        for year in range(START_YEAR, END_YEAR + 1):
            date_queries = [str(year)]
            for date_query in date_queries:
                params = {"dates": date_query, "limit": limit}
                url = ESPN_SCOREBOARD.format(sport=sport, league=league)
                payload = fetch(url, params)
                requests.append(
                    {
                        "series": series,
                        "calendar_year": year,
                        "date_query": date_query,
                        "url": f"{url}?{urllib.parse.urlencode(params)}",
                        "sha256": sha256_bytes(payload),
                    }
                )
                data = json.loads(payload)
                for event in data.get("events", []):
                    competitions = event.get("competitions") or [{}]
                    competition_type = (competitions[0].get("type") or {}).get("abbreviation")
                    headlines = event_headlines(event)
                    if series == "NBA Finals":
                        keep = competition_type == "FINAL"
                    else:
                        keep = any(value.lower().startswith("super bowl") for value in headlines)
                    if not keep:
                        continue
                    headline = next(iter(headlines), series)
                    utc = datetime.fromisoformat(str(event["date"]).replace("Z", "+00:00"))
                    local = utc.astimezone(NYC_TZ)
                    rows.append(
                        {
                            "event_date": local.date().isoformat(),
                            "league": league.upper(),
                            "series": series,
                            "event_detail": headline,
                            "event_name": event.get("name"),
                            "local_start": local.isoformat(),
                            "source_system": "ESPN scoreboard",
                            "source_event_id": str(event.get("id")),
                            "source_url": f"{url}?{urllib.parse.urlencode(params)}",
                        }
                    )
            if series == "NBA Finals" and not any(
                row["series"] == series and row["event_date"].startswith(str(year)) for row in rows
            ):
                # Month queries retrieve the same typed records when a year
                # page omits them (2012) or hits its ceiling before the delayed
                # July 2021 Finals.  No individual game dates are guessed.
                for month in (6, 7):
                    params = {"dates": f"{year}{month:02d}", "limit": 300}
                    url = ESPN_SCOREBOARD.format(sport=sport, league=league)
                    payload = fetch(url, params)
                    requests.append(
                        {
                            "series": series,
                            "calendar_year": year,
                            "date_query": f"{year}{month:02d}",
                            "url": f"{url}?{urllib.parse.urlencode(params)}",
                            "sha256": sha256_bytes(payload),
                        }
                    )
                    for event in json.loads(payload).get("events", []):
                        competitions = event.get("competitions") or [{}]
                        if (competitions[0].get("type") or {}).get("abbreviation") != "FINAL":
                            continue
                        utc = datetime.fromisoformat(str(event["date"]).replace("Z", "+00:00"))
                        local = utc.astimezone(NYC_TZ)
                        headlines = event_headlines(event)
                        rows.append(
                            {
                                "event_date": local.date().isoformat(),
                                "league": league.upper(),
                                "series": series,
                                "event_detail": next(iter(headlines), series),
                                "event_name": event.get("name"),
                                "local_start": local.isoformat(),
                                "source_system": "ESPN scoreboard",
                                "source_event_id": str(event.get("id")),
                                "source_url": f"{url}?{urllib.parse.urlencode(params)}",
                            }
                        )
    return rows, requests


def mlb_world_series() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    requests: list[dict[str, object]] = []
    for year in range(START_YEAR, END_YEAR + 1):
        params = {
            "sportId": 1,
            "gameTypes": "W",
            "startDate": f"10/01/{year}",
            "endDate": f"11/15/{year}",
            "hydrate": "team",
        }
        payload = fetch(MLB_SCHEDULE, params)
        source_url = f"{MLB_SCHEDULE}?{urllib.parse.urlencode(params)}"
        requests.append(
            {
                "series": "World Series",
                "calendar_year": year,
                "url": source_url,
                "sha256": sha256_bytes(payload),
            }
        )
        data = json.loads(payload)
        for date_block in data.get("dates", []):
            for game in date_block.get("games", []):
                if game.get("seriesDescription") != "World Series":
                    continue
                utc = datetime.fromisoformat(str(game["gameDate"]).replace("Z", "+00:00"))
                local = utc.astimezone(NYC_TZ)
                away = game.get("teams", {}).get("away", {}).get("team", {}).get("name")
                home = game.get("teams", {}).get("home", {}).get("team", {}).get("name")
                rows.append(
                    {
                        "event_date": local.date().isoformat(),
                        "league": "MLB",
                        "series": "World Series",
                        "event_detail": game.get("description") or "World Series game",
                        "event_name": f"{away} at {home}",
                        "local_start": local.isoformat(),
                        "source_system": "MLB Stats API",
                        "source_event_id": str(game.get("gamePk")),
                        "source_url": source_url,
                    }
                )
    return rows, requests


def acquire_sports() -> tuple[pd.DataFrame, dict[str, object]]:
    espn_rows, espn_requests = espn_championships()
    mlb_rows, mlb_requests = mlb_world_series()
    sports = pd.DataFrame(espn_rows + mlb_rows).drop_duplicates("source_event_id")
    sports = sports.sort_values(["event_date", "league", "source_event_id"]).reset_index(drop=True)
    expected_series = {"Super Bowl", "NBA Finals", "World Series"}
    if set(sports["series"]) != expected_series:
        raise ValueError(f"Championship series missing from acquired data: {expected_series - set(sports['series'])}")
    year_counts = sports.assign(year=pd.to_datetime(sports["event_date"]).dt.year).groupby(["series", "year"]).size()
    if (year_counts.groupby(level=0).size() != (END_YEAR - START_YEAR + 1)).any():
        present = set(year_counts.index)
        missing = {
            series: [year for year in range(START_YEAR, END_YEAR + 1) if (series, year) not in present]
            for series in sorted(expected_series)
        }
        raise ValueError(f"At least one championship series is missing a calendar year: {missing}")
    if not year_counts.loc["Super Bowl"].eq(1).all():
        raise ValueError("The Super Bowl universe must contain exactly one game per calendar year.")
    return sports, {
        "event_universe": (
            "All Super Bowl, NBA Finals, and World Series game dates from 2006 through 2025. "
            "Dates are converted from source timestamps to America/New_York."
        ),
        "requests": espn_requests + mlb_requests,
        "rows_by_series": {key: int(value) for key, value in sports.groupby("series").size().items()},
    }


def acquire_protests() -> tuple[pd.DataFrame, dict[str, object]]:
    phase_frames: list[pd.DataFrame] = []
    source_entries: list[dict[str, object]] = []
    browser_header = {"User-Agent": "Mozilla/5.0"}
    nyc_localities = {
        "new york", "new york city", "manhattan", "brooklyn", "bronx", "queens",
        "staten island", "flushing", "jamaica", "long island city",
    }

    def first_column(frame: pd.DataFrame, *names: str) -> pd.Series:
        for name in names:
            if name in frame:
                return frame[name]
        return pd.Series(pd.NA, index=frame.index, dtype="object")

    for source_info in CCC_DATAVERSE_FILES:
        url = DATAVERSE_FILE_URL.format(file_id=source_info["file_id"])
        payload = fetch(url, headers=browser_header)
        source = pd.read_csv(
            io.BytesIO(payload), sep=str(source_info["separator"]), low_memory=False,
            encoding="utf-8", encoding_errors="replace",
        )
        source.columns = [str(column).strip() for column in source.columns]
        event_date = pd.to_datetime(first_column(source, "date"), errors="coerce")
        state = first_column(source, "resolved_state", "state").astype("string").str.upper()
        locality = first_column(source, "resolved_locality", "locality").astype("string")
        county = first_column(source, "resolved_county", "county").astype("string")
        county_match = county.fillna("").str.contains(
            r"(?:^|;\s*)(?:New York|Kings|Bronx|Queens|Richmond)(?: County)?(?:;|$)",
            case=False, regex=True,
        )
        locality_match = locality.fillna("").str.strip().str.lower().isin(nyc_localities)
        online_values = first_column(source, "online").astype("string").str.strip().str.lower()
        online = online_values.isin({"1", "true", "yes"})
        include = (
            state.eq("NY") & (county_match | locality_match) & ~online
            & event_date.dt.year.between(2017, END_YEAR)
        )
        selected = source.loc[include].copy()
        selected_dates = event_date.loc[include]
        phase = pd.DataFrame(
            {
                "event_date": selected_dates.dt.date.astype(str),
                "city_town": first_column(selected, "resolved_locality", "locality"),
                "state": first_column(selected, "resolved_state", "state"),
                "county": first_column(selected, "resolved_county", "county"),
                "location_detail": first_column(selected, "location", "location_detail"),
                "event_type": first_column(selected, "event_type", "type"),
                "macro_event": first_column(selected, "macroevent"),
                "actor": first_column(selected, "organizations", "actors"),
                "claim": first_column(selected, "claims_summary", "claims"),
                "estimate_low": first_column(selected, "size_low"),
                "estimate_high": first_column(selected, "size_high"),
                "estimate_text": first_column(selected, "size_text"),
                "estimate_category": first_column(selected, "size_cat"),
                "reported_arrests": first_column(selected, "arrests"),
                "reported_participant_injuries": first_column(
                    selected, "participant_injuries", "injuries_crowd"
                ),
                "reported_police_injuries": first_column(selected, "police_injuries", "injuries_police"),
                "reported_property_damage": first_column(selected, "property_damage"),
                "source_1": first_column(selected, "source1", "source_1"),
                "source_2": first_column(selected, "source2", "source_2"),
                "source_3": first_column(selected, "source3", "source_3"),
                "latitude": first_column(selected, "lat"),
                "longitude": first_column(selected, "lon"),
                "ccc_phase": str(source_info["phase"]),
                "source_doi": str(source_info["doi"]),
                "source_version": str(source_info["version"]),
            }
        )
        phase_frames.append(phase)
        source_entries.append(
            {
                **source_info,
                "source_url": url,
                "source_sha256": sha256_bytes(payload),
                "source_rows": len(source),
                "nyc_rows_through_2025": len(phase),
            }
        )
    protests = pd.concat(phase_frames, ignore_index=True).sort_values(
        ["event_date", "city_town", "event_type"], na_position="last"
    )
    if protests.empty or protests["event_date"].duplicated().all():
        raise ValueError("CCC filter did not produce a usable NYC event set.")
    covered_years = set(pd.to_datetime(protests["event_date"]).dt.year.unique())
    expected_years = set(range(2017, END_YEAR + 1))
    if covered_years != expected_years:
        raise ValueError(f"CCC NYC subset is missing years: {sorted(expected_years - covered_years)}")
    return protests.reset_index(drop=True), {
        "source_datasets": source_entries,
        "event_universe": (
            "In-person independent political crowd events in the five New York City counties, "
            "2017 through 2025, as recorded by the Crowd Counting Consortium. Multiple events on "
            "one date remain separate records and are collapsed only for city-day comparisons."
        ),
        "coverage": f"{protests['event_date'].min()} through {protests['event_date'].max()}",
        "rows": len(protests),
        "distinct_event_days": int(protests["event_date"].nunique()),
        "known_limitations": (
            "CCC begins in 2017, relies on publicly reported and fact-checked events, can lag, and "
            "does not claim perfect capture of every political crowd. No 2006-2016 comparison is made."
        ),
    }


def audit_legacy_inputs() -> dict[str, object]:
    weather_dir = ROOT / "data" / "external" / "weather"
    holidays = ROOT / "data" / "external" / "holidays" / "US_hol_df.csv"
    sports = ROOT / "data" / "external" / "events" / "Sports_Holidays_3.csv"
    protests = ROOT / "data" / "external" / "events" / "Protest_Dates.csv"
    return {
        "weather": {
            "status": "not used",
            "files": sorted(path.name for path in weather_dir.glob("*") if path.is_file()),
            "reason": "Mixed sources, incompatible granularities, incomplete coverage, and no pinned provenance manifest.",
        },
        "holidays": {
            "status": "not used",
            "path": str(holidays.relative_to(ROOT)).replace("\\", "/"),
            "reason": "Ends in 2023 and does not preserve its generating rules or source provenance.",
        },
        "sports": {
            "status": "candidate list only; independently reconstructed",
            "path": str(sports.relative_to(ROOT)).replace("\\", "/"),
            "reason": "Coherent championship-only scope but no source provenance and no complete 2025 season.",
        },
        "political_events": {
            "status": "not used",
            "path": str(protests.relative_to(ROOT)).replace("\\", "/"),
            "reason": "Hand-selected dates mix protests with elections, disasters, rulings, and other event classes.",
        },
    }


def verify_snapshot() -> dict[str, object]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for name, entry in manifest["files"].items():
        path = ROOT / entry["path"]
        if not path.exists():
            raise FileNotFoundError(path)
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            raise ValueError(f"Checksum mismatch for {name}: {actual} != {entry['sha256']}")
    return manifest


def build_snapshot() -> dict[str, object]:
    OUT.mkdir(parents=True, exist_ok=True)
    weather, weather_meta = acquire_weather()
    holidays = holiday_calendar()
    sports, sports_meta = acquire_sports()
    protests, protests_meta = acquire_protests()
    files = {
        "weather": write_frame(weather, "central_park_weather_2006_2025.csv"),
        "holidays": write_frame(holidays, "us_federal_holidays_2006_2025.csv"),
        "sports": write_frame(sports, "championship_games_2006_2025.csv"),
        "political_events": write_frame(protests, "nyc_political_crowds_2017_2025.csv"),
    }
    manifest = {
        "schema_version": 1,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_boundary": f"{START_YEAR}-01-01 through {END_YEAR}-12-31",
        "files": files,
        "sources": {
            "weather": weather_meta,
            "holidays": {
                "source_url": "https://www.opm.gov/policy-data-oversight/pay-leave/pay-administration/fact-sheets/holidays-work-schedules-and-pay/",
                "event_universe": "Actual dates and observed dates for the 11 federal holidays defined by 5 U.S.C. 6103; Juneteenth begins in 2021.",
                "primary_analysis": "Actual calendar dates only; observed dates are retained but not substituted.",
            },
            "sports": sports_meta,
            "political_events": protests_meta,
        },
        "legacy_input_audit": audit_legacy_inputs(),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return verify_snapshot()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Replace the pinned snapshot from its sources.")
    args = parser.parse_args()
    if MANIFEST.exists() and not args.force:
        manifest = verify_snapshot()
        print(f"Verified {len(manifest['files'])} contextual files; snapshot unchanged.")
        return
    manifest = build_snapshot()
    print(f"Pinned {len(manifest['files'])} contextual files under {OUT.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
