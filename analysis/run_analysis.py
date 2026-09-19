"""Build the repaired descriptive and forecasting analysis."""

from __future__ import annotations

import argparse
import json
import math
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OFFICIAL = RAW / "official"
RESULTS = Path(__file__).resolve().parent / "results"
EXTERNAL = ROOT / "data" / "external"
CONTEXTUAL = EXTERNAL / "contextual"
FORECAST_SEED = 20260914
PRIMARY_FORECAST_MODEL = "dynamic_count_ensemble"
DYNAMIC_LOCAL_WINDOW_DAYS = 28
DYNAMIC_WEEKDAY_SHRINKAGE = 0.5
DYNAMIC_AR_PENALTY = 50.0
DYNAMIC_LOCAL_WEIGHT = 0.75
DYNAMIC_AR_WEIGHT = 0.25
SPATIAL_SEED = 20260917
CONTEXT_SEED = 20260918

UNKNOWN_TOKENS = {"", "UNKNOWN", "NULL", "(NULL)", "N/A", "NA", "NAN", "NONE"}
VALID_AGE_GROUPS = {"<18", "18-24", "25-44", "45-64", "65+"}
PERIODS = (
    ("context", "pre_2020_decline", 2006, 2019, "Context-defined pre-2020 period"),
    ("context", "2020_2021_discontinuity", 2020, 2021, "Context-defined discontinuity period"),
    ("context", "post_2021_decline", 2022, 2025, "Context-defined post-2021 period"),
    ("sensitivity", "early_decline", 2006, 2012, "Best-BIC segmented-linear sensitivity"),
    ("sensitivity", "later_pre_2020_decline", 2013, 2019, "Best-BIC segmented-linear sensitivity"),
    ("sensitivity", "2020_onward", 2020, 2025, "Best-BIC segmented-linear sensitivity"),
)


@dataclass
class CleanData:
    shootings: pd.DataFrame
    victims: pd.DataFrame
    offenders: pd.DataFrame
    legacy: pd.DataFrame
    audit: dict[str, object]


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"INCIDENT_KEY": "string"}, low_memory=False)


def latest_complete_year(dates: pd.Series) -> int:
    maximum = pd.Timestamp(dates.max())
    if maximum.month == 12 and maximum.day == 31:
        return int(maximum.year)
    return int(maximum.year - 1)


def repair_coordinates(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    repaired = frame.copy()
    source_lat = pd.to_numeric(repaired["Latitude"], errors="coerce")
    source_lon = pd.to_numeric(repaired["Longitude"], errors="coerce")
    normal = source_lat.between(40.0, 41.0) & source_lon.between(-75.0, -73.0)
    swapped = source_lat.between(-75.0, -73.0) & source_lon.between(40.0, 41.0)
    repaired["latitude_clean"] = np.where(swapped, source_lon, source_lat)
    repaired["longitude_clean"] = np.where(swapped, source_lat, source_lon)
    unresolved = ~(normal | swapped)
    repaired.loc[unresolved, ["latitude_clean", "longitude_clean"]] = np.nan
    repaired["coordinate_status"] = np.select(
        [normal, swapped], ["as_published", "reversed_in_export"], default="unresolved"
    )
    return repaired, {
        "as_published": int(normal.sum()),
        "reversed_in_export": int(swapped.sum()),
        "unresolved": int(unresolved.sum()),
    }


def clean_data() -> CleanData:
    shootings_raw = read_csv(OFFICIAL / "shootings_2006_present.csv")
    victims_raw = read_csv(OFFICIAL / "shooting_victims_2006_present.csv")
    offenders_raw = read_csv(OFFICIAL / "shooting_offenders_2006_present.csv")
    legacy_raw = read_csv(RAW / "NYPD_Shooting_Incident_Data__Historic_.csv")

    shootings = shootings_raw.drop_duplicates().copy()
    victims = victims_raw.drop_duplicates().copy()
    offenders = offenders_raw.drop_duplicates().copy()
    legacy = legacy_raw.drop_duplicates().copy()

    shootings["occur_date"] = pd.to_datetime(shootings["OCCUR_DATE"], format="%m/%d/%Y", errors="coerce")
    legacy["occur_date"] = pd.to_datetime(legacy["OCCUR_DATE"], format="%m/%d/%Y", errors="coerce")
    if shootings["occur_date"].isna().any() or legacy["occur_date"].isna().any():
        raise ValueError("Unparseable occurrence dates found.")
    shootings["occur_hour"] = pd.to_numeric(
        shootings["OCCUR_TIME"].astype("string").str.extract(r"^(\d{1,2}):", expand=False),
        errors="coerce",
    )
    invalid_hour = ~shootings["occur_hour"].between(0, 23)
    shootings.loc[invalid_hour, "occur_hour"] = np.nan
    shootings, coordinate_counts = repair_coordinates(shootings)

    date_lookup = shootings[["INCIDENT_KEY", "occur_date"]]
    victims = victims.merge(date_lookup, on="INCIDENT_KEY", how="left", validate="many_to_one")
    offenders = offenders.merge(date_lookup, on="INCIDENT_KEY", how="left", validate="many_to_one")

    complete_year = latest_complete_year(shootings["occur_date"])
    incident_keys = set(shootings["INCIDENT_KEY"].dropna())
    audit: dict[str, object] = {
        "current_snapshot": {
            "date_min": shootings["occur_date"].min().date().isoformat(),
            "date_max": shootings["occur_date"].max().date().isoformat(),
            "latest_complete_year": complete_year,
        },
        "shootings": {
            "raw_rows": len(shootings_raw),
            "exact_duplicates_removed": len(shootings_raw) - len(shootings),
            "clean_rows": len(shootings),
            "unique_incident_keys": int(shootings["INCIDENT_KEY"].nunique()),
            "duplicate_incident_keys": int(shootings.duplicated("INCIDENT_KEY").sum()),
            "invalid_occurrence_hours": int(invalid_hour.sum()),
            "coordinate_status": coordinate_counts,
        },
        "victims": {
            "raw_rows": len(victims_raw),
            "exact_duplicates_removed": len(victims_raw) - len(victims),
            "clean_rows": len(victims),
            "unique_victim_ids": int(victims["VICTIM_ID"].nunique()),
            "orphan_incident_keys": len(set(victims["INCIDENT_KEY"].dropna()) - incident_keys),
            "orphan_rows": int(victims["occur_date"].isna().sum()),
        },
        "offenders": {
            "raw_rows": len(offenders_raw),
            "exact_duplicates_removed": len(offenders_raw) - len(offenders),
            "clean_rows": len(offenders),
            "unique_offender_ids": int(offenders["PERP_ID"].nunique()),
            "orphan_incident_keys": len(set(offenders["INCIDENT_KEY"].dropna()) - incident_keys),
            "orphan_rows": int(offenders["occur_date"].isna().sum()),
        },
        "legacy_snapshot": {
            "raw_rows": len(legacy_raw),
            "exact_duplicates_removed": len(legacy_raw) - len(legacy),
            "rows": len(legacy),
            "unique_incident_keys": int(legacy["INCIDENT_KEY"].nunique()),
            "repeated_incident_rows": int(legacy.duplicated("INCIDENT_KEY").sum()),
            "maximum_rows_per_incident": int(legacy.groupby("INCIDENT_KEY").size().max()),
            "date_min": legacy["occur_date"].min().date().isoformat(),
            "date_max": legacy["occur_date"].max().date().isoformat(),
        },
    }
    return CleanData(shootings, victims, offenders, legacy, audit)


def annual_counts(data: CleanData) -> pd.DataFrame:
    shootings = data.shootings.assign(year=data.shootings["occur_date"].dt.year)
    victims = data.victims.dropna(subset=["occur_date"]).assign(year=lambda x: x["occur_date"].dt.year)
    offenders = data.offenders.dropna(subset=["occur_date"]).assign(year=lambda x: x["occur_date"].dt.year)
    complete = int(data.audit["current_snapshot"]["latest_complete_year"])

    result = shootings.groupby("year").size().rename("incidents").to_frame()
    result = result.join(victims.groupby("year").size().rename("victims"), how="outer")
    result = result.join(offenders.groupby("year").size().rename("offender_records"), how="outer")
    fatal = victims["STAT_MURDER_FLG"].astype("string").str.upper().eq("Y")
    result = result.join(victims[fatal].groupby("year").size().rename("fatal_victims"), how="outer")
    result = result.join(
        victims[fatal].groupby("year")["INCIDENT_KEY"].nunique().rename("fatal_incidents"), how="outer"
    )
    result = result.fillna(0).astype(int).reset_index()
    result["victims_per_incident"] = result["victims"] / result["incidents"]
    result["is_complete_year"] = result["year"] <= complete
    return result


def reconciliation(data: CleanData) -> pd.DataFrame:
    legacy = data.legacy.assign(year=data.legacy["occur_date"].dt.year)
    shootings = data.shootings.assign(year=data.shootings["occur_date"].dt.year)
    victims = data.victims.dropna(subset=["occur_date"]).assign(year=lambda x: x["occur_date"].dt.year)
    table = legacy.groupby("year").agg(
        legacy_rows=("INCIDENT_KEY", "size"), legacy_unique_incidents=("INCIDENT_KEY", "nunique")
    )
    table = table.join(shootings.groupby("year").size().rename("current_incidents"), how="left")
    table = table.join(victims.groupby("year").size().rename("current_victims"), how="left")
    table = table.reset_index()
    table["legacy_rows_minus_current_victims"] = table["legacy_rows"] - table["current_victims"]
    table["legacy_unique_minus_current_incidents"] = (
        table["legacy_unique_incidents"] - table["current_incidents"]
    )
    return table


def linear_slope(year: pd.Series, value: pd.Series) -> float:
    if len(year) < 2:
        return math.nan
    return float(np.polyfit(year.to_numpy(dtype=float), value.to_numpy(dtype=float), 1)[0])


def period_summary(annual: pd.DataFrame, complete_year: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for family, name, start, planned_end, basis in PERIODS:
        end = min(planned_end, complete_year)
        subset = annual[annual["year"].between(start, end)].copy()
        if subset.empty:
            continue
        first = subset.iloc[0]
        last = subset.iloc[-1]
        rows.append(
            {
                "period_family": family,
                "period": name,
                "start_year": start,
                "end_year": end,
                "basis": basis,
                "years": len(subset),
                "incidents": int(subset["incidents"].sum()),
                "annual_mean_incidents": float(subset["incidents"].mean()),
                "first_year_incidents": int(first["incidents"]),
                "last_year_incidents": int(last["incidents"]),
                "first_to_last_change_pct": float(
                    (last["incidents"] - first["incidents"]) / first["incidents"] * 100
                ),
                "ols_slope_incidents_per_year": linear_slope(subset["year"], subset["incidents"]),
                "victims": int(subset["victims"].sum()),
                "victims_per_incident": float(subset["victims"].sum() / subset["incidents"].sum()),
                "fatal_victims": int(subset["fatal_victims"].sum()),
            }
        )
    return pd.DataFrame(rows)


def ytd_comparison(data: CleanData) -> pd.DataFrame:
    boundary = pd.Timestamp(data.shootings["occur_date"].max())
    rows: list[dict[str, object]] = []
    for year in range(max(2006, boundary.year - 5), boundary.year + 1):
        cutoff = pd.Timestamp(year=year, month=boundary.month, day=boundary.day)
        start = pd.Timestamp(year=year, month=1, day=1)
        incident_keys = data.shootings.loc[data.shootings["occur_date"].between(start, cutoff), "INCIDENT_KEY"]
        victim_subset = data.victims[data.victims["INCIDENT_KEY"].isin(set(incident_keys))]
        offender_subset = data.offenders[data.offenders["INCIDENT_KEY"].isin(set(incident_keys))]
        rows.append(
            {
                "year": year,
                "through_month_day": boundary.strftime("%m-%d"),
                "incidents": len(incident_keys),
                "victims": len(victim_subset),
                "fatal_victims": int(victim_subset["STAT_MURDER_FLG"].astype("string").str.upper().eq("Y").sum()),
                "offender_records": len(offender_subset),
            }
        )
    result = pd.DataFrame(rows)
    result["incident_change_from_prior_year_pct"] = result["incidents"].pct_change() * 100
    return result


def _segment_rss(years: np.ndarray, values: np.ndarray) -> float:
    coefficient = np.polyfit(years, values, 1)
    residual = values - np.polyval(coefficient, years)
    return float(np.square(residual).sum())


def changepoint_sensitivity(annual: pd.DataFrame, max_breaks: int = 2, min_segment: int = 4) -> pd.DataFrame:
    complete = annual[annual["is_complete_year"]].copy()
    years = complete["year"].to_numpy(dtype=float)
    values = complete["incidents"].to_numpy(dtype=float)
    n = len(years)
    candidates: list[dict[str, object]] = []

    configurations: list[tuple[int, ...]] = [()]
    for first in range(min_segment, n - min_segment + 1):
        configurations.append((first,))
    if max_breaks >= 2:
        for first in range(min_segment, n - 2 * min_segment + 1):
            for second in range(first + min_segment, n - min_segment + 1):
                configurations.append((first, second))

    for breaks in configurations:
        boundaries = (0,) + breaks + (n,)
        rss = sum(_segment_rss(years[a:b], values[a:b]) for a, b in zip(boundaries[:-1], boundaries[1:]))
        parameters = 2 * (len(breaks) + 1) + len(breaks)
        bic = n * math.log(max(rss / n, 1e-12)) + parameters * math.log(n)
        break_years = [int(years[index]) for index in breaks]
        candidates.append(
            {
                "number_of_breaks": len(breaks),
                "candidate_segment_start_years": ";".join(map(str, break_years)) or "none",
                "rss": rss,
                "bic": bic,
                "minimum_segment_years": min_segment,
            }
        )
    result = pd.DataFrame(candidates).sort_values("bic").reset_index(drop=True)
    result["delta_bic"] = result["bic"] - result["bic"].min()
    return result


def temporal_tables(data: CleanData, complete_year: int) -> dict[str, pd.DataFrame]:
    incidents = data.shootings[data.shootings["occur_date"].dt.year <= complete_year].copy()
    date_index = pd.date_range(incidents["occur_date"].min(), f"{complete_year}-12-31", freq="D")
    daily = incidents.groupby("occur_date").size().reindex(date_index, fill_value=0).rename("incidents")
    daily.index.name = "date"

    calendar = pd.DataFrame(index=date_index)
    calendar["month"] = calendar.index.month
    calendar["weekday_number"] = calendar.index.dayofweek
    calendar["weekday"] = calendar.index.day_name()
    calendar["incidents"] = daily
    month = calendar.groupby("month").agg(incidents=("incidents", "sum"), calendar_days=("incidents", "size"))
    month["incidents_per_calendar_day"] = month["incidents"] / month["calendar_days"]
    month["month_name"] = pd.to_datetime(month.index, format="%m").month_name()
    month = month.reset_index()[["month", "month_name", "incidents", "calendar_days", "incidents_per_calendar_day"]]

    weekday = calendar.groupby(["weekday_number", "weekday"]).agg(
        incidents=("incidents", "sum"), calendar_days=("incidents", "size")
    )
    weekday["incidents_per_calendar_day"] = weekday["incidents"] / weekday["calendar_days"]
    weekday = weekday.reset_index().sort_values("weekday_number")

    valid_hours = incidents.dropna(subset=["occur_hour"]).copy()
    hour = valid_hours.groupby("occur_hour").size().reindex(range(24), fill_value=0).rename("incidents").to_frame()
    hour["share_of_incidents_with_valid_time"] = hour["incidents"] / hour["incidents"].sum()
    hour = hour.reset_index().rename(columns={"index": "hour"})

    return {"daily_incidents": daily.reset_index(), "temporal_month": month, "temporal_weekday": weekday, "temporal_hour": hour}


def _design_dummies(values: pd.Series, prefix: str) -> pd.DataFrame:
    return pd.get_dummies(values.astype("string"), prefix=prefix, drop_first=True, dtype=float)


def _poisson_fit(
    x: np.ndarray, y: np.ndarray, hac_lags: int = 14
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit a Poisson log-link model and return HAC-robust covariance."""
    beta = np.zeros(x.shape[1], dtype=float)
    penalty = np.eye(x.shape[1]) * 1e-8
    penalty[0, 0] = 0
    for _ in range(120):
        eta = np.clip(x @ beta, -12, 12)
        mu = np.exp(eta)
        z = eta + (y - mu) / np.maximum(mu, 1e-10)
        weighted_x = x * np.sqrt(mu)[:, None]
        lhs = weighted_x.T @ weighted_x + penalty
        rhs = weighted_x.T @ (z * np.sqrt(mu))
        updated = np.linalg.solve(lhs, rhs)
        if np.max(np.abs(updated - beta)) < 1e-9:
            beta = updated
            break
        beta = updated
    mu = np.exp(np.clip(x @ beta, -12, 12))
    bread = np.linalg.pinv((x * mu[:, None]).T @ x + penalty)
    scores = x * (y - mu)[:, None]
    meat = scores.T @ scores
    maximum_lag = min(hac_lags, len(scores) - 1)
    for lag in range(1, maximum_lag + 1):
        weight = 1 - lag / (maximum_lag + 1)
        cross = scores[lag:].T @ scores[:-lag]
        meat += weight * (cross + cross.T)
    covariance = bread @ meat @ bread
    return beta, covariance, mu


def seasonal_context(daily: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["year"] = frame["date"].dt.year
    frame["season"] = pd.Categorical(
        np.select(
            [
                frame["date"].dt.month.isin([12, 1, 2]),
                frame["date"].dt.month.isin([3, 4, 5]),
                frame["date"].dt.month.isin([6, 7, 8]),
            ],
            ["Winter", "Spring", "Summer"],
            default="Autumn",
        ),
        categories=["Winter", "Spring", "Summer", "Autumn"],
        ordered=True,
    )
    by_year = frame.groupby(["year", "season"], observed=True).agg(
        incidents=("incidents", "sum"), calendar_days=("incidents", "size")
    ).reset_index()
    by_year["incidents_per_calendar_day"] = by_year["incidents"] / by_year["calendar_days"]
    summary = frame.groupby("season", observed=True).agg(
        incidents=("incidents", "sum"), calendar_days=("incidents", "size")
    ).reset_index()
    summary["incidents_per_calendar_day"] = summary["incidents"] / summary["calendar_days"]
    standard_error = np.sqrt(summary["incidents"]) / summary["calendar_days"]
    summary["rate_lower_95"] = np.maximum(0, summary["incidents_per_calendar_day"] - 1.96 * standard_error)
    summary["rate_upper_95"] = summary["incidents_per_calendar_day"] + 1.96 * standard_error
    return {"seasonal_by_year": by_year, "seasonal_summary": summary}


def weather_context(daily: pd.DataFrame) -> dict[str, pd.DataFrame]:
    weather = pd.read_csv(CONTEXTUAL / "central_park_weather_2006_2025.csv")
    weather["date"] = pd.to_datetime(weather["date"], errors="raise")
    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame = frame.merge(weather, on="date", how="left", validate="one_to_one")
    if frame["tavg_c"].isna().any():
        raise ValueError("Daily incident series does not have complete Central Park average temperature coverage.")
    frame["year"] = frame["date"].dt.year
    frame["month"] = frame["date"].dt.month
    frame["weekday"] = frame["date"].dt.dayofweek

    calendar = pd.concat(
        [
            pd.Series(1.0, index=frame.index, name="intercept"),
            _design_dummies(frame["year"], "year"),
            _design_dummies(frame["month"], "month"),
            _design_dummies(frame["weekday"], "weekday"),
        ],
        axis=1,
    )
    linear = calendar.copy()
    linear["temperature_5c"] = (frame["tavg_c"] - frame["tavg_c"].mean()) / 5
    beta, covariance, _ = _poisson_fit(linear.to_numpy(), frame["incidents"].to_numpy(dtype=float))
    index = list(linear.columns).index("temperature_5c")
    coefficient = float(beta[index])
    standard_error = float(np.sqrt(max(covariance[index, index], 0)))
    association = pd.DataFrame(
        [
            {
                "model": "Poisson log-link with year, month, and weekday fixed effects; 14-day HAC uncertainty",
                "days": len(frame),
                "temperature_increment_c": 5,
                "incidence_rate_ratio": math.exp(coefficient),
                "lower_95": math.exp(coefficient - 1.96 * standard_error),
                "upper_95": math.exp(coefficient + 1.96 * standard_error),
                "coefficient_log_rate": coefficient,
                "robust_standard_error": standard_error,
            }
        ]
    )

    breaks = [-np.inf, 0, 5, 10, 15, 20, 25, np.inf]
    labels = ["Below 0", "0 to <5", "5 to <10", "10 to <15", "15 to <20", "20 to <25", "25 or above"]
    frame["temperature_bin"] = pd.cut(frame["tavg_c"], bins=breaks, labels=labels, right=False)
    reference = "15 to <20"
    indicators = pd.get_dummies(frame["temperature_bin"], dtype=float)
    indicators = indicators[[label for label in labels if label != reference]]
    binned = pd.concat([calendar, indicators], axis=1)
    beta_bins, covariance_bins, _ = _poisson_fit(
        binned.to_numpy(), frame["incidents"].to_numpy(dtype=float)
    )
    bin_rows: list[dict[str, object]] = []
    for label in labels:
        subset = frame[frame["temperature_bin"].eq(label)]
        if label == reference:
            coefficient_bin = 0.0
            error_bin = 0.0
        else:
            column_index = list(binned.columns).index(label)
            coefficient_bin = float(beta_bins[column_index])
            error_bin = float(np.sqrt(max(covariance_bins[column_index, column_index], 0)))
        bin_rows.append(
            {
                "temperature_bin": label,
                "reference_bin": label == reference,
                "days": len(subset),
                "incidents": int(subset["incidents"].sum()),
                "raw_incidents_per_day": float(subset["incidents"].mean()),
                "adjusted_incidence_rate_ratio": math.exp(coefficient_bin),
                "lower_95": math.exp(coefficient_bin - 1.96 * error_bin),
                "upper_95": math.exp(coefficient_bin + 1.96 * error_bin),
            }
        )
    coverage = pd.DataFrame(
        [
            {
                "station_id": weather["station_id"].iloc[0],
                "station_name": weather["station_name"].iloc[0],
                "start_date": weather["date"].min().date().isoformat(),
                "end_date": weather["date"].max().date().isoformat(),
                "days": len(weather),
                "missing_average_temperature": int(weather["tavg_c"].isna().sum()),
                "missing_precipitation": int(weather["precip_mm"].isna().sum()),
            }
        ]
    )
    return {
        "weather_temperature_association": association,
        "weather_temperature_bins": pd.DataFrame(bin_rows),
        "weather_coverage": coverage,
    }


def matched_event_comparison(
    daily: pd.DataFrame,
    events: pd.DataFrame,
    date_column: str,
    category_column: str,
    universe_name: str,
    comparison_start: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_frame = daily.copy()
    daily_frame["date"] = pd.to_datetime(daily_frame["date"])
    if comparison_start is not None:
        daily_frame = daily_frame[daily_frame["date"].ge(pd.Timestamp(comparison_start))]
    lookup = daily_frame.set_index("date")["incidents"]
    event_frame = events.copy()
    event_frame[date_column] = pd.to_datetime(event_frame[date_column], errors="raise")
    if comparison_start is not None:
        event_frame = event_frame[event_frame[date_column].ge(pd.Timestamp(comparison_start))]
    event_dates = set(event_frame[date_column])
    rows: list[dict[str, object]] = []
    for event_date, group in event_frame.groupby(date_column):
        if event_date not in lookup.index:
            continue
        categories = sorted(set(group[category_column].dropna().astype(str)))
        candidate_dates = [
            event_date + pd.Timedelta(days=offset)
            for offset in (-28, -21, -14, -7, 7, 14, 21, 28)
        ]
        controls = [
            day for day in candidate_dates
            if day in lookup.index and day.year == event_date.year and day not in event_dates
        ]
        if not controls:
            continue
        rows.append(
            {
                "universe": universe_name,
                "event_date": event_date.date().isoformat(),
                "categories": "; ".join(categories),
                "event_records": len(group),
                "event_incidents": int(lookup.loc[event_date]),
                "control_days": len(controls),
                "control_mean_incidents": float(lookup.loc[controls].mean()),
                "paired_difference": float(lookup.loc[event_date] - lookup.loc[controls].mean()),
            }
        )
    details = pd.DataFrame(rows)
    if details.empty:
        raise ValueError(f"No matched event-day comparisons could be constructed for {universe_name}.")

    category_values = sorted(set(event_frame[category_column].dropna().astype(str)))
    groups = [("All included dates", details)]
    for category in category_values:
        groups.append((category, details[details["categories"].str.split("; ").apply(lambda x: category in x)]))
    rng = np.random.default_rng(CONTEXT_SEED)
    summary_rows: list[dict[str, object]] = []
    for category, subset in groups:
        if subset.empty:
            continue
        event_rate = float(subset["event_incidents"].mean())
        control_rate = float(subset["control_mean_incidents"].mean())
        bootstrap_difference = np.empty(2_000)
        bootstrap_ratio = np.empty(2_000)
        for index in range(len(bootstrap_difference)):
            sample = subset.iloc[rng.integers(0, len(subset), len(subset))]
            sampled_event = float(sample["event_incidents"].mean())
            sampled_control = float(sample["control_mean_incidents"].mean())
            bootstrap_difference[index] = sampled_event - sampled_control
            bootstrap_ratio[index] = sampled_event / sampled_control if sampled_control > 0 else np.nan
        summary_rows.append(
            {
                "universe": universe_name,
                "category": category,
                "matched_event_days": len(subset),
                "event_incidents_per_day": event_rate,
                "matched_control_incidents_per_day": control_rate,
                "paired_difference": event_rate - control_rate,
                "difference_lower_95": float(np.nanpercentile(bootstrap_difference, 2.5)),
                "difference_upper_95": float(np.nanpercentile(bootstrap_difference, 97.5)),
                "event_to_control_ratio": event_rate / control_rate if control_rate > 0 else math.nan,
                "ratio_lower_95": float(np.nanpercentile(bootstrap_ratio, 2.5)),
                "ratio_upper_95": float(np.nanpercentile(bootstrap_ratio, 97.5)),
                "bootstrap_replicates": len(bootstrap_difference),
                "seed": CONTEXT_SEED,
            }
        )
    return details, pd.DataFrame(summary_rows)


def adjusted_event_day_association(
    daily: pd.DataFrame, event_dates: Iterable[pd.Timestamp], start_date: str, label: str
) -> pd.DataFrame:
    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame[frame["date"].ge(pd.Timestamp(start_date))].copy()
    dates = {pd.Timestamp(value) for value in event_dates}
    frame["event_day"] = frame["date"].isin(dates).astype(float)
    frame["year"] = frame["date"].dt.year
    frame["month"] = frame["date"].dt.month
    frame["weekday"] = frame["date"].dt.dayofweek
    design = pd.concat(
        [
            pd.Series(1.0, index=frame.index, name="intercept"),
            _design_dummies(frame["year"], "year"),
            _design_dummies(frame["month"], "month"),
            _design_dummies(frame["weekday"], "weekday"),
            frame[["event_day"]],
        ],
        axis=1,
    )
    beta, covariance, _ = _poisson_fit(design.to_numpy(), frame["incidents"].to_numpy(dtype=float))
    index = list(design.columns).index("event_day")
    coefficient = float(beta[index])
    standard_error = float(np.sqrt(max(covariance[index, index], 0)))
    return pd.DataFrame(
        [
            {
                "universe": label,
                "start_date": frame["date"].min().date().isoformat(),
                "end_date": frame["date"].max().date().isoformat(),
                "calendar_days": len(frame),
                "event_days": int(frame["event_day"].sum()),
                "non_event_days": int((1 - frame["event_day"]).sum()),
                "incidence_rate_ratio": math.exp(coefficient),
                "lower_95": math.exp(coefficient - 1.96 * standard_error),
                "upper_95": math.exp(coefficient + 1.96 * standard_error),
                "coefficient_log_rate": coefficient,
                "robust_standard_error": standard_error,
                "model": "Poisson log-link with year, month, and weekday fixed effects; 14-day HAC uncertainty",
            }
        ]
    )


def event_context(daily: pd.DataFrame) -> dict[str, pd.DataFrame]:
    holidays = pd.read_csv(CONTEXTUAL / "us_federal_holidays_2006_2025.csv")
    holiday_details, holiday_summary = matched_event_comparison(
        daily, holidays, "actual_date", "holiday_name", "Federal holiday actual dates"
    )

    sports = pd.read_csv(CONTEXTUAL / "championship_games_2006_2025.csv")
    sports_details, sports_summary = matched_event_comparison(
        daily, sports, "event_date", "series", "Championship game dates"
    )

    protests = pd.read_csv(CONTEXTUAL / "nyc_political_crowds_2017_2025.csv", low_memory=False)
    protest_days = protests.groupby("event_date", as_index=False).agg(
        event_records=("event_type", "size"),
        event_type=("event_type", lambda values: "Political crowd day"),
        reported_attendance_low=("estimate_low", "sum"),
    )
    protest_details, protest_summary = matched_event_comparison(
        daily,
        protest_days,
        "event_date",
        "event_type",
        "CCC-recorded NYC political crowd days",
        comparison_start="2017-01-01",
    )
    protest_adjusted = adjusted_event_day_association(
        daily,
        pd.to_datetime(protest_days["event_date"]),
        "2017-01-01",
        "CCC-recorded NYC political crowd days",
    )
    protest_dates = pd.to_datetime(protests["event_date"])
    protest_yearly_records = protests.assign(year=protest_dates.dt.year).groupby("year").size()
    protest_yearly_days = protest_days.assign(
        year=pd.to_datetime(protest_days["event_date"]).dt.year
    ).groupby("year").size()
    protest_coverage_by_year = pd.DataFrame({"year": range(2017, 2026)})
    protest_coverage_by_year["event_records"] = protest_coverage_by_year["year"].map(
        protest_yearly_records
    ).fillna(0).astype(int)
    protest_coverage_by_year["event_days"] = protest_coverage_by_year["year"].map(
        protest_yearly_days
    ).fillna(0).astype(int)
    protest_coverage_by_year["calendar_days"] = protest_coverage_by_year["year"].map(
        lambda year: len(pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D"))
    )
    protest_coverage_by_year["non_event_days"] = (
        protest_coverage_by_year["calendar_days"] - protest_coverage_by_year["event_days"]
    )
    protest_coverage_by_year["event_day_share"] = (
        protest_coverage_by_year["event_days"] / protest_coverage_by_year["calendar_days"]
    )
    coverage = pd.DataFrame(
        [
            {
                "dataset": "federal_holidays",
                "start_date": holidays["actual_date"].min(),
                "end_date": holidays["actual_date"].max(),
                "records": len(holidays),
                "distinct_days": holidays["actual_date"].nunique(),
            },
            {
                "dataset": "championship_games",
                "start_date": sports["event_date"].min(),
                "end_date": sports["event_date"].max(),
                "records": len(sports),
                "distinct_days": sports["event_date"].nunique(),
            },
            {
                "dataset": "political_crowds",
                "start_date": protests["event_date"].min(),
                "end_date": protests["event_date"].max(),
                "records": len(protests),
                "distinct_days": protests["event_date"].nunique(),
            },
        ]
    )
    return {
        "holiday_match_details": holiday_details,
        "holiday_match_summary": holiday_summary,
        "sports_match_details": sports_details,
        "sports_match_summary": sports_summary,
        "protest_match_details": protest_details,
        "protest_match_summary": protest_summary,
        "protest_adjusted_association": protest_adjusted,
        "protest_coverage_by_year": protest_coverage_by_year,
        "contextual_event_coverage": coverage,
    }


def demographic_tables(data: CleanData) -> tuple[pd.DataFrame, pd.DataFrame]:
    definitions = (
        ("victim", data.victims, "VICTIM_AGE_GROUP", "age_group"),
        ("victim", data.victims, "VICTIM_SEX", "recorded_sex"),
        ("victim", data.victims, "VICTIM_RACE", "recorded_race"),
        ("offender", data.offenders, "PERP_AGE_GROUP", "age_group"),
        ("offender", data.offenders, "PERP_SEX", "recorded_sex"),
        ("offender", data.offenders, "PERP_RACE", "recorded_race"),
    )
    distribution_rows: list[dict[str, object]] = []
    quality_rows: list[dict[str, object]] = []
    for entity, frame, source_column, field in definitions:
        values = frame[source_column].astype("string").fillna("").str.strip().str.upper()
        missing_unknown = values.isin(UNKNOWN_TOKENS)
        invalid = pd.Series(False, index=frame.index)
        if field == "age_group":
            invalid = ~(values.isin(VALID_AGE_GROUPS) | missing_unknown)
        statuses = np.select(
            [missing_unknown, invalid], ["missing_or_unknown", "invalid_recorded_value"], default="recorded"
        )
        normalized = values.mask(values.eq(""), "<MISSING>")
        temp = pd.DataFrame({"value": normalized, "status": statuses})
        counts = temp.groupby(["status", "value"]).size().rename("count").reset_index()
        counts["share_of_all_records"] = counts["count"] / len(frame)
        counts.insert(0, "field", field)
        counts.insert(0, "entity", entity)
        distribution_rows.extend(counts.to_dict("records"))
        quality_rows.append(
            {
                "entity": entity,
                "field": field,
                "total_records": len(frame),
                "missing_or_unknown_count": int(missing_unknown.sum()),
                "missing_or_unknown_share": float(missing_unknown.mean()),
                "invalid_recorded_value_count": int(invalid.sum()),
                "invalid_recorded_value_share": float(invalid.mean()),
            }
        )
    return pd.DataFrame(distribution_rows), pd.DataFrame(quality_rows)


def categorical_distribution(
    frame: pd.DataFrame, definitions: Iterable[tuple[str, str]]
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for source_column, field in definitions:
        values = frame[source_column].astype("string").fillna("").str.strip().str.upper()
        missing = values.isin(UNKNOWN_TOKENS)
        invalid = ~values.isin(VALID_AGE_GROUPS | UNKNOWN_TOKENS) if field == "age_group" else pd.Series(False, index=frame.index)
        display = values.mask(missing, "Unknown or missing")
        statuses = np.select(
            [missing, invalid], ["missing_or_unknown", "invalid_recorded_value"], default="recorded"
        )
        counts = pd.DataFrame({"value": display, "status": statuses}).value_counts().rename("count").reset_index()
        for item in counts.itertuples(index=False):
            rows.append(
                {
                    "field": field,
                    "value": item.value,
                    "status": item.status,
                    "count": int(item.count),
                    "share_of_records": float(item.count / len(frame)) if len(frame) else math.nan,
                }
            )
    return pd.DataFrame(rows)


def location_tables(data: CleanData, complete_year: int) -> dict[str, pd.DataFrame]:
    incidents = data.shootings[data.shootings["occur_date"].dt.year <= complete_year].copy()
    population = pd.read_csv(EXTERNAL / "population" / "borough_population_2020.csv")
    total = incidents.groupby("BORO").size().rename("incidents_2006_to_complete_year")
    in_2020 = incidents[incidents["occur_date"].dt.year == 2020].groupby("BORO").size().rename("incidents_2020")
    borough = population.merge(total, left_on="borough", right_index=True, how="left")
    borough = borough.merge(in_2020, left_on="borough", right_index=True, how="left")
    borough[["incidents_2006_to_complete_year", "incidents_2020"]] = borough[
        ["incidents_2006_to_complete_year", "incidents_2020"]
    ].fillna(0).astype(int)
    borough["incidents_per_100k_2020"] = borough["incidents_2020"] / borough["population_2020"] * 100_000

    coordinate = data.shootings.assign(year=data.shootings["occur_date"].dt.year).groupby(
        ["year", "coordinate_status"]
    ).size().rename("rows").reset_index()
    coordinate["share_within_year"] = coordinate["rows"] / coordinate.groupby("year")["rows"].transform("sum")

    descriptions = categorical_distribution(
        incidents,
        (
            ("LOC_OF_OCCUR_DESC", "inside_outside"),
            ("LOC_CLASSFCTN_DESC", "location_classification"),
            ("LOCATION_DESC", "detailed_location"),
        ),
    )

    fatal_keys = set(
        data.victims.loc[
            data.victims["STAT_MURDER_FLG"].astype("string").str.upper().eq("Y"), "INCIDENT_KEY"
        ]
    )
    points = incidents.dropna(subset=["latitude_clean", "longitude_clean"]).copy()
    points = points.assign(
        year=points["occur_date"].dt.year,
        fatal_incident=points["INCIDENT_KEY"].isin(fatal_keys),
    )[
        [
            "INCIDENT_KEY",
            "occur_date",
            "year",
            "BORO",
            "PRECINCT",
            "latitude_clean",
            "longitude_clean",
            "fatal_incident",
        ]
    ]

    precinct_population = pd.read_csv(EXTERNAL / "nyc-precincts" / "nyc_precinct_2020pop.txt")[
        ["precinct", "P1_001N"]
    ].rename(columns={"P1_001N": "population_2020"})
    incidents_2020 = incidents[incidents["occur_date"].dt.year.eq(2020)]
    precinct_counts = incidents_2020.groupby("PRECINCT").size().rename("incidents_2020")
    fatal_2020 = incidents_2020[incidents_2020["INCIDENT_KEY"].isin(fatal_keys)]
    precinct_fatal = fatal_2020.groupby("PRECINCT").size().rename("fatal_incidents_2020")
    precinct = precinct_population.merge(precinct_counts, left_on="precinct", right_index=True, how="left")
    precinct = precinct.merge(precinct_fatal, left_on="precinct", right_index=True, how="left")
    precinct[["incidents_2020", "fatal_incidents_2020"]] = precinct[
        ["incidents_2020", "fatal_incidents_2020"]
    ].fillna(0).astype(int)
    precinct["incidents_per_100k_2020"] = precinct["incidents_2020"] / precinct["population_2020"] * 100_000
    precinct["fatal_incidents_per_100k_2020"] = (
        precinct["fatal_incidents_2020"] / precinct["population_2020"] * 100_000
    )

    return {
        "borough_2020_rates": borough,
        "coordinate_quality_by_year": coordinate,
        "location_descriptions": descriptions,
        "spatial_points_complete": points,
        "precinct_2020_rates": precinct,
    }


def _ring_contains_point(ring: list[list[float]], x: float, y: float) -> bool:
    inside = False
    for index in range(len(ring)):
        x1, y1 = ring[index - 1][:2]
        x2, y2 = ring[index][:2]
        cross = (y1 > y) != (y2 > y)
        if cross and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def geometry_contains_point(geometry: dict[str, object], x: float, y: float) -> bool:
    coordinates = geometry["coordinates"]
    polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
    for polygon in polygons:
        if _ring_contains_point(polygon[0], x, y) and not any(
            _ring_contains_point(hole, x, y) for hole in polygon[1:]
        ):
            return True
    return False


def _geometry_bbox(geometry: dict[str, object]) -> tuple[float, float, float, float]:
    coordinates = geometry["coordinates"]
    polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
    points = [point for polygon in polygons for ring in polygon for point in ring]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def assign_points_to_tracts(points: pd.DataFrame, features: list[dict[str, object]]) -> pd.Series:
    indexed = [
        (feature["properties"]["GEOID"], _geometry_bbox(feature["geometry"]), feature["geometry"])
        for feature in features
    ]
    assignments: list[object] = []
    for row in points.itertuples(index=False):
        x = float(row.longitude_clean)
        y = float(row.latitude_clean)
        match = pd.NA
        for geoid, (xmin, ymin, xmax, ymax), geometry in indexed:
            if xmin <= x <= xmax and ymin <= y <= ymax and geometry_contains_point(geometry, x, y):
                match = geoid
                break
        assignments.append(match)
    return pd.Series(assignments, index=points.index, dtype="string")


def _spearman(x: pd.Series, y: pd.Series) -> float:
    return float(x.rank(method="average").corr(y.rank(method="average")))


def income_tables(data: CleanData) -> dict[str, pd.DataFrame]:
    spatial_dir = EXTERNAL / "census-tracts-2020"
    geometry = json.loads((spatial_dir / "nyc_census_tracts_2020.geojson").read_text(encoding="utf-8"))
    acs = pd.read_csv(spatial_dir / "nyc_tract_acs5_2020.csv", dtype={"geoid": "string"})
    incidents_2020 = data.shootings[data.shootings["occur_date"].dt.year.eq(2020)].copy()
    valid = incidents_2020.dropna(subset=["latitude_clean", "longitude_clean"]).copy()
    valid["geoid"] = assign_points_to_tracts(valid, geometry["features"])

    counts = valid.dropna(subset=["geoid"]).groupby("geoid").size().rename("incidents_2020")
    tract = acs.merge(counts, left_on="geoid", right_index=True, how="left")
    tract["incidents_2020"] = tract["incidents_2020"].fillna(0).astype(int)
    tract["eligible_for_income_analysis"] = (
        tract["population_acs5_2020"].gt(0) & tract["median_household_income_acs5_2020"].gt(0)
    )
    tract["incidents_per_100k_2020"] = np.where(
        tract["population_acs5_2020"].gt(0),
        tract["incidents_2020"] / tract["population_acs5_2020"] * 100_000,
        np.nan,
    )

    eligible = tract[tract["eligible_for_income_analysis"]].copy()
    eligible["income_quartile"] = pd.qcut(
        eligible["median_household_income_acs5_2020"], 4, labels=["Q1 lowest", "Q2", "Q3", "Q4 highest"]
    )
    quartile = eligible.groupby("income_quartile", observed=True).agg(
        tracts=("geoid", "size"),
        population_acs5_2020=("population_acs5_2020", "sum"),
        incidents_2020=("incidents_2020", "sum"),
        median_tract_income=("median_household_income_acs5_2020", "median"),
    ).reset_index()
    quartile["incidents_per_100k_2020"] = quartile["incidents_2020"] / quartile["population_acs5_2020"] * 100_000
    standard_error = np.sqrt(quartile["incidents_2020"]) / quartile["population_acs5_2020"] * 100_000
    quartile["rate_lower_95"] = np.maximum(0, quartile["incidents_per_100k_2020"] - 1.96 * standard_error)
    quartile["rate_upper_95"] = quartile["incidents_per_100k_2020"] + 1.96 * standard_error

    rho = _spearman(eligible["median_household_income_acs5_2020"], eligible["incidents_per_100k_2020"])
    rng = np.random.default_rng(SPATIAL_SEED)
    bootstrap = np.empty(2_000)
    for index in range(len(bootstrap)):
        sample = eligible.iloc[rng.integers(0, len(eligible), len(eligible))]
        bootstrap[index] = _spearman(
            sample["median_household_income_acs5_2020"], sample["incidents_per_100k_2020"]
        )
    association = pd.DataFrame(
        [
            {
                "method": "Spearman rank correlation across eligible Census tracts",
                "tracts": len(eligible),
                "rho": rho,
                "bootstrap_lower_95": float(np.nanpercentile(bootstrap, 2.5)),
                "bootstrap_upper_95": float(np.nanpercentile(bootstrap, 97.5)),
                "bootstrap_replicates": len(bootstrap),
                "seed": SPATIAL_SEED,
            }
        ]
    )
    audit = pd.DataFrame(
        [
            {"metric": "shooting_incidents_2020", "count": len(incidents_2020)},
            {"metric": "incidents_with_valid_coordinates", "count": len(valid)},
            {"metric": "incidents_assigned_to_2020_tract", "count": int(valid["geoid"].notna().sum())},
            {"metric": "incidents_unassigned_to_2020_tract", "count": int(valid["geoid"].isna().sum())},
            {"metric": "nyc_tracts_in_geometry", "count": len(geometry["features"])},
            {"metric": "tracts_eligible_for_income_analysis", "count": len(eligible)},
        ]
    )
    return {
        "income_tract_2020": tract,
        "income_quartile_2020": quartile,
        "income_association_2020": association,
        "spatial_assignment_audit": audit,
    }


def fatality_tables(data: CleanData, complete_year: int) -> dict[str, pd.DataFrame]:
    victims = data.victims[
        data.victims["occur_date"].dt.year.le(complete_year)
        & data.victims["STAT_MURDER_FLG"].astype("string").str.upper().eq("Y")
    ].copy()
    fatal_keys = set(victims["INCIDENT_KEY"])
    incidents = data.shootings[
        data.shootings["occur_date"].dt.year.le(complete_year)
        & data.shootings["INCIDENT_KEY"].isin(fatal_keys)
    ].copy()
    offenders = data.offenders[
        data.offenders["occur_date"].dt.year.le(complete_year)
        & data.offenders["INCIDENT_KEY"].isin(fatal_keys)
    ].drop_duplicates("PERP_ID").copy()

    incident_month = incidents.assign(month=incidents["occur_date"].dt.month).groupby("month").size().rename("fatal_incidents").reset_index()
    incident_month["month_name"] = pd.to_datetime(incident_month["month"], format="%m").dt.month_name()
    incident_weekday = incidents.assign(
        weekday_number=incidents["occur_date"].dt.dayofweek,
        weekday=incidents["occur_date"].dt.day_name(),
    ).groupby(["weekday_number", "weekday"]).size().rename("fatal_incidents").reset_index()
    incident_hour = incidents.dropna(subset=["occur_hour"]).groupby("occur_hour").size().reindex(range(24), fill_value=0).rename("fatal_incidents").reset_index()
    for frame in (incident_month, incident_weekday, incident_hour):
        frame["share_of_fatal_incidents"] = frame["fatal_incidents"] / len(incidents)

    borough = incidents.assign(BORO=incidents["BORO"].astype("string").fillna("Unknown or missing")).groupby("BORO").size().rename("fatal_incidents").reset_index()
    borough["share_of_fatal_incidents"] = borough["fatal_incidents"] / len(incidents)
    precinct = incidents.groupby("PRECINCT").size().rename("fatal_incidents").reset_index()
    precinct["share_of_fatal_incidents"] = precinct["fatal_incidents"] / len(incidents)
    locations = categorical_distribution(
        incidents,
        (("LOC_OF_OCCUR_DESC", "inside_outside"), ("LOC_CLASSFCTN_DESC", "location_classification"), ("LOCATION_DESC", "detailed_location")),
    )

    linked_incident_count = offenders["INCIDENT_KEY"].nunique()
    coverage = pd.DataFrame(
        [
            {"metric": "fatal_victim_records", "count": len(victims)},
            {"metric": "fatal_incidents", "count": len(incidents)},
            {"metric": "fatal_incidents_with_linked_known_offender", "count": linked_incident_count},
            {"metric": "fatal_incidents_without_linked_known_offender", "count": len(incidents) - linked_incident_count},
            {"metric": "distinct_linked_known_offender_records", "count": len(offenders)},
        ]
    )
    demographic_rows: list[pd.DataFrame] = []
    for entity, frame, definitions in (
        ("fatal_victim", victims, (("VICTIM_AGE_GROUP", "age_group"), ("VICTIM_SEX", "recorded_sex"), ("VICTIM_RACE", "recorded_race"))),
        ("linked_known_offender", offenders, (("PERP_AGE_GROUP", "age_group"), ("PERP_SEX", "recorded_sex"), ("PERP_RACE", "recorded_race"))),
    ):
        distribution = categorical_distribution(frame, definitions)
        distribution.insert(0, "entity", entity)
        demographic_rows.append(distribution)

    return {
        "fatal_temporal_month": incident_month,
        "fatal_temporal_weekday": incident_weekday,
        "fatal_temporal_hour": incident_hour,
        "fatal_borough": borough,
        "fatal_precinct": precinct,
        "fatal_location_descriptions": locations,
        "fatal_offender_coverage": coverage,
        "fatal_demographic_distributions": pd.concat(demographic_rows, ignore_index=True),
    }


def make_poisson_features(dates: Iterable[pd.Timestamp], reference: pd.Timestamp) -> np.ndarray:
    index = pd.DatetimeIndex(dates)
    trend = (index - reference).days.to_numpy(dtype=float) / 365.25
    columns: list[np.ndarray] = [np.ones(len(index)), trend]
    weekday = index.dayofweek.to_numpy()
    columns.extend((weekday == value).astype(float) for value in range(1, 7))
    day_number = (index.dayofyear.to_numpy(dtype=float) - 1) / 365.25
    for harmonic in range(1, 4):
        columns.append(np.sin(2 * np.pi * harmonic * day_number))
        columns.append(np.cos(2 * np.pi * harmonic * day_number))
    return np.column_stack(columns)


def poisson_calendar_predict(train: pd.Series, future_dates: pd.DatetimeIndex) -> np.ndarray:
    training = train.iloc[-8 * 366 :]
    reference = training.index.min()
    x = make_poisson_features(training.index, reference)
    y = training.to_numpy(dtype=float)
    beta = np.zeros(x.shape[1])
    beta[0] = math.log(max(y.mean(), 1e-6))
    penalty = np.eye(x.shape[1]) * 0.1
    penalty[0, 0] = 0
    for _ in range(60):
        eta = np.clip(x @ beta, -8, 8)
        mu = np.exp(eta)
        z = eta + (y - mu) / np.maximum(mu, 1e-8)
        weight = np.sqrt(mu)
        lhs = (x * weight[:, None]).T @ (x * weight[:, None]) + penalty
        rhs = (x * weight[:, None]).T @ (z * weight)
        updated = np.linalg.solve(lhs, rhs)
        if np.max(np.abs(updated - beta)) < 1e-8:
            beta = updated
            break
        beta = updated
    prediction = np.exp(np.clip(make_poisson_features(future_dates, reference) @ beta, -8, 8))
    return prediction


def make_autoregressive_feature(history: list[float], date: pd.Timestamp) -> np.ndarray:
    values = np.asarray(history, dtype=float)
    day_number = (date.dayofyear - 1) / 365.25
    return np.asarray(
        [
            values[-1],
            values[-7],
            values[-14],
            values[-7:].mean(),
            values[-28:].mean(),
            values[-56:].mean(),
            *[float(date.dayofweek == value) for value in range(1, 7)],
            math.sin(2 * math.pi * day_number),
            math.cos(2 * math.pi * day_number),
            math.sin(4 * math.pi * day_number),
            math.cos(4 * math.pi * day_number),
        ],
        dtype=float,
    )


def autoregressive_log_ridge_predict(
    train: pd.Series,
    future_dates: pd.DatetimeIndex,
    penalty_strength: float = DYNAMIC_AR_PENALTY,
) -> np.ndarray:
    """Recursive regularised count forecast using only information at the origin."""
    training = train.iloc[-5 * 366 :]
    values = training.to_numpy(dtype=float)
    start = 56
    features = np.vstack(
        [
            make_autoregressive_feature(values[:index].tolist(), training.index[index])
            for index in range(start, len(values))
        ]
    )
    target = np.log1p(values[start:])
    feature_mean = features.mean(axis=0)
    feature_scale = features.std(axis=0)
    feature_scale[feature_scale == 0] = 1
    standardised = (features - feature_mean) / feature_scale
    design = np.column_stack([np.ones(len(standardised)), standardised])
    penalty = np.eye(design.shape[1]) * penalty_strength
    penalty[0, 0] = 0
    beta = np.linalg.solve(design.T @ design + penalty, design.T @ target)

    history = values.tolist()
    predictions: list[float] = []
    for date in future_dates:
        feature = (make_autoregressive_feature(history, date) - feature_mean) / feature_scale
        prediction = max(0.0, float(np.expm1(np.r_[1.0, feature] @ beta)))
        predictions.append(prediction)
        history.append(prediction)
    return np.asarray(predictions)


def local_weekday_predict(train: pd.Series, future_dates: pd.DatetimeIndex) -> np.ndarray:
    """Recent local level plus a deliberately shrunk weekday adjustment."""
    local_level = float(train.iloc[-DYNAMIC_LOCAL_WINDOW_DAYS:].mean())
    trailing_year = train.iloc[-365:]
    weekday_effect = (
        trailing_year.groupby(trailing_year.index.dayofweek).mean() - trailing_year.mean()
    )
    return np.clip(
        np.asarray(
            [
                local_level
                + DYNAMIC_WEEKDAY_SHRINKAGE * weekday_effect.get(date.dayofweek, 0.0)
                for date in future_dates
            ],
            dtype=float,
        ),
        0,
        None,
    )


def negative_binomial_interval(
    train: pd.Series,
    mean_prediction: np.ndarray,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Method-of-moments overdispersion and deterministic 80% predictive intervals."""
    trailing = train.iloc[-3 * 365 :]
    weekday_mean = trailing.groupby(trailing.index.dayofweek).mean()
    fitted = np.asarray(
        [weekday_mean.get(date.dayofweek, trailing.mean()) for date in trailing.index],
        dtype=float,
    )
    observed = trailing.to_numpy(dtype=float)
    numerator = float(np.sum(np.square(observed - fitted) - fitted))
    denominator = float(np.sum(np.square(fitted)))
    dispersion = max(numerator / max(denominator, 1e-8), 0.01)
    size = 1.0 / dispersion
    probability = size / (size + np.maximum(mean_prediction, 1e-8))
    rng = np.random.default_rng(seed)
    draws = rng.negative_binomial(size, probability, size=(20_000, len(mean_prediction)))
    lower = np.quantile(draws, 0.10, axis=0)
    upper = np.quantile(draws, 0.90, axis=0)
    return lower, upper, dispersion


def dynamic_count_ensemble_prediction(
    train: pd.Series,
    future_dates: pd.DatetimeIndex,
    autoregressive_prediction: np.ndarray | None = None,
) -> dict[str, np.ndarray | float]:
    """Primary 14/28-day model: adaptive level, calendar structure, count intervals."""
    autoregressive = (
        autoregressive_prediction
        if autoregressive_prediction is not None
        else autoregressive_log_ridge_predict(train, future_dates)
    )
    local = local_weekday_predict(train, future_dates)
    prediction = DYNAMIC_LOCAL_WEIGHT * local + DYNAMIC_AR_WEIGHT * autoregressive
    seed = FORECAST_SEED + int(pd.Timestamp(train.index.max()).toordinal())
    lower, upper, dispersion = negative_binomial_interval(train, prediction, seed)
    return {
        "prediction": prediction,
        "lower": lower,
        "upper": upper,
        "dispersion": dispersion,
    }


def forecast_model_specification() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"setting": "primary_model", "value": PRIMARY_FORECAST_MODEL},
            {"setting": "development_origins", "value": "2018-2021; March, June, September month-end"},
            {"setting": "evaluation_origins", "value": "2022-2025; March, June, September month-end"},
            {"setting": "forecast_horizons_days", "value": "14, 28"},
            {"setting": "local_level_window_days", "value": str(DYNAMIC_LOCAL_WINDOW_DAYS)},
            {"setting": "weekday_effect_shrinkage", "value": str(DYNAMIC_WEEKDAY_SHRINKAGE)},
            {"setting": "autoregressive_training_years", "value": "5"},
            {"setting": "autoregressive_lags_days", "value": "1, 7, 14"},
            {"setting": "autoregressive_penalty", "value": str(DYNAMIC_AR_PENALTY)},
            {"setting": "local_component_weight", "value": str(DYNAMIC_LOCAL_WEIGHT)},
            {"setting": "autoregressive_component_weight", "value": str(DYNAMIC_AR_WEIGHT)},
            {"setting": "predictive_distribution", "value": "negative binomial; 80% interval"},
        ]
    )


def baseline_predictions(train: pd.Series, future_dates: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    last_28_mean = float(train.iloc[-28:].mean())
    seasonal_week = np.resize(train.iloc[-7:].to_numpy(dtype=float), len(future_dates))
    trailing = train.iloc[-365:].to_frame("incidents")
    trailing["weekday"] = trailing.index.dayofweek
    weekday_means = trailing.groupby("weekday")["incidents"].mean()
    day_of_week = np.array([weekday_means.get(day.dayofweek, trailing["incidents"].mean()) for day in future_dates])
    return {
        "rolling_mean_28": np.repeat(last_28_mean, len(future_dates)),
        "seasonal_naive_7": seasonal_week,
        "day_of_week_mean_365": day_of_week,
        "poisson_calendar": poisson_calendar_predict(train, future_dates),
    }


def prophet_prediction(train: pd.Series, future_dates: pd.DatetimeIndex) -> dict[str, np.ndarray] | None:
    try:
        from prophet import Prophet
    except ImportError:
        return None
    model = Prophet(
        growth="linear",
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=True,
        seasonality_mode="additive",
        changepoint_prior_scale=0.05,
        interval_width=0.8,
        uncertainty_samples=200,
    )
    model.add_country_holidays(country_name="US")
    training = train.rename_axis("ds").rename("y").reset_index()
    np.random.seed(FORECAST_SEED)
    model.fit(training, seed=FORECAST_SEED)
    np.random.seed(FORECAST_SEED)
    forecast = model.predict(pd.DataFrame({"ds": future_dates}))
    return {
        "prediction": np.clip(forecast["yhat"].to_numpy(dtype=float), 0, None),
        "lower": np.clip(forecast["yhat_lower"].to_numpy(dtype=float), 0, None),
        "upper": np.clip(forecast["yhat_upper"].to_numpy(dtype=float), 0, None),
    }


def forecast_evaluation(daily: pd.DataFrame, complete_year: int, include_prophet: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    series = daily.set_index("date")["incidents"].astype(float)
    origins = [
        pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
        for year in range(max(2022, complete_year - 3), complete_year + 1)
        for month in (3, 6, 9)
    ]
    prediction_rows: list[dict[str, object]] = []
    for origin in origins:
        train = series.loc[:origin]
        future_dates = pd.date_range(origin + pd.Timedelta(days=1), periods=28, freq="D")
        actual = series.reindex(future_dates).to_numpy(dtype=float)
        models = baseline_predictions(train, future_dates)
        intervals: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        autoregressive = autoregressive_log_ridge_predict(train, future_dates)
        models["autoregressive_log_ridge"] = autoregressive
        dynamic = dynamic_count_ensemble_prediction(train, future_dates, autoregressive)
        models[PRIMARY_FORECAST_MODEL] = np.asarray(dynamic["prediction"])
        intervals[PRIMARY_FORECAST_MODEL] = (
            np.asarray(dynamic["lower"]),
            np.asarray(dynamic["upper"]),
        )
        if include_prophet:
            prophet = prophet_prediction(train, future_dates)
            if prophet is not None:
                models["prophet"] = prophet["prediction"]
                intervals["prophet"] = (prophet["lower"], prophet["upper"])
        for model_name, prediction in models.items():
            lower, upper = intervals.get(model_name, (np.full(28, np.nan), np.full(28, np.nan)))
            for step, (date, observed, estimate, low, high) in enumerate(
                zip(future_dates, actual, prediction, lower, upper), start=1
            ):
                prediction_rows.append(
                    {
                        "origin": origin.date().isoformat(),
                        "date": date.date().isoformat(),
                        "step": step,
                        "model": model_name,
                        "actual": observed,
                        "prediction": estimate,
                        "lower_80": low,
                        "upper_80": high,
                    }
                )

    predictions = pd.DataFrame(prediction_rows)
    metric_rows: list[dict[str, object]] = []
    for (origin, model), group in predictions.groupby(["origin", "model"]):
        for horizon in (14, 28):
            subset = group[group["step"] <= horizon]
            error = subset["prediction"] - subset["actual"]
            coverage = math.nan
            if subset["lower_80"].notna().all():
                coverage = float(
                    ((subset["actual"] >= subset["lower_80"]) & (subset["actual"] <= subset["upper_80"])).mean()
                )
            metric_rows.append(
                {
                    "origin": origin,
                    "model": model,
                    "horizon_days": horizon,
                    "mae": float(error.abs().mean()),
                    "rmse": float(np.sqrt(np.square(error).mean())),
                    "mean_error": float(error.mean()),
                    "interval_80_coverage": coverage,
                }
            )
    by_origin = pd.DataFrame(metric_rows)
    summary = by_origin.groupby(["model", "horizon_days"], as_index=False).agg(
        origins=("origin", "nunique"),
        mae=("mae", "mean"),
        rmse=("rmse", "mean"),
        mean_error=("mean_error", "mean"),
        interval_80_coverage=("interval_80_coverage", "mean"),
    )
    naive_names = {"rolling_mean_28", "seasonal_naive_7", "day_of_week_mean_365"}
    summary["best_naive_mae"] = summary["horizon_days"].map(
        summary[summary["model"].isin(naive_names)].groupby("horizon_days")["mae"].min()
    )
    summary["mae_lift_vs_best_naive_pct"] = (
        (summary["best_naive_mae"] - summary["mae"]) / summary["best_naive_mae"] * 100
    )
    prophet_mae = summary[summary["model"].eq("prophet")].set_index("horizon_days")["mae"]
    summary["mae_lift_vs_prophet_pct"] = summary.apply(
        lambda row: (
            (prophet_mae.get(row["horizon_days"], math.nan) - row["mae"])
            / prophet_mae.get(row["horizon_days"], math.nan)
            * 100
        ),
        axis=1,
    )
    summary["mae_rank"] = summary.groupby("horizon_days")["mae"].rank(method="min")

    primary_rows = summary[summary["model"].eq(PRIMARY_FORECAST_MODEL)]
    prophet_rows = summary[summary["model"].eq("prophet")]
    if include_prophet and len(prophet_rows) == 2 and len(primary_rows) == 2:
        if (primary_rows["mae_lift_vs_best_naive_pct"] > 0).all() and (
            primary_rows["mae_lift_vs_prophet_pct"] > 0
        ).all():
            verdict = "dynamic_count_ensemble_preferred"
        else:
            verdict = "no_consistent_model_lift"
    elif include_prophet:
        verdict = "prophet_unavailable"
    else:
        verdict = "dynamic_count_ensemble_evaluated_without_prophet"
    return predictions, by_origin, summary, verdict


def forecast_development_metrics(daily: pd.DataFrame) -> pd.DataFrame:
    """Preserve the pre-evaluation development check for the fixed primary design."""
    series = daily.set_index("date")["incidents"].astype(float)
    origins = [
        pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
        for year in range(2018, 2022)
        for month in (3, 6, 9)
    ]
    rows: list[dict[str, object]] = []
    for origin in origins:
        train = series.loc[:origin]
        future_dates = pd.date_range(origin + pd.Timedelta(days=1), periods=28, freq="D")
        actual = series.reindex(future_dates).to_numpy(dtype=float)
        autoregressive = autoregressive_log_ridge_predict(train, future_dates)
        dynamic = np.asarray(
            dynamic_count_ensemble_prediction(train, future_dates, autoregressive)["prediction"]
        )
        models = {
            PRIMARY_FORECAST_MODEL: dynamic,
            "rolling_mean_28": np.repeat(float(train.iloc[-28:].mean()), 28),
        }
        for model, prediction in models.items():
            for horizon in (14, 28):
                error = prediction[:horizon] - actual[:horizon]
                rows.append(
                    {
                        "origin": origin.date().isoformat(),
                        "model": model,
                        "horizon_days": horizon,
                        "mae": float(np.abs(error).mean()),
                        "rmse": float(np.sqrt(np.square(error).mean())),
                        "mean_error": float(error.mean()),
                    }
                )
    return pd.DataFrame(rows)


def write_findings(
    data: CleanData,
    annual: pd.DataFrame,
    periods: pd.DataFrame,
    changepoints: pd.DataFrame,
    demographic_quality: pd.DataFrame,
    forecast_summary: pd.DataFrame,
    forecast_verdict: str,
    ytd: pd.DataFrame,
    income: dict[str, pd.DataFrame],
    fatality: dict[str, pd.DataFrame],
    contextual: dict[str, pd.DataFrame],
) -> None:
    complete_year = int(data.audit["current_snapshot"]["latest_complete_year"])
    current_2020 = int(annual.loc[annual["year"].eq(2020), "incidents"].iloc[0])
    current_2019 = int(annual.loc[annual["year"].eq(2019), "incidents"].iloc[0])
    current_last = int(annual.loc[annual["year"].eq(complete_year), "incidents"].iloc[0])
    current_2023 = int(annual.loc[annual["year"].eq(2023), "incidents"].iloc[0])
    best_break = changepoints.iloc[0]
    current_ytd = ytd.iloc[-1]
    prior_ytd = ytd.iloc[-2]
    income_result = income["income_association_2020"].iloc[0]
    income_quartiles = income["income_quartile_2020"].set_index("income_quartile")
    fatal_coverage = fatality["fatal_offender_coverage"].set_index("metric")["count"]
    season_peak = contextual["seasonal_summary"].sort_values("incidents_per_calendar_day").iloc[-1]
    temperature_result = contextual["weather_temperature_association"].iloc[0]
    holiday_result = contextual["holiday_match_summary"].query("category == 'All included dates'").iloc[0]
    sports_result = contextual["sports_match_summary"].query("category == 'All included dates'").iloc[0]
    protest_result = contextual["protest_adjusted_association"].iloc[0]
    protest_matched = contextual["protest_match_summary"].query("category == 'All included dates'").iloc[0]
    best_models = forecast_summary.sort_values(["horizon_days", "mae"]).groupby("horizon_days").first().reset_index()
    quality_lines = []
    for row in demographic_quality.itertuples(index=False):
        quality_lines.append(
            f"- {row.entity} {row.field}: {row.missing_or_unknown_count:,} missing/unknown "
            f"({row.missing_or_unknown_share:.1%}); {row.invalid_recorded_value_count:,} invalid recorded "
            f"values ({row.invalid_recorded_value_share:.2%})."
        )
    forecast_lines = []
    for row in best_models.itertuples(index=False):
        forecast_lines.append(
            f"- {row.horizon_days}-day horizon: `{row.model}` had the lowest mean MAE ({row.mae:.3f} incidents/day)."
        )
    prophet_lines = []
    for row in forecast_summary[forecast_summary["model"].eq("prophet")].sort_values("horizon_days").itertuples(index=False):
        relative = row.mae_lift_vs_best_naive_pct
        direction = "better" if relative > 0 else "worse"
        prophet_lines.append(
            f"- {row.horizon_days}-day Prophet MAE was {row.mae:.3f} incidents/day, "
            f"{abs(relative):.2f}% {direction} than the best naive model; its nominal 80% interval covered "
            f"{row.interval_80_coverage:.2%} of observations."
        )
    primary_lines = []
    for row in forecast_summary[
        forecast_summary["model"].eq(PRIMARY_FORECAST_MODEL)
    ].sort_values("horizon_days").itertuples(index=False):
        primary_lines.append(
            f"- {row.horizon_days}-day dynamic-count MAE was {row.mae:.3f} incidents/day, "
            f"{row.mae_lift_vs_best_naive_pct:.2f}% better than the best predeclared naive model and "
            f"{row.mae_lift_vs_prophet_pct:.2f}% better than Prophet; its nominal 80% negative-binomial "
            f"interval covered {row.interval_80_coverage:.2%} of observations."
        )

    manifest = json.loads((OFFICIAL / "manifest.json").read_text(encoding="utf-8"))
    snapshot_retrieved = manifest["retrieved_at_utc"]

    text = f"""# Repaired analysis findings

**Official snapshot retrieved:** {snapshot_retrieved}

**Official data boundary:** {data.audit['current_snapshot']['date_min']} through {data.audit['current_snapshot']['date_max']}

**Latest complete calendar year used for annual comparison:** {complete_year}

These are maintained analytical results, not finished publication prose. Descriptive patterns do not establish causes.

## Central correction: rows were not incidents

The legacy file contains {data.audit['legacy_snapshot']['rows']:,} rows but only {data.audit['legacy_snapshot']['unique_incident_keys']:,} unique incident keys. It repeats {data.audit['legacy_snapshot']['repeated_incident_rows']:,} rows across multi-victim incidents, with as many as {data.audit['legacy_snapshot']['maximum_rows_per_incident']} rows for one incident. The old report's annual row totals therefore measured victim records while labeling them shooting incidents.

The repaired analysis uses the current shootings table for incident counts, the victims table for victim counts, and the offenders table for known-offender records. These units are never interchanged.

## Refreshed trend

- Recorded incidents rose from {current_2019:,} in 2019 to {current_2020:,} in 2020 ({(current_2020-current_2019)/current_2019:.1%}). This is a discontinuity in the observed series, not a causal estimate.
- Incidents declined from {current_2023:,} in 2023 to {current_last:,} in {complete_year} ({(current_last-current_2023)/current_2023:.1%}).
- Through {data.audit['current_snapshot']['date_max'][5:]}, 2026 recorded {int(current_ytd.incidents):,} incidents versus {int(prior_ytd.incidents):,} over the equivalent 2025 window ({current_ytd.incident_change_from_prior_year_pct / 100:.1%}). The partial year is not mixed into full-year comparisons.
- `period_summary.csv` keeps context-defined eras separate from the exploratory segmented-linear sensitivity periods.
- An exploratory segmented-linear sensitivity check preferred segment starts at `{best_break.candidate_segment_start_years}` by BIC. This is a descriptive model-selection result; it does not identify historical causes or prove that the break dates were known in advance.

## Data-quality repairs

- The current shootings export contains {data.audit['shootings']['coordinate_status']['reversed_in_export']:,} rows whose published latitude and longitude values are reversed and {data.audit['shootings']['coordinate_status']['as_published']:,} rows already in the stated orientation. The repair uses per-row NYC range checks; it does not swap whole columns.
- Exact duplicate records removed: {data.audit['victims']['exact_duplicates_removed']:,} victim rows and {data.audit['offenders']['exact_duplicates_removed']:,} offender rows.
- Records lacking a matching current incident key remain visible in the audit: {data.audit['victims']['orphan_rows']:,} victim rows and {data.audit['offenders']['orphan_rows']:,} offender rows. They are excluded from date-based summaries because their occurrence date cannot be established from the current incident table.

## Demographic measurement

The offender table contains records for known suspects/offenders; it is not the denominator for all incidents or for any population-risk claim. Categories are recorded administrative fields rather than complete identities.

{chr(10).join(quality_lines)}

Full category counts—including unknown and invalid recorded values—are retained in `demographic_distributions.csv`.

## Place, income, and fatality findings

- The tract analysis assigns {int(income['spatial_assignment_audit'].set_index('metric').loc['incidents_assigned_to_2020_tract', 'count']):,} of {int(income['spatial_assignment_audit'].set_index('metric').loc['shooting_incidents_2020', 'count']):,} 2020 incidents to January 2020-vintage Census tracts.
- Across {int(income_result.tracts):,} tracts with positive population and a published positive median household income, the Spearman association between median household income and the 2020 incident rate was {income_result.rho:.3f} (tract bootstrap 95% interval {income_result.bootstrap_lower_95:.3f} to {income_result.bootstrap_upper_95:.3f}). This is an ecological association, not an individual-level or causal result.
- Income-quartile aggregate rates ranged from {income_quartiles.loc['Q4 highest', 'incidents_per_100k_2020']:.1f} per 100,000 in the highest-income tract quartile to {income_quartiles.loc['Q1 lowest', 'incidents_per_100k_2020']:.1f} in the lowest-income quartile.
- Complete years contain {int(fatal_coverage['fatal_incidents']):,} fatal incidents and {int(fatal_coverage['fatal_victim_records']):,} fatal victim records. {int(fatal_coverage['fatal_incidents_with_linked_known_offender']):,} fatal incidents have at least one linked known-offender record; {int(fatal_coverage['fatal_incidents_without_linked_known_offender']):,} do not.
- The linked known-offender demographic table is limited to {int(fatal_coverage['distinct_linked_known_offender_records']):,} distinct published records. It does not describe every fatal incident, conviction, or population group.

## Contextual associations

- {season_peak.season} had the highest complete-year rate at {season_peak.incidents_per_calendar_day:.2f} incidents per calendar day.
- In the daily Poisson model with year, month, and weekday fixed effects, a 5°C higher Central Park average temperature was associated with an incident-rate ratio of {temperature_result.incidence_rate_ratio:.3f} (14-day HAC 95% interval {temperature_result.lower_95:.3f} to {temperature_result.upper_95:.3f}). This is a within-calendar association, not a causal effect of temperature.
- Across {int(holiday_result.matched_event_days):,} federal holiday dates with same-weekday controls inside the same year, the mean difference was {holiday_result.paired_difference:.3f} incidents per day (bootstrap 95% interval {holiday_result.difference_lower_95:.3f} to {holiday_result.difference_upper_95:.3f}).
- Across {int(sports_result.matched_event_days):,} independently sourced championship-game dates, the mean difference from matched controls was {sports_result.paired_difference:.3f} incidents per day (bootstrap 95% interval {sports_result.difference_lower_95:.3f} to {sports_result.difference_upper_95:.3f}).
- The political-event comparison is restricted to the CCC coverage period. A calendar-adjusted model comparing {int(protest_result.event_days):,} recorded political-crowd days with {int(protest_result.non_event_days):,} non-event days estimated an incident-rate ratio of {protest_result.incidence_rate_ratio:.3f} (14-day HAC 95% interval {protest_result.lower_95:.3f} to {protest_result.upper_95:.3f}). A same-weekday matched sensitivity could pair {int(protest_matched.matched_event_days):,} event days. Reporting and event coverage are not random, so this remains an association with recorded event days.

## Forecast evaluation

Forecasts use rolling chronological origins, never random train/test splits. Model structure was selected on 2018-2021 development origins; the publication comparison uses twelve untouched 2022-2025 origins. Each origin predicts the following 28 days, with metrics at 14 and 28 days. Every fitted model sees only observations available at its origin.

The preferred model is the dynamic count ensemble: 75% recent 28-day local level with a shrunk weekday adjustment, plus 25% regularised recursive log-autoregression. Negative-binomial predictive intervals keep the output non-negative and allow variance to exceed the mean.

{chr(10).join(primary_lines)}

{chr(10).join(forecast_lines)}

{chr(10).join(prophet_lines)}

Forecast verdict: **`{forecast_verdict}`**. The dynamic count ensemble supersedes Prophet for this report because it had lower MAE at both horizons, preserved the count scale, and beat the strongest predeclared naive benchmark in the untouched evaluation window. Prophet remains as the original historical choice and a fully evaluated comparison.

## Publication boundaries

- Use complete years for annual comparisons. Treat 2026 only as year-to-date and compare it with equivalent year-to-date windows.
- The 2020 borough rate uses the official 2020 Census population denominator. Do not apply that fixed denominator to the full 2006-{complete_year} period.
- The tract-income result combines 2020 incidents, January 2020-vintage tract geometry, and 2020 ACS 5-year estimates. It remains subject to ACS uncertainty, small-area rate instability, ecological fallacy, and spatial dependence.
- Do not infer causes from time coincidence, demographics from incident-level joins, or offender characteristics for incidents without an offender record.
"""
    (RESULTS / "ANALYSIS_FINDINGS.md").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-prophet", action="store_true", help="Run deterministic baselines only.")
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)

    data = clean_data()
    complete_year = int(data.audit["current_snapshot"]["latest_complete_year"])
    annual = annual_counts(data)
    recon = reconciliation(data)
    periods = period_summary(annual, complete_year)
    ytd = ytd_comparison(data)
    changepoints = changepoint_sensitivity(annual)
    temporal = temporal_tables(data, complete_year)
    contextual = {
        **seasonal_context(temporal["daily_incidents"]),
        **weather_context(temporal["daily_incidents"]),
        **event_context(temporal["daily_incidents"]),
    }
    distributions, demographic_quality = demographic_tables(data)
    location = location_tables(data, complete_year)
    income = income_tables(data)
    fatality = fatality_tables(data, complete_year)
    predictions, metrics_by_origin, metrics_summary, verdict = forecast_evaluation(
        temporal["daily_incidents"], complete_year, include_prophet=not args.skip_prophet
    )
    development_metrics = forecast_development_metrics(temporal["daily_incidents"])

    data.audit["runtime"] = {
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "prophet_requested": not args.skip_prophet,
        "forecast_verdict": verdict,
    }
    contextual_manifest = json.loads((CONTEXTUAL / "manifest.json").read_text(encoding="utf-8"))
    data.audit["contextual_snapshot"] = {
        "retrieved_at_utc": contextual_manifest["retrieved_at_utc"],
        "analysis_boundary": contextual_manifest["analysis_boundary"],
        "files": contextual_manifest["files"],
    }
    (RESULTS / "data_audit.json").write_text(
        json.dumps(data.audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tables = {
        "annual_counts": annual,
        "legacy_reconciliation": recon,
        "period_summary": periods,
        "ytd_comparison": ytd,
        "changepoint_sensitivity": changepoints,
        "demographic_distributions": distributions,
        "demographic_quality": demographic_quality,
        "forecast_predictions": predictions,
        "forecast_metrics_by_origin": metrics_by_origin,
        "forecast_metrics_summary": metrics_summary,
        "forecast_development_metrics": development_metrics,
        "forecast_model_specification": forecast_model_specification(),
        **temporal,
        **contextual,
        **location,
        **income,
        **fatality,
    }
    for name, frame in tables.items():
        frame.to_csv(RESULTS / f"{name}.csv", index=False, lineterminator="\n")
    write_findings(
        data,
        annual,
        periods,
        changepoints,
        demographic_quality,
        metrics_summary,
        verdict,
        ytd,
        income,
        fatality,
        contextual,
    )
    print(f"Wrote {len(tables) + 2} maintained results to {RESULTS.relative_to(ROOT)}")
    print(f"Forecast verdict: {verdict}")


if __name__ == "__main__":
    main()
