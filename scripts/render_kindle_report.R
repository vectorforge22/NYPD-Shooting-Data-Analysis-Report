args <- commandArgs(trailingOnly = TRUE)

project_root <- if (length(args) >= 1L) args[[1L]] else getwd()
project_root <- normalizePath(project_root, winslash = "/", mustWork = TRUE)

pandoc_dir <- file.path(project_root, ".tools", "pandoc-3.11", "pandoc-3.11")
input_file <- file.path(
  project_root,
  "reports",
  "source",
  "NYPDShootingDataReport_Rebuilt.Rmd"
)
output_dir <- file.path(project_root, "publishing", "kindle")
source_dir <- dirname(input_file)
cover_image <- file.path(
  project_root,
  "publishing",
  "cover",
  "NYPD_Shooting_Incidents_Kindle_Cover.jpg"
)

required_paths <- c(
  file.path(pandoc_dir, "pandoc.exe"),
  input_file,
  cover_image,
  file.path(source_dir, "kindle.css")
)

missing_paths <- required_paths[!file.exists(required_paths)]
if (length(missing_paths) > 0L) {
  stop(
    "Kindle report toolchain is incomplete: ",
    paste(missing_paths, collapse = ", ")
  )
}

Sys.setenv(RSTUDIO_PANDOC = pandoc_dir)

if (!requireNamespace("rmarkdown", quietly = TRUE)) {
  stop("The locked R dependency library is missing rmarkdown.")
}
if (!requireNamespace("bookdown", quietly = TRUE)) {
  stop("The locked R dependency library is missing bookdown.")
}

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

original_working_directory <- getwd()
on.exit(setwd(original_working_directory), add = TRUE)
setwd(source_dir)

render_one <- function(output_format, output_name) {
  source_output <- rmarkdown::render(
    input = basename(input_file),
    output_format = output_format,
    output_file = output_name,
    output_dir = source_dir,
    envir = new.env(parent = globalenv()),
    clean = TRUE,
    quiet = FALSE
  )

  if (!file.exists(source_output)) {
    stop("The render completed without producing ", output_name)
  }

  published_output <- file.path(output_dir, output_name)
  if (!file.copy(source_output, published_output, overwrite = TRUE)) {
    stop("The render completed but could not publish ", output_name)
  }
  unlink(source_output)
  normalizePath(published_output, winslash = "/")
}

epub_output <- render_one(
  bookdown::epub_book(
    fig_width = 7.2,
    fig_height = 4.5,
    dev = "png",
    fig_caption = TRUE,
    number_sections = TRUE,
    toc = TRUE,
    toc_depth = 2,
    stylesheet = "kindle.css",
    cover_image = cover_image,
    chapter_level = 1,
    epub_version = "epub3"
  ),
  "NYPD_Shooting_Incidents_Kindle.epub"
)

docx_output <- render_one(
  rmarkdown::word_document(
    toc = TRUE,
    toc_depth = 2,
    fig_caption = TRUE,
    number_sections = TRUE
  ),
  "NYPD_Shooting_Incidents_Kindle_Create.docx"
)

unlink(file.path(source_dir, "report-figures"), recursive = TRUE, force = TRUE)
unlink(file.path(source_dir, "NYPDShootingDataReport_Rebuilt_files"), recursive = TRUE, force = TRUE)

message("Rendered EPUB: ", epub_output)
message("Rendered DOCX: ", docx_output)
