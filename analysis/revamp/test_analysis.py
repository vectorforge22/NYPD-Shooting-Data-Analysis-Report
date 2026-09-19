"""Regression tests for repaired analytical units and transformations."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from analysis.revamp import acquire_contextual_data, acquire_data, acquire_spatial_data, run_analysis as analysis


class CoordinateRepairTests(unittest.TestCase):
    def test_repairs_rows_individually(self) -> None:
        frame = pd.DataFrame(
            {
                "Latitude": [40.7, -73.9, 0],
                "Longitude": [-73.9, 40.7, 0],
            }
        )
        repaired, counts = analysis.repair_coordinates(frame)
        self.assertEqual(counts, {"as_published": 1, "reversed_in_export": 1, "unresolved": 1})
        self.assertAlmostEqual(repaired.loc[0, "latitude_clean"], 40.7)
        self.assertAlmostEqual(repaired.loc[1, "latitude_clean"], 40.7)
        self.assertTrue(np.isnan(repaired.loc[2, "latitude_clean"]))

    def test_point_in_polygon_respects_holes(self) -> None:
        geometry = {
            "type": "Polygon",
            "coordinates": [
                [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
                [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]],
            ],
        }
        self.assertTrue(analysis.geometry_contains_point(geometry, 0.5, 0.5))
        self.assertFalse(analysis.geometry_contains_point(geometry, 2, 2))


class AcquisitionTests(unittest.TestCase):
    def test_pinned_manifest_checksums_verify(self) -> None:
        manifest = acquire_data.verify_snapshot(acquire_data.RAW_DIR / "manifest.json")
        self.assertEqual(manifest["datasets"]["shootings"]["id"], "5ucz-vwe8")

    def test_spatial_snapshot_checksums_verify(self) -> None:
        self.assertTrue(acquire_spatial_data.validate_existing())

    def test_contextual_snapshot_checksums_verify(self) -> None:
        manifest = acquire_contextual_data.verify_snapshot()
        self.assertEqual(set(manifest["files"]), {"weather", "holidays", "sports", "political_events"})

    def test_generated_holiday_calendar_uses_actual_and_observed_dates(self) -> None:
        holidays = acquire_contextual_data.holiday_calendar()
        self.assertEqual(len(holidays), 205)
        new_year_2006 = holidays[
            holidays["holiday_name"].eq("New Year's Day")
            & holidays["actual_date"].eq("2006-01-01")
        ].iloc[0]
        self.assertEqual(new_year_2006["observed_date"], "2006-01-02")


class DataIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = analysis.clean_data()
        cls.complete_year = int(cls.data.audit["current_snapshot"]["latest_complete_year"])
        cls.annual = analysis.annual_counts(cls.data)
        cls.temporal = analysis.temporal_tables(cls.data, cls.complete_year)
        cls.contextual = {
            **analysis.seasonal_context(cls.temporal["daily_incidents"]),
            **analysis.weather_context(cls.temporal["daily_incidents"]),
            **analysis.event_context(cls.temporal["daily_incidents"]),
        }
        cls.location = analysis.location_tables(cls.data, cls.complete_year)
        cls.income = analysis.income_tables(cls.data)
        cls.fatality = analysis.fatality_tables(cls.data, cls.complete_year)

    def test_current_incident_table_is_unique(self) -> None:
        self.assertEqual(len(self.data.shootings), self.data.shootings["INCIDENT_KEY"].nunique())

    def test_legacy_rows_are_not_incident_counts(self) -> None:
        self.assertGreater(len(self.data.legacy), self.data.legacy["INCIDENT_KEY"].nunique())

    def test_latest_complete_year_excludes_partial_2026(self) -> None:
        self.assertEqual(self.complete_year, 2025)

    def test_pinned_snapshot_quality_counts_do_not_drift_silently(self) -> None:
        self.assertEqual(self.data.audit["shootings"]["clean_rows"], 24_310)
        self.assertEqual(self.data.audit["victims"]["exact_duplicates_removed"], 164)
        self.assertEqual(self.data.audit["offenders"]["exact_duplicates_removed"], 116)
        self.assertEqual(
            self.data.audit["shootings"]["coordinate_status"],
            {"as_published": 321, "reversed_in_export": 23_988, "unresolved": 1},
        )

    def test_2026_ytd_is_compared_with_matching_2025_window(self) -> None:
        comparison = analysis.ytd_comparison(self.data).set_index("year")
        self.assertEqual(comparison.loc[2025, "through_month_day"], "06-30")
        self.assertEqual(int(comparison.loc[2025, "incidents"]), 337)
        self.assertEqual(int(comparison.loc[2026, "incidents"]), 322)

    def test_daily_series_is_complete(self) -> None:
        daily = self.temporal["daily_incidents"]
        expected = (pd.Timestamp("2025-12-31") - daily["date"].min()).days + 1
        self.assertEqual(len(daily), expected)
        self.assertFalse(daily["incidents"].isna().any())

    def test_annual_incidents_reconcile_to_complete_daily_series(self) -> None:
        expected = int(self.annual.loc[self.annual["year"].le(2025), "incidents"].sum())
        self.assertEqual(expected, int(self.temporal["daily_incidents"]["incidents"].sum()))

    def test_coordinates_are_either_repaired_or_explicitly_unresolved(self) -> None:
        resolved = self.data.shootings.dropna(subset=["latitude_clean", "longitude_clean"])
        self.assertTrue(resolved["latitude_clean"].between(40, 41).all())
        self.assertTrue(resolved["longitude_clean"].between(-75, -73).all())

    def test_forecasts_do_not_use_future_dates(self) -> None:
        predictions, _, summary, _ = analysis.forecast_evaluation(
            self.temporal["daily_incidents"], self.complete_year, include_prophet=False
        )
        origins = pd.to_datetime(predictions["origin"])
        dates = pd.to_datetime(predictions["date"])
        self.assertTrue((dates > origins).all())
        self.assertTrue((predictions["step"] <= 28).all())
        self.assertTrue((predictions["prediction"] >= 0).all())
        primary_predictions = predictions[
            predictions["model"].eq(analysis.PRIMARY_FORECAST_MODEL)
        ]
        self.assertTrue(primary_predictions["lower_80"].notna().all())
        self.assertTrue((primary_predictions["lower_80"] <= primary_predictions["upper_80"]).all())
        primary_metrics = summary[summary["model"].eq(analysis.PRIMARY_FORECAST_MODEL)]
        self.assertEqual(set(primary_metrics["horizon_days"]), {14, 28})
        self.assertTrue((primary_metrics["mae_lift_vs_best_naive_pct"] > 0).all())

    def test_primary_forecast_spec_separates_development_and_evaluation(self) -> None:
        specification = analysis.forecast_model_specification().set_index("setting")["value"]
        self.assertEqual(specification["primary_model"], "dynamic_count_ensemble")
        self.assertIn("2018-2021", specification["development_origins"])
        self.assertIn("2022-2025", specification["evaluation_origins"])
        development = analysis.forecast_development_metrics(
            self.temporal["daily_incidents"]
        ).groupby(["model", "horizon_days"])["mae"].mean()
        for horizon in (14, 28):
            self.assertLess(
                development.loc[(analysis.PRIMARY_FORECAST_MODEL, horizon)],
                development.loc[("rolling_mean_28", horizon)],
            )

    def test_2020_spatial_assignments_reconcile(self) -> None:
        audit = self.income["spatial_assignment_audit"].set_index("metric")["count"]
        self.assertEqual(int(audit["shooting_incidents_2020"]), 1_532)
        self.assertEqual(int(audit["incidents_assigned_to_2020_tract"]), 1_532)
        self.assertEqual(int(audit["incidents_unassigned_to_2020_tract"]), 0)

    def test_income_analysis_uses_matching_2020_units(self) -> None:
        association = self.income["income_association_2020"].iloc[0]
        self.assertEqual(int(association["tracts"]), 2_206)
        self.assertLess(float(association["bootstrap_upper_95"]), 0)
        quartiles = self.income["income_quartile_2020"]
        self.assertEqual(int(quartiles["incidents_2020"].sum()), 1_495)

    def test_precinct_2020_counts_reconcile(self) -> None:
        precinct = self.location["precinct_2020_rates"]
        self.assertEqual(len(precinct), 77)
        self.assertEqual(int(precinct["incidents_2020"].sum()), 1_532)

    def test_location_missingness_is_explicit(self) -> None:
        locations = self.location["location_descriptions"]
        missing = locations[
            locations["field"].eq("detailed_location")
            & locations["status"].eq("missing_or_unknown")
        ]
        self.assertEqual(int(missing["count"].sum()), 14_484)

    def test_fatal_units_and_offender_coverage_reconcile(self) -> None:
        coverage = self.fatality["fatal_offender_coverage"].set_index("metric")["count"]
        self.assertEqual(int(coverage["fatal_victim_records"]), 4_781)
        self.assertEqual(int(coverage["fatal_incidents"]), 4_619)
        self.assertEqual(
            int(coverage["fatal_incidents"]),
            int(coverage["fatal_incidents_with_linked_known_offender"])
            + int(coverage["fatal_incidents_without_linked_known_offender"]),
        )

    def test_invalid_fatal_offender_age_is_visible(self) -> None:
        demographic = self.fatality["fatal_demographic_distributions"]
        invalid = demographic[
            demographic["entity"].eq("linked_known_offender")
            & demographic["field"].eq("age_group")
            & demographic["status"].eq("invalid_recorded_value")
        ]
        self.assertEqual(int(invalid["count"].sum()), 1)

    def test_contextual_weather_covers_every_complete_year_day(self) -> None:
        coverage = self.contextual["weather_coverage"].iloc[0]
        self.assertEqual(int(coverage["days"]), 7_305)
        self.assertEqual(int(coverage["missing_average_temperature"]), 0)
        result = self.contextual["weather_temperature_association"].iloc[0]
        self.assertGreater(float(result["incidence_rate_ratio"]), 0)
        self.assertLess(float(result["lower_95"]), float(result["incidence_rate_ratio"]))
        self.assertGreater(float(result["upper_95"]), float(result["incidence_rate_ratio"]))

    def test_championship_universe_has_all_three_series_for_twenty_years(self) -> None:
        sports = pd.read_csv(analysis.CONTEXTUAL / "championship_games_2006_2025.csv")
        sports["year"] = pd.to_datetime(sports["event_date"]).dt.year
        self.assertEqual(set(sports["series"]), {"NBA Finals", "Super Bowl", "World Series"})
        self.assertTrue(sports.groupby("series")["year"].nunique().eq(20).all())
        self.assertTrue(sports[sports["series"].eq("Super Bowl")].groupby("year").size().eq(1).all())

    def test_political_event_comparison_is_bounded_and_reports_saturation(self) -> None:
        coverage = self.contextual["contextual_event_coverage"].set_index("dataset")
        self.assertEqual(coverage.loc["political_crowds", "start_date"], "2017-01-04")
        self.assertEqual(coverage.loc["political_crowds", "end_date"], "2025-12-31")
        adjusted = self.contextual["protest_adjusted_association"].iloc[0]
        self.assertEqual(int(adjusted["event_days"]), 2_648)
        self.assertEqual(int(adjusted["event_days"] + adjusted["non_event_days"]), 3_287)
        matched = self.contextual["protest_match_summary"].query(
            "category == 'All included dates'"
        ).iloc[0]
        self.assertLess(int(matched["matched_event_days"]), int(adjusted["event_days"]))


if __name__ == "__main__":
    unittest.main()
