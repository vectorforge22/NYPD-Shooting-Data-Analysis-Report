# Maintained analysis

This directory contains the repaired analysis. The historical R and notebook files elsewhere under `analysis/` remain provenance, not maintained evidence.

## Analytical units

- **Shooting incident:** one row per `INCIDENT_KEY` in the current shootings table.
- **Shooting victim:** one row per victim record in the current victims table.
- **Known offender record:** one row per offender record in the current offenders table. This is not a count of convictions or a population risk estimate.

The old combined file repeats `INCIDENT_KEY` for multi-victim incidents. Its row count must not be labeled as an incident count.

## Data acquisition

From the repository root:

```powershell
& .\.venv\Scripts\python.exe analysis\revamp\acquire_data.py
```

The acquisition script pins the three current NYC Open Data tables, their metadata, checksums, and retrieval timestamp under `data/raw/official/`. Without `--force`, it verifies the existing snapshot and leaves its original retrieval time intact. Use `--force` only when intentionally creating a new versioned snapshot.

Step 4 contextual inputs are independently pinned under `data/external/contextual/`:

```powershell
& .\.venv\Scripts\python.exe analysis\revamp\acquire_contextual_data.py
```

The contextual manifest records NOAA weather, rule-generated federal holidays, ESPN/MLB championship schedules, all three official Crowd Counting Consortium Dataverse phases, and the disposition of the earlier working files. Without `--force`, the command verifies checksums and performs no network access.

## Environment

```powershell
& '<Python 3.12 path>' -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r analysis\revamp\requirements.txt
```

The pinned `cmdstanpy` version is intentional: it is compatible with Prophet's bundled model in the tested Python 3.12 environment.

## Run and verify

```powershell
& .\.venv\Scripts\python.exe analysis\revamp\run_analysis.py
& .\.venv\Scripts\python.exe -m unittest analysis\revamp\test_analysis.py
```

Use `--skip-prophet` only for a quick descriptive/baseline check. Publication results must come from the full run.

## Maintained outputs

`results/ANALYSIS_FINDINGS.md` is the compact interpretation guide. The accompanying CSV and JSON files preserve the audit, incident/victim/offender reconciliation, annual and year-to-date counts, period sensitivity, temporal patterns, demographic completeness, borough rates, contextual comparisons, and rolling forecast evaluation. `forecast_model_specification.csv` records the fixed development/evaluation split and the preferred model's components.

The historical R Markdown and scripts remain intact as provenance. This Python 3.12 pipeline is the maintained repair because it makes the data units, validation rules, and rolling forecast comparisons explicit and testable.

## Interpretation boundaries

- Current shootings, victim, and offender tables have different units; do not substitute one for another.
- Full-year comparisons stop at the latest complete calendar year. The incomplete 2026 record is year-to-date only.
- Changepoints are exploratory descriptions, not evidence of causes.
- Borough rates use the matching 2020 Census denominator only.
- The preferred forecast is a dynamic count ensemble selected on 2018-2021 development origins and evaluated on untouched 2022-2025 origins. It combines a recent local level, shrunk weekday effects, a regularised log-autoregression, and negative-binomial predictive intervals.
- Prophet remains as the original project choice, but it is superseded in this snapshot because it loses to the preferred model and the strongest naive benchmark at both evaluated horizons.

## Deliberate exclusions from the repaired evidence layer

The historical income-overlay map and the old weather, holiday, sports, and protest working files are not used as analytical inputs. Step 4 replaces them with pinned, independently sourced contextual data and bounded association designs while preserving the originals as provenance. Step 5 answers the empty ARIMA, bounded XGBoost, and GARCH inquiries explicitly: the autoregressive idea is evaluated in corrected form, date-and-lag tree boosting is not promoted for this citywide report, and negative-binomial count dispersion replaces GARCH for predictive uncertainty. A separate Part 2 document will address the larger contextual XGBoost v2 system, its source inventory, and the data engineering required to evaluate it.
