# Repaired analysis findings

**Official snapshot retrieved:** 2026-09-14T04:31:12+00:00

**Official data boundary:** 2006-01-01 through 2026-06-30

**Latest complete calendar year used for annual comparison:** 2025

These are maintained analytical results, not finished publication prose. Descriptive patterns do not establish causes.

## Central correction: rows were not incidents

The legacy file contains 28,562 rows but only 22,394 unique incident keys. It repeats 6,168 rows across multi-victim incidents, with as many as 18 rows for one incident. The old report's annual row totals therefore measured victim records while labeling them shooting incidents.

The repaired analysis uses the current shootings table for incident counts, the victims table for victim counts, and the offenders table for known-offender records. These units are never interchanged.

## Refreshed trend

- Recorded incidents rose from 777 in 2019 to 1,532 in 2020 (97.2%). This is a discontinuity in the observed series, not a causal estimate.
- Incidents declined from 974 in 2023 to 688 in 2025 (-29.4%).
- Through 06-30, 2026 recorded 322 incidents versus 337 over the equivalent 2025 window (-4.5%). The partial year is not mixed into full-year comparisons.
- `period_summary.csv` keeps context-defined eras separate from the exploratory segmented-linear sensitivity periods.
- An exploratory segmented-linear sensitivity check preferred segment starts at `2013;2020` by BIC. This is a descriptive model-selection result; it does not identify historical causes or prove that the break dates were known in advance.

## Data-quality repairs

- The current shootings export contains 23,988 rows whose published latitude and longitude values are reversed and 321 rows already in the stated orientation. The repair uses per-row NYC range checks; it does not swap whole columns.
- Exact duplicate records removed: 164 victim rows and 116 offender rows.
- Records lacking a matching current incident key remain visible in the audit: 2 victim rows and 2 offender rows. They are excluded from date-based summaries because their occurrence date cannot be established from the current incident table.

## Demographic measurement

The offender table contains records for known suspects/offenders; it is not the denominator for all incidents or for any population-risk claim. Categories are recorded administrative fields rather than complete identities.

- victim age_group: 60 missing/unknown (0.2%); 1 invalid recorded values (0.00%).
- victim recorded_sex: 12 missing/unknown (0.0%); 0 invalid recorded values (0.00%).
- victim recorded_race: 65 missing/unknown (0.2%); 0 invalid recorded values (0.00%).
- offender age_group: 3,394 missing/unknown (17.8%); 6 invalid recorded values (0.03%).
- offender recorded_sex: 1,395 missing/unknown (7.3%); 0 invalid recorded values (0.00%).
- offender recorded_race: 1,749 missing/unknown (9.2%); 0 invalid recorded values (0.00%).

Full category counts—including unknown and invalid recorded values—are retained in `demographic_distributions.csv`.

## Place, income, and fatality findings

- The tract analysis assigns 1,532 of 1,532 2020 incidents to January 2020-vintage Census tracts.
- Across 2,206 tracts with positive population and a published positive median household income, the Spearman association between median household income and the 2020 incident rate was -0.371 (tract bootstrap 95% interval -0.409 to -0.334). This is an ecological association, not an individual-level or causal result.
- Income-quartile aggregate rates ranged from 4.7 per 100,000 in the highest-income tract quartile to 35.7 in the lowest-income quartile.
- Complete years contain 4,619 fatal incidents and 4,781 fatal victim records. 3,040 fatal incidents have at least one linked known-offender record; 1,579 do not.
- The linked known-offender demographic table is limited to 4,157 distinct published records. It does not describe every fatal incident, conviction, or population group.

## Contextual associations

- Summer had the highest complete-year rate at 4.33 incidents per calendar day.
- In the daily Poisson model with year, month, and weekday fixed effects, a 5°C higher Central Park average temperature was associated with an incident-rate ratio of 1.174 (14-day HAC 95% interval 1.151 to 1.197). This is a within-calendar association, not a causal effect of temperature.
- Across 205 federal holiday dates with same-weekday controls inside the same year, the mean difference was 1.558 incidents per day (bootstrap 95% interval 1.157 to 1.969).
- Across 249 independently sourced championship-game dates, the mean difference from matched controls was -0.023 incidents per day (bootstrap 95% interval -0.286 to 0.238).
- The political-event comparison is restricted to the CCC coverage period. A calendar-adjusted model comparing 2,648 recorded political-crowd days with 639 non-event days estimated an incident-rate ratio of 1.149 (14-day HAC 95% interval 1.040 to 1.269). A same-weekday matched sensitivity could pair 638 event days. Reporting and event coverage are not random, so this remains an association with recorded event days.

## Forecast evaluation

Forecasts use rolling chronological origins, never random train/test splits. Model structure was selected on 2018-2021 development origins; the publication comparison uses twelve untouched 2022-2025 origins. Each origin predicts the following 28 days, with metrics at 14 and 28 days. Every fitted model sees only observations available at its origin.

The preferred model is the dynamic count ensemble: 75% recent 28-day local level with a shrunk weekday adjustment, plus 25% regularised recursive log-autoregression. Negative-binomial predictive intervals keep the output non-negative and allow variance to exceed the mean.

- 14-day dynamic-count MAE was 1.523 incidents/day, 1.45% better than the best predeclared naive model and 7.33% better than Prophet; its nominal 80% negative-binomial interval covered 91.67% of observations.
- 28-day dynamic-count MAE was 1.409 incidents/day, 3.98% better than the best predeclared naive model and 12.39% better than Prophet; its nominal 80% negative-binomial interval covered 92.86% of observations.

- 14-day horizon: `dynamic_count_ensemble` had the lowest mean MAE (1.523 incidents/day).
- 28-day horizon: `autoregressive_log_ridge` had the lowest mean MAE (1.409 incidents/day).

- 14-day Prophet MAE was 1.644 incidents/day, 6.34% worse than the best naive model; its nominal 80% interval covered 79.76% of observations.
- 28-day Prophet MAE was 1.608 incidents/day, 9.60% worse than the best naive model; its nominal 80% interval covered 78.57% of observations.

Forecast verdict: **`dynamic_count_ensemble_preferred`**. The dynamic count ensemble supersedes Prophet for this report because it had lower MAE at both horizons, preserved the count scale, and beat the strongest predeclared naive benchmark in the untouched evaluation window. Prophet remains as the original historical choice and a fully evaluated comparison.

## Publication boundaries

- Use complete years for annual comparisons. Treat 2026 only as year-to-date and compare it with equivalent year-to-date windows.
- The 2020 borough rate uses the official 2020 Census population denominator. Do not apply that fixed denominator to the full 2006-2025 period.
- The tract-income result combines 2020 incidents, January 2020-vintage tract geometry, and 2020 ACS 5-year estimates. It remains subject to ACS uncertainty, small-area rate instability, ecological fallacy, and spatial dependence.
- Do not infer causes from time coincidence, demographics from incident-level joins, or offender characteristics for incidents without an offender record.
