/** Ranked palette for chart series.
 *
 *  Position 0 is the default — used by the single-line sparkline on the
 *  home-page card and by the #1-ranked outcome on the multi-line event
 *  chart. Subsequent indices fall through to other Tailwind-500 hues.
 */
export const CHART_PALETTE = [
  "rgb(14 165 233)", // sky-500 (default / #1)
  "rgb(16 185 129)", // emerald-500 (#2)
  "rgb(245 158 11)", // amber-500 (#3)
  "rgb(244 63 94)",  // rose-500 (#4)
] as const;

/** Shorthand for the default sparkline color. */
export const CHART_PRIMARY_COLOR = CHART_PALETTE[0];
