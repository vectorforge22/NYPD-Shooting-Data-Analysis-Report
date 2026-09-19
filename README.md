# NYPD Shooting Data Analysis Report

This public repository contains the reproducible evidence, report source, and release material for *NYPD Shooting Incidents: Exploratory Analysis and Forecast Evaluation* by Arthur Dominic Blanc.

The project began as graduate coursework and was rebuilt as an independent publication. The maintained edition corrects an incident-versus-victim unit error, refreshes official data through 30 June 2026, separates incident, victim, and known-offender records, and evaluates forecasting methods on chronological holdouts.

## Read the report

- `report/NYPD_Shooting_Incidents_Publication_Edition.pdf` - fixed-layout publication edition
- `report/source/NYPDShootingDataReport_Rebuilt.Rmd` - maintained report source
- `analysis/results/ANALYSIS_FINDINGS.md` - compact evidence summary

The reflowable Kindle edition is being finalized separately. Versioned PDF and EPUB downloads should be attached to GitHub Releases once the final Kindle v3 files are approved.

## Repository layout

- `analysis/` - acquisition, validation, repaired analysis, tests, and published result tables
- `report/source/` - R Markdown source, theme, data-loading layer, Kindle stylesheet, and PDF preamble
- `report/` - visually reviewed fixed-layout PDF
- `scripts/` - report rendering entry points
- `assets/` - publication cover
- `REPRODUCIBILITY.md` - environment, data, and verification instructions
- `NOTICE.md` - authorship, institutional, data-source, AI, and licensing boundaries

## Important interpretation boundaries

- A shooting incident, a victim record, and a known-offender record are different analytical units.
- Known-offender records are incomplete and are not evidence of conviction.
- Demographic fields describe published administrative records, not population risk, guilt, propensity, or cause.
- Geographic and contextual comparisons are observational unless the report explicitly establishes a stronger design.
- Partial 2026 data are compared only with equivalent year-to-date windows.

## Public data and repository scope

The analysis uses public records and public-source contextual data. Raw snapshots are intentionally not committed here. The acquisition scripts, source identifiers, retrieval timestamps, hashes, maintained results, and tests provide the reproducibility path without turning the repository into a second data-distribution service.

## Corrections

Open an issue identifying the edition date, affected claim or figure, and supporting evidence. A source-data refresh should be released as a new dated edition rather than silently changing the meaning of an existing snapshot.

## Status

The fixed-layout report is publication-ready. The Kindle v3 package remains in owner review and should not be represented as final until its KPF has passed the manual device-preview checklist.

