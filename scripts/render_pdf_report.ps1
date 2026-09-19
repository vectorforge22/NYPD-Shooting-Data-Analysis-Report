$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$rscriptPath = Join-Path $projectRoot ".tools\R-4.6.1\bin\Rscript.exe"
$pandocPath = Join-Path $projectRoot ".tools\pandoc-3.11\pandoc-3.11"
$tinytexPath = Join-Path $projectRoot ".tools\TinyTeX\bin\windows"
$renderScript = Join-Path $projectRoot "reports\scripts\render_pdf_report.R"

foreach ($requiredPath in @($rscriptPath, $pandocPath, $tinytexPath, $renderScript)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "PDF report prerequisite is missing: $requiredPath"
    }
}

$env:RSTUDIO_PANDOC = $pandocPath
$env:RENV_CONFIG_SANDBOX_ENABLED = "FALSE"
$env:RENV_PATHS_CACHE = Join-Path $projectRoot ".tools\renv-cache"
$env:RENV_PATHS_ROOT = Join-Path $projectRoot ".tools\renv-root"
$env:PATH = "$tinytexPath;$env:PATH"

Push-Location $projectRoot
try {
    & $rscriptPath $renderScript $projectRoot
    if ($LASTEXITCODE -ne 0) {
        throw "PDF report render failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
