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

/** Compact dollar formatter — $850, $12.4K, $8.1M, $1.2B, $3.4T, $1.0Q.
 *  Goes up to quadrillions so the demo faucet's huge apUSD grant stays legible. */
export function formatVolume(usd: number): string {
  if (usd >= 1e15) return `$${(usd / 1e15).toFixed(1)}Q`;
  if (usd >= 1e12) return `$${(usd / 1e12).toFixed(1)}T`;
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

const SIGNED_USD_FMT = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** "+$84.20" / "-$210.80" / "$0.00" — a P/L dollar amount with an explicit
 *  leading sign for non-zero values, so a gain reads unambiguously on the
 *  arena leaderboard. */
export function formatSignedUsd(n: number): string {
  const body = SIGNED_USD_FMT.format(Math.abs(n));
  if (n > 0) return `+${body}`;
  if (n < 0) return `-${body}`;
  return body;
}

/** "42s" / "5m" / "2h" / "3d" — coarse age of an event given its distance in
 *  seconds. Negative distances (clock skew) clamp to "0s". Callers append
 *  their own "ago". */
export function relativeTime(secsAgo: number): string {
  if (secsAgo < 0) secsAgo = 0;
  if (secsAgo < 60) return `${secsAgo}s`;
  if (secsAgo < 3600) return `${Math.floor(secsAgo / 60)}m`;
  if (secsAgo < 86_400) return `${Math.floor(secsAgo / 3600)}h`;
  return `${Math.floor(secsAgo / 86_400)}d`;
}

/** Which volume figure a card should show, and what to call it.
 *
 *  All-time is preferred, but only events touched by a recent sync carry it: an
 *  event that has dropped out of the synced top-N keeps its last-captured 24h
 *  figure and never gets an all-time one. Falling back to that figure — labelled
 *  as what it is — beats dropping the line, which would have blanked 545 of 962
 *  production events. */
export function volumeStat(
  volume: number | null,
  volume24hr: number | null,
): { value: number; label: string } | null {
  if (volume !== null) return { value: volume, label: "vol" };
  if (volume24hr !== null) return { value: volume24hr, label: "24h vol" };
  return null;
}
