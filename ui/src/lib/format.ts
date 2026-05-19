/** Locale formatters + small wrappers used across cards and detail pages.
 *
 *  Keep these in one place so a label like "May 19" or a volume like "$8.1M"
 *  renders identically wherever it appears. Wrappers accept Unix-seconds
 *  inputs (the shape every market endpoint returns) and return `null` for
 *  null inputs so call sites don't have to guard.
 */

const SHORT_DATE_FMT = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
});

const LONG_DATE_FMT = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
});

/** "May 19" — used on grid cards and chart axes. */
export function formatShortDate(seconds: number | null): string | null {
  if (seconds === null) return null;
  return SHORT_DATE_FMT.format(new Date(seconds * 1000));
}

/** "May 19, 2026" — used in the event/market detail header. */
export function formatLongDate(seconds: number | null): string | null {
  if (seconds === null) return null;
  return LONG_DATE_FMT.format(new Date(seconds * 1000));
}

/** Compact dollar formatter — $850, $12.4K, $8.1M, $1.2B. */
export function formatVolume(usd: number): string {
  if (usd >= 1_000_000_000) return `$${(usd / 1_000_000_000).toFixed(1)}B`;
  if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(1)}M`;
  if (usd >= 1_000) return `$${(usd / 1_000).toFixed(1)}K`;
  return `$${Math.round(usd)}`;
}
