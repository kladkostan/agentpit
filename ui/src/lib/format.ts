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

const CLOCK_FMT = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
});

/** "12:50 PM" — used to label rotating-series time windows. */
export function formatClock(seconds: number | null): string | null {
  if (seconds === null) return null;
  return CLOCK_FMT.format(new Date(seconds * 1000));
}

/** "4:03" — a mm:ss countdown from a non-negative second count. */
export function formatCountdown(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${String(rem).padStart(2, "0")}`;
}

/** Parse a stringified upstream volume ("0", "14646954.7", "") into a number.
 *  Returns null for absent/zero/unparseable values so call sites can hide the
 *  stat rather than render a misleading "$0". */
export function parseVolume(raw: string | null | undefined): number | null {
  if (raw == null) return null;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

/** Compact dollar formatter — $850, $12.4K, $8.1M, $1.2B. */
export function formatVolume(usd: number): string {
  if (usd >= 1_000_000_000) return `$${(usd / 1_000_000_000).toFixed(1)}B`;
  if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(1)}M`;
  if (usd >= 1_000) return `$${(usd / 1_000).toFixed(1)}K`;
  return `$${Math.round(usd)}`;
}

/** Format a YES mid-price (dollars in [0, 1]) as a whole-percent probability
 *  label, without the "%" sign. A non-zero probability below 1% renders as
 *  "<1" rather than rounding down to a misleading "0"; a null mid renders as
 *  an em dash. Call sites append their own "%". */
export function formatProbabilityPct(mid: number | null): string {
  if (mid === null) return "—";
  const pct = mid * 100;
  if (pct <= 0) return "0";
  if (pct < 1) return "<1";
  return String(Math.round(pct));
}
