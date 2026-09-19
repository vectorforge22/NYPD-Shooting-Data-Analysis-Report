args <- commandArgs(trailingOnly = TRUE)

project_root <- if (length(args) >= 1L) args[[1L]] else getwd()
project_root <- normalizePath(project_root, winslash = "/", mustWork = TRUE)

pandoc_dir <- file.path(project_root, ".tools", "pandoc-3.11", "pandoc-3.11")
tinytex_bin <- file.path(project_root, ".tools", "TinyTeX", "bin", "windows")
input_file <- file.path(
  project_root,
  "reports",
  "source",
  "NYPDShootingDataReport_Rebuilt.Rmd"
)
output_dir <- file.path(project_root, "reports", "rendered")
source_dir <- dirname(input_file)

required_paths <- c(
  file.path(pandoc_dir, "pandoc.exe"),
  file.path(tinytex_bin, "xelatex.exe"),
  input_file
)

missing_paths <- required_paths[!file.exists(required_paths)]
if (length(missing_paths) > 0L) {
  stop(
    "PDF report toolchain is incomplete: ",
    paste(missing_paths, collapse = ", ")
  )
}

Sys.setenv(RSTUDIO_PANDOC = pandoc_dir)
Sys.setenv(
  PATH = paste(tinytex_bin, Sys.getenv("PATH"), sep = .Platform$path.sep)
)

if (!requireNamespace("rmarkdown", quietly = TRUE)) {
  stop("The locked R dependency library is missing rmarkdown.")
}

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

original_working_directory <- getwd()
on.exit(setwd(original_working_directory), add = TRUE)
setwd(source_dir)

output_file <- rmarkdown::render(
  input = basename(input_file),
  output_file = "NYPDShootingDataReport_Rebuilt.pdf",
  output_dir = source_dir,
  envir = new.env(parent = globalenv()),
  clean = TRUE,
  quiet = FALSE
)

if (!file.exists(output_file)) {
  stop("The PDF render completed without producing the expected file.")
}

published_file <- file.path(output_dir, basename(output_file))
if (!file.copy(output_file, published_file, overwrite = TRUE)) {
  stop("The PDF rendered but could not be copied to the publication folder.")
}

unlink(output_file)
unlink(file.path(source_dir, "report-figures"), recursive = TRUE, force = TRUE)
message("Rendered: ", normalizePath(published_file, winslash = "/"))
