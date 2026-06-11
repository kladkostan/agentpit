import type { Market, MarketState } from "@/types/market";

/** States a window can no longer be traded in. */
const ENDED_STATES: ReadonlySet<MarketState> = new Set([
  "RESOLVED",
  "CANCELLED",
  "CLOSED",
]);

/** Cadence ceiling: 5m/15m/4h series all fall under this. Anything coarser is
 *  treated as a normal event, not a rotating series. */
const MAX_INTERVAL_SECONDS = 4 * 3600 + 60;

export interface RotatingSeries {
  /** The window to trade right now: the one whose [close − interval, close)
   *  contains `now`, else the soonest-closing tradeable window. Null only if
   *  every window has ended. */
  live: Market | null;
  /** Tradeable windows after the live one, soonest-closing first. */
  upcoming: Market[];
  /** Ended (closed/resolved) windows, most-recent-first. */
  past: Market[];
  /** Cadence in seconds (the base spacing between window closes), so callers
   *  can render each window's open as `close − interval`. */
  interval: number;
}

/**
 * Detect a "rotating series" — an event whose markets are regularly-spaced time
 * windows (e.g. *BTC Up or Down 5m*, closing every 5 minutes), as opposed to a
 * normal multi-outcome event whose markets all share one close (e.g. a World
 * Cup winner, where all outcomes resolve at the tournament's end).
 *
 * Detection keys on `end_date` (the window close), NOT `start_date`: upstream
 * lists each window ~24h ahead, so every window's `start_date` is roughly its
 * listing time and they all overlap. The real signal is distinct, regularly
 * spaced closes.
 *
 * The signature: ≥2 markets, distinct end_dates, and consecutive closes that
 * are clean integer multiples of a short base interval (missing windows
 * allowed). Returns the live/upcoming/past split + the interval, or `null` when
 * the event is not a rotating series (caller falls back to the leaderboard).
 *
 * `nowSec` is unix seconds — pass it in so the function stays pure/testable.
 */
export function detectRotatingSeries(
  markets: readonly Market[],
  nowSec: number,
): RotatingSeries | null {
  if (markets.length < 2) return null;
  if (!markets.every((m) => m.end_date != null)) return null;

  const sorted = [...markets].sort(
    (a, b) => (a.end_date as number) - (b.end_date as number),
  );
  const ends = sorted.map((m) => m.end_date as number);

  // Shared-window events (all the same close) are not rotating series.
  if (new Set(ends).size < 2) return null;

  // Base cadence = smallest positive gap between consecutive closes.
  let interval = Infinity;
  for (let i = 1; i < ends.length; i++) {
    const gap = ends[i]! - ends[i - 1]!;
    if (gap > 0 && gap < interval) interval = gap;
  }
  if (!Number.isFinite(interval) || interval <= 0) return null;
  if (interval > MAX_INTERVAL_SECONDS) return null;

  // Every gap must be a clean multiple of the base interval (regular cadence,
  // tolerating missing windows). A ragged gap means it's not a rotating series.
  for (let i = 1; i < ends.length; i++) {
    const gap = ends[i]! - ends[i - 1]!;
    if (gap === 0) return null;
    const k = gap / interval;
    if (Math.abs(k - Math.round(k)) > 0.05) return null;
  }

  const past: Market[] = [];
  const tradeable: Market[] = [];
  for (const m of sorted) {
    if ((m.end_date as number) <= nowSec || ENDED_STATES.has(m.market_state)) {
      past.push(m);
    } else {
      tradeable.push(m);
    }
  }

  // Live = the window whose [close − interval, close) contains `now` (soonest
  // close if several), else the soonest-closing tradeable window.
  const containing = tradeable
    .filter(
      (m) =>
        (m.end_date as number) - interval <= nowSec &&
        nowSec < (m.end_date as number),
    )
    .sort((a, b) => (a.end_date as number) - (b.end_date as number));
  const live =
    containing[0] ??
    tradeable
      .slice()
      .sort((a, b) => (a.end_date as number) - (b.end_date as number))[0] ??
    null;

  const upcoming = tradeable
    .filter((m) => m !== live)
    .sort((a, b) => (a.end_date as number) - (b.end_date as number));

  // `past` is close-ascending; reverse for most-recent-first history.
  const pastDesc = past.slice().reverse();

  return { live, upcoming, past: pastDesc, interval };
}
