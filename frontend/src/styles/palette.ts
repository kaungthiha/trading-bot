/** Chart colours, mirroring styles/tokens.css. SVG presentation attributes can't read CSS
 * variables, so the values live here once instead of in every chart.
 *
 * GAIN/LOSS were run through the dataviz palette validator on SURFACE (#fffcf6): lightness,
 * chroma, colour-vision separation (worst protan dE 15.8) and contrast all pass. Sign is
 * also encoded by position or direction in every chart, never by colour alone. */
export const CHART = {
  series: "#356fa3", // == --blue: the one series colour, and gains
  gain: "#356fa3",
  loss: "#b8483b",   // == --red
  ink: "#2d2925",    // == --ink: lines and direct labels
  muted: "#6b645b",  // == --muted: axis text (5.7:1 on SURFACE)
  grid: "#e2d9cc",   // == --line: recessive grid
  base: "#b9aa98",   // == --line-strong: zero / reference lines
  surface: "#fffcf6", // == --surface: plot background and the 2px separation ring
} as const;
