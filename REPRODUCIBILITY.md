# Reproducibility

## Evidence model

The repository separates mutable source acquisition from a pinned analytical snapshot. The report reads maintained CSV and JSON outputs; it does not download live data during rendering. A new data refresh must create a new dated snapshot and edition.

## Python analysis

Use Python 3.12 and install the pinned analysis requirements:

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r analysis\requirements.txt
```

Acquire the official and contextual inputs from the repository root:

```powershell
& .\.venv\Scripts\python.exe analysis\acquire_data.py
& .\.venv\Scripts\python.exe analysis\acquire_spatial_data.py
& .\.venv\Scripts\python.exe analysis\acquire_contextual_data.py
```

Run the maintained analysis and tests:

```powershell
& .\.venv\Scripts\python.exe analysis\run_analysis.py
& .\.venv\Scripts\python.exe -m unittest analysis\test_analysis.py
```

The publication baseline passes 25 tests. `analysis/results/` contains the report's evidence layer, including unit reconciliation, annual and year-to-date counts, spatial and contextual analyses, forecast evaluation, and audit records.

## Report rendering

The report source is `report/source/NYPDShootingDataReport_Rebuilt.Rmd`. The private production checkout pins R, R packages, Pandoc, XeLaTeX, and supporting tools. This public repository records the source and entry-point scripts but does not duplicate the complete local toolchain.

From a compatible R environment with the required packages and Pandoc/XeLaTeX available, adapt the project-root paths in `scripts/render_pdf_report.R` and render the report. The published PDF is included so readers can inspect the exact fixed-layout edition without reconstructing the toolchain.

## Data boundaries

- Official snapshot: NYC Open Data shootings, victims, and offenders tables through 30 June 2026.
- Complete-year comparisons: 2006-2025.
- Partial-year comparison: 1 January through 30 June only.
- Contextual inputs: NOAA Central Park daily summaries, federal holiday rules, championship schedules, and Crowd Counting Consortium records.
- Raw downloaded files are excluded from Git. The report appendix and analysis outputs preserve source IDs, timestamps, and SHA-256 checksums.

## Verification performed for the publication edition

- 25 maintained analysis tests passed.
- The 42-page PDF was rendered to page images and every page was visually reviewed.
- The corrected PDF contains the current public repository address and the original course-report date.

