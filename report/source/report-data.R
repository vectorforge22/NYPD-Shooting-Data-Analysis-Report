project_root <- here::here()
results_dir <- file.path(project_root, "analysis", "revamp", "results")
snapshot_dir <- file.path(project_root, "data", "raw", "official")
contextual_dir <- file.path(project_root, "data", "external", "contextual")

required_result_files <- c(
  "annual_counts.csv",
  "borough_2020_rates.csv",
  "daily_incidents.csv",
  "data_audit.json",
  "demographic_distributions.csv",
  "demographic_quality.csv",
  "fatal_borough.csv",
  "fatal_demographic_distributions.csv",
  "fatal_location_descriptions.csv",
  "fatal_offender_coverage.csv",
  "fatal_precinct.csv",
  "fatal_temporal_hour.csv",
  "fatal_temporal_month.csv",
  "fatal_temporal_weekday.csv",
  "forecast_development_metrics.csv",
  "forecast_metrics_by_origin.csv",
  "forecast_metrics_summary.csv",
  "forecast_model_specification.csv",
  "forecast_predictions.csv",
  "income_association_2020.csv",
  "income_quartile_2020.csv",
  "income_tract_2020.csv",
  "contextual_event_coverage.csv",
  "holiday_match_summary.csv",
  "location_descriptions.csv",
  "period_summary.csv",
  "precinct_2020_rates.csv",
  "protest_adjusted_association.csv",
  "protest_coverage_by_year.csv",
  "protest_match_summary.csv",
  "seasonal_summary.csv",
  "spatial_assignment_audit.csv",
  "spatial_points_complete.csv",
  "sports_match_summary.csv",
  "temporal_hour.csv",
  "temporal_month.csv",
  "temporal_weekday.csv",
  "weather_coverage.csv",
  "weather_temperature_association.csv",
  "weather_temperature_bins.csv",
  "ytd_comparison.csv"
)

required_paths <- c(
  file.path(results_dir, required_result_files),
  file.path(snapshot_dir, "manifest.json"),
  file.path(contextual_dir, "manifest.json")
)

missing_paths <- required_paths[!file.exists(required_paths)]
if (length(missing_paths) > 0L) {
  stop(
    "The maintained analysis is incomplete. Missing: ",
    paste(missing_paths, collapse = ", ")
  )
}

read_result <- function(name) {
  readr::read_csv(
    file.path(results_dir, name),
    show_col_types = FALSE,
    progress = FALSE
  )
}

audit <- jsonlite::read_json(
  file.path(results_dir, "data_audit.json"),
  simplifyVector = TRUE
)
manifest <- jsonlite::read_json(
  file.path(snapshot_dir, "manifest.json"),
  simplifyVector = TRUE
)
contextual_manifest <- jsonlite::read_json(
  file.path(contextual_dir, "manifest.json"),
  simplifyVector = TRUE
)

annual_counts <- read_result("annual_counts.csv")
borough_2020 <- read_result("borough_2020_rates.csv")
daily_incidents <- read_result("daily_incidents.csv") |>
  dplyr::mutate(
    date = as.Date(date),
    month = as.integer(format(date, "%m")),
    month_name = factor(
      month.abb[month],
      levels = month.abb
    )
  )
demographic_distributions <- read_result("demographic_distributions.csv")
demographic_quality <- read_result("demographic_quality.csv")
fatal_borough <- read_result("fatal_borough.csv")
fatal_demographic_distributions <- read_result("fatal_demographic_distributions.csv")
fatal_location_descriptions <- read_result("fatal_location_descriptions.csv")
fatal_offender_coverage <- read_result("fatal_offender_coverage.csv")
fatal_precinct <- read_result("fatal_precinct.csv")
fatal_temporal_hour <- read_result("fatal_temporal_hour.csv")
fatal_temporal_month <- read_result("fatal_temporal_month.csv")
fatal_temporal_weekday <- read_result("fatal_temporal_weekday.csv")
forecast_development_metrics <- read_result("forecast_development_metrics.csv")
forecast_metrics_by_origin <- read_result("forecast_metrics_by_origin.csv")
forecast_metrics_summary <- read_result("forecast_metrics_summary.csv")
forecast_model_specification <- read_result("forecast_model_specification.csv")
forecast_predictions <- read_result("forecast_predictions.csv") |>
  dplyr::mutate(origin = as.Date(origin), date = as.Date(date))
income_association_2020 <- read_result("income_association_2020.csv")
income_quartile_2020 <- read_result("income_quartile_2020.csv")
income_tract_2020 <- read_result("income_tract_2020.csv")
contextual_event_coverage <- read_result("contextual_event_coverage.csv")
holiday_match_summary <- read_result("holiday_match_summary.csv")
location_descriptions <- read_result("location_descriptions.csv")
period_summary <- read_result("period_summary.csv")
precinct_2020 <- read_result("precinct_2020_rates.csv")
protest_adjusted_association <- read_result("protest_adjusted_association.csv")
protest_coverage_by_year <- read_result("protest_coverage_by_year.csv")
protest_match_summary <- read_result("protest_match_summary.csv")
seasonal_summary <- read_result("seasonal_summary.csv")
spatial_assignment_audit <- read_result("spatial_assignment_audit.csv")
spatial_points_complete <- read_result("spatial_points_complete.csv") |>
  dplyr::mutate(occur_date = as.Date(occur_date))
temporal_hour <- read_result("temporal_hour.csv")
temporal_month <- read_result("temporal_month.csv")
temporal_weekday <- read_result("temporal_weekday.csv")
sports_match_summary <- read_result("sports_match_summary.csv")
weather_coverage <- read_result("weather_coverage.csv")
weather_temperature_association <- read_result("weather_temperature_association.csv")
weather_temperature_bins <- read_result("weather_temperature_bins.csv")
ytd_comparison <- read_result("ytd_comparison.csv")

complete_annual <- dplyr::filter(annual_counts, is_complete_year)
partial_annual <- dplyr::filter(annual_counts, !is_complete_year)

if (!identical(audit$current_snapshot$date_max, "2026-06-30")) {
  stop("Unexpected current data boundary: ", audit$current_snapshot$date_max)
}
if (max(complete_annual$year) != audit$current_snapshot$latest_complete_year) {
  stop("Complete-year boundary does not match the maintained audit.")
}
if (sum(complete_annual$incidents) != sum(temporal_month$incidents)) {
  stop("Annual and monthly incident totals do not reconcile.")
}
if (sum(complete_annual$incidents) != sum(temporal_hour$incidents)) {
  stop("Annual and hourly incident totals do not reconcile.")
}
if (sum(complete_annual$incidents) != sum(daily_incidents$incidents)) {
  stop("Annual and daily incident totals do not reconcile.")
}
if (sum(borough_2020$incidents_2020) != complete_annual$incidents[complete_annual$year == 2020]) {
  stop("The 2020 borough counts do not reconcile to the annual incident total.")
}
if (sum(precinct_2020$incidents_2020) != complete_annual$incidents[complete_annual$year == 2020]) {
  stop("The 2020 precinct counts do not reconcile to the annual incident total.")
}
spatial_audit <- stats::setNames(spatial_assignment_audit$count, spatial_assignment_audit$metric)
if (spatial_audit[["incidents_assigned_to_2020_tract"]] !=
    complete_annual$incidents[complete_annual$year == 2020]) {
  stop("The 2020 tract assignments do not reconcile to the annual incident total.")
}
fatal_coverage <- stats::setNames(fatal_offender_coverage$count, fatal_offender_coverage$metric)
if (fatal_coverage[["fatal_incidents"]] != sum(complete_annual$fatal_incidents) ||
    fatal_coverage[["fatal_victim_records"]] != sum(complete_annual$fatal_victims)) {
  stop("Fatal incident and victim totals do not reconcile to annual totals.")
}
if (fatal_coverage[["fatal_incidents"]] !=
    fatal_coverage[["fatal_incidents_with_linked_known_offender"]] +
    fatal_coverage[["fatal_incidents_without_linked_known_offender"]]) {
  stop("Fatal known-offender coverage does not reconcile.")
}
if (weather_coverage$days[[1L]] != nrow(daily_incidents) ||
    weather_coverage$missing_average_temperature[[1L]] != 0L) {
  stop("Contextual weather coverage does not reconcile to the daily incident series.")
}
if (sum(protest_coverage_by_year$event_days) !=
    contextual_event_coverage$distinct_days[contextual_event_coverage$dataset == "political_crowds"]) {
  stop("Political-event day coverage does not reconcile.")
}

fmt_int <- function(value) {
  scales::comma(value, accuracy = 1)
}

fmt_decimal <- function(value, accuracy = 0.1) {
  scales::number(value, accuracy = accuracy)
}

fmt_pct <- function(value, accuracy = 0.1) {
  scales::percent(value, accuracy = accuracy)
}

annual_value <- function(year, field = "incidents") {
  row <- annual_counts[annual_counts$year == year, , drop = FALSE]
  if (nrow(row) != 1L) {
    stop("Expected exactly one annual row for ", year)
  }
  row[[field]][[1L]]
}

ytd_value <- function(year, field = "incidents") {
  row <- ytd_comparison[ytd_comparison$year == year, , drop = FALSE]
  if (nrow(row) != 1L) {
    stop("Expected exactly one year-to-date row for ", year)
  }
  row[[field]][[1L]]
}

incidents_2019 <- annual_value(2019)
incidents_2020 <- annual_value(2020)
incidents_2023 <- annual_value(2023)
incidents_2025 <- annual_value(2025)
ytd_incidents_2025 <- ytd_value(2025)
ytd_incidents_2026 <- ytd_value(2026)

change_2019_2020 <- incidents_2020 / incidents_2019 - 1
change_2023_2025 <- incidents_2025 / incidents_2023 - 1
change_ytd_2025_2026 <- ytd_incidents_2026 / ytd_incidents_2025 - 1

complete_incidents <- sum(complete_annual$incidents)
current_incidents <- audit$shootings$clean_rows
current_victims <- audit$victims$clean_rows
current_offenders <- audit$offenders$clean_rows

peak_month <- temporal_month[which.max(temporal_month$incidents_per_calendar_day), ]
lowest_month <- temporal_month[which.min(temporal_month$incidents_per_calendar_day), ]
peak_weekday <- temporal_weekday[which.max(temporal_weekday$incidents_per_calendar_day), ]
lowest_weekday <- temporal_weekday[which.min(temporal_weekday$incidents_per_calendar_day), ]
peak_hour <- temporal_hour[which.max(temporal_hour$incidents), ]
late_night_hours <- c(22, 23, 0, 1, 2)
late_night_share <- sum(temporal_hour$incidents[temporal_hour$occur_hour %in% late_night_hours]) /
  sum(temporal_hour$incidents)

highest_borough_rate <- borough_2020[which.max(borough_2020$incidents_per_100k_2020), ]
lowest_borough_rate <- borough_2020[which.min(borough_2020$incidents_per_100k_2020), ]

fatal_incidents_complete <- sum(complete_annual$fatal_incidents)
fatal_victims_complete <- sum(complete_annual$fatal_victims)
fatal_linked_incidents <- fatal_coverage[["fatal_incidents_with_linked_known_offender"]]
fatal_unlinked_incidents <- fatal_coverage[["fatal_incidents_without_linked_known_offender"]]
fatal_linked_offender_records <- fatal_coverage[["distinct_linked_known_offender_records"]]
fatal_linked_incident_share <- fatal_linked_incidents / fatal_incidents_complete

income_result <- income_association_2020[1, ]
income_q1 <- income_quartile_2020[income_quartile_2020$income_quartile == "Q1 lowest", ]
income_q4 <- income_quartile_2020[income_quartile_2020$income_quartile == "Q4 highest", ]
location_classification <- location_descriptions |>
  dplyr::filter(field == "location_classification") |>
  dplyr::arrange(dplyr::desc(count))
detailed_location_missing <- location_descriptions |>
  dplyr::filter(field == "detailed_location", status == "missing_or_unknown")

season_peak <- seasonal_summary[which.max(seasonal_summary$incidents_per_calendar_day), ]
season_low <- seasonal_summary[which.min(seasonal_summary$incidents_per_calendar_day), ]
temperature_result <- weather_temperature_association[1, ]
holiday_overall <- holiday_match_summary |>
  dplyr::filter(category == "All included dates")
holiday_ranked <- holiday_match_summary |>
  dplyr::filter(category != "All included dates") |>
  dplyr::arrange(dplyr::desc(paired_difference))
sports_overall <- sports_match_summary |>
  dplyr::filter(category == "All included dates")
sports_series <- sports_match_summary |>
  dplyr::filter(category != "All included dates")
protest_result <- protest_adjusted_association[1, ]
protest_matched <- protest_match_summary |>
  dplyr::filter(category == "All included dates")
primary_forecast_metrics <- forecast_metrics_summary |>
  dplyr::filter(model == "dynamic_count_ensemble") |>
  dplyr::arrange(horizon_days)
prophet_forecast_metrics <- forecast_metrics_summary |>
  dplyr::filter(model == "prophet") |>
  dplyr::arrange(horizon_days)
forecast_example_origin <- max(forecast_predictions$origin)
forecast_example <- forecast_predictions |>
  dplyr::filter(
    origin == forecast_example_origin,
    model %in% c("dynamic_count_ensemble", "prophet", "rolling_mean_28")
  )
contextual_retrieved <- sub("T", " ", contextual_manifest$retrieved_at_utc, fixed = TRUE)
contextual_retrieved <- sub("\\.[0-9]+", "", contextual_retrieved)
contextual_retrieved <- sub("\\+00:00$", " UTC", contextual_retrieved)

demographic_display <- demographic_distributions |>
  dplyr::mutate(
    display_value = dplyr::case_when(
      status == "missing_or_unknown" ~ "Unknown or missing",
      status == "invalid_recorded_value" ~ "Invalid recorded value",
      TRUE ~ value
    ),
    entity_label = dplyr::recode(
      entity,
      victim = "Victim records",
      offender = "Known-offender records"
    )
  ) |>
  dplyr::group_by(entity, entity_label, field, display_value) |>
  dplyr::summarise(count = sum(count), .groups = "drop") |>
  dplyr::group_by(entity, field) |>
  dplyr::mutate(share = count / sum(count)) |>
  dplyr::ungroup()

source_table <- data.frame(
  Analytical.unit = c("Shooting incident", "Victim record", "Known-offender record"),
  Dataset.ID = c(
    manifest$datasets$shootings$id,
    manifest$datasets$victims$id,
    manifest$datasets$offenders$id
  ),
  Records.after.cleaning = c(current_incidents, current_victims, current_offenders),
  stringsAsFactors = FALSE
)

hash_table <- data.frame(
  Dataset = c("Shootings", "Victims", "Known offenders"),
  Dataset.ID = c(
    manifest$datasets$shootings$id,
    manifest$datasets$victims$id,
    manifest$datasets$offenders$id
  ),
  SHA256 = c(
    manifest$datasets$shootings$csv_sha256,
    manifest$datasets$victims$csv_sha256,
    manifest$datasets$offenders$csv_sha256
  ),
  stringsAsFactors = FALSE
)

snapshot_retrieved <- sub("T", " ", manifest$retrieved_at_utc, fixed = TRUE)
snapshot_retrieved <- sub("\\+00:00$", " UTC", snapshot_retrieved)
