report_colours <- c(
  ink = "#14212B",
  slate = "#56656F",
  teal = "#216A70",
  orange = "#B9582B",
  ochre = "#C59A35",
  mist = "#D9DED9",
  paper = "#F7F5F0"
)

theme_report <- function(base_size = 10) {
  ggplot2::theme_minimal(base_size = base_size) +
    ggplot2::theme(
      plot.title = ggplot2::element_text(
        colour = report_colours[["ink"]],
        face = "bold",
        size = ggplot2::rel(1.35),
        margin = ggplot2::margin(b = 5)
      ),
      plot.subtitle = ggplot2::element_text(
        colour = report_colours[["slate"]],
        size = ggplot2::rel(1.02),
        margin = ggplot2::margin(b = 10)
      ),
      plot.caption = ggplot2::element_text(
        colour = report_colours[["slate"]],
        size = ggplot2::rel(0.78),
        hjust = 1,
        margin = ggplot2::margin(t = 8)
      ),
      axis.title = ggplot2::element_text(colour = report_colours[["ink"]]),
      axis.text = ggplot2::element_text(colour = report_colours[["slate"]]),
      axis.ticks = ggplot2::element_blank(),
      panel.grid.minor = ggplot2::element_blank(),
      panel.grid.major.x = ggplot2::element_blank(),
      panel.grid.major.y = ggplot2::element_line(
        colour = report_colours[["mist"]],
        linewidth = 0.35
      ),
      legend.position = "top",
      legend.justification = "left",
      legend.title = ggplot2::element_blank(),
      legend.text = ggplot2::element_text(
        colour = report_colours[["slate"]],
        size = ggplot2::rel(0.88)
      ),
      strip.text = ggplot2::element_text(
        colour = report_colours[["ink"]],
        face = "bold"
      ),
      strip.background = ggplot2::element_rect(
        fill = report_colours[["paper"]],
        colour = NA
      ),
      plot.margin = ggplot2::margin(10, 10, 12, 10)
    )
}

report_fill_scale <- function(...) {
  ggplot2::scale_fill_manual(
    values = c(
      "Victim records" = report_colours[["teal"]],
      "Known-offender records" = report_colours[["orange"]],
      "Fatal victim records" = report_colours[["orange"]],
      "Fatal incidents" = report_colours[["teal"]],
      "Fatal-victim records" = report_colours[["teal"]],
      "Linked known-offender records" = report_colours[["orange"]]
    ),
    ...
  )
}

report_colour_scale <- function(...) {
  ggplot2::scale_colour_manual(
    values = c(
      "Victim records" = report_colours[["teal"]],
      "Known-offender records" = report_colours[["orange"]],
      "Fatal victim records" = report_colours[["orange"]],
      "Fatal incidents" = report_colours[["teal"]]
    ),
    ...
  )
}

add_report_watermark <- function(plot, label = "Arthur Dominic Blanc") {
  plot +
    ggplot2::labs(caption = label) +
    ggplot2::theme(
      plot.caption = ggplot2::element_text(
        colour = grDevices::adjustcolor(report_colours[["slate"]], alpha.f = 0.65),
        size = ggplot2::rel(0.72),
        hjust = 1,
        margin = ggplot2::margin(t = 5)
      )
    )
}
