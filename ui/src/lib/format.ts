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
 *  Goes up to quadrillions for upstream Polymarket market volumes. (It used to
 *  be sized for the old quadrillion-apUSD signup grant; that grant is $100k
 *  now, but the large branches still earn their keep on volume figures.) */
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
 *  `prefer` follows the list's sort, so the number on a card explains the order
 *  it is in. Under "24hr Volume" a card showing its all-time figure reads as a
 *  contradiction — $16.2M sitting above $12.0M above $1.4M, in a list that says
 *  it is ranked by the last day.
 *
 *  Either figure falls back to the other, because only events touched by a
 *  recent sync carry both: one that has dropped out of the synced top-N keeps
 *  its last-captured 24h figure and never gets an all-time one. Showing that —
 *  labelled as what it is — beats dropping the line, which would have blanked
 *  545 of 962 production events. */
export function volumeStat(
  volume: number | null,
  volume24hr: number | null,
  prefer: "total" | "24h" = "total",
): { value: number; label: string } | null {
  const total = volume !== null ? { value: volume, label: "vol" } : null;
  const daily =
    volume24hr !== null ? { value: volume24hr, label: "24h vol" } : null;
  return prefer === "24h" ? (daily ?? total) : (total ?? daily);
}

/** "3.3" / "25" / "-21.9" — a P/L percentage at one decimal, dropping a
 *  trailing ".0" so a clean value still reads as "25".
 *
 *  Rounding to a whole percent made the parenthetical contradict the dollars
 *  beside it: a $0.30 gain on a $9.20 cost is 3.26%, and "+$0.30 (3%)" invites
 *  the reader to compute 9.20 x 1.03 = $9.48 and wonder where the $9.50 came
 *  from. The sign is preserved; callers that print their own sign should pass
 *  an absolute value. */
export function formatPnlPct(pct: number): string {
  if (!Number.isFinite(pct)) return "0";
  const rounded = Math.round(pct * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

/** "0x933B…5215" — an address short enough to sit on one line without
 *  wrapping, keeping both ends so it stays recognisable at a glance. The full
 *  value is never far: every place this renders offers a way to copy it.
 *
 *  Shared rather than per-page: the Arena board and the profile show the same
 *  account, and two truncation rules would make it look like two accounts. */
export function shortAddress(a: string): string {
  return a.length < 12 ? a : `${a.slice(0, 6)}…${a.slice(-4)}`;
}

/** Small words that stay lowercase inside a title, unless they lead it. */
const TITLE_STOPWORDS = new Set([
  "a", "an", "and", "at", "by", "for", "in", "of", "on", "or", "the", "to", "vs",
]);

/** A tag label, cased for display.
 *
 *  Upstream authors these by hand and is inconsistent: most read like titles
 *  ("Global Elections", "ATP Tour", "Argentina Primera División") but a
 *  handful arrive entirely lowercase ("league of legends", "primary
 *  elections", "baseball") and look like a bug beside their neighbours.
 *
 *  Only the all-lowercase ones are touched. Any label carrying a capital was
 *  cased deliberately, and re-casing it would wreck the acronyms and proper
 *  nouns that make up most of the list — "AI", "ATP", "A100", "US Election"
 *  would come back as "Ai", "Atp", "A100", "Us Election".
 */
export function displayTagLabel(label: string): string {
  if (/[A-Z]/.test(label)) return label;
  return label
    .split(" ")
    .map((word, i) =>
      i > 0 && TITLE_STOPWORDS.has(word)
        ? word
        : word.charAt(0).toUpperCase() + word.slice(1),
    )
    .join(" ");
}
