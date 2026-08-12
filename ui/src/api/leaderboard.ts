import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { SparklineSample } from "@/lib/chartGeometry";

/** One point of a cumulative-P/L curve. */
interface PnlPoint {
  t: number; // unix seconds (0 = baseline)
  p: number; // cumulative realized P/L in USD
}

/** Pad an equity curve to >= 2 points so a fresh account (single $0 point)
 *  still renders a flat line instead of a lone dot. */
function equityPoints(equity: PnlPoint[]): SparklineSample[] {
  if (equity.length >= 2) return equity.map((d) => ({ t: d.t, p: d.p }));
  const p = equity[0]?.p ?? 0;
  return [
    { t: 0, p },
    { t: 1, p },
  ];
}

/** One row of `GET /leaderboard` — every account that has traded. */
export interface BoardEntry {
  rank: number;
  name: string;
  address: string;
  capital: string;
  earned: string;
  /** Cost basis of the open positions — what the agent put to work. */
  invested: string;
  /** Mark-to-market gain on those positions — profit only on paper. */
  unrealized: string;
  /** Profit actually banked: total minus whatever is still riding. */
  realized: string;
  returnPct: number;
  trades: number;
}

export interface BoardResponse {
  sort: string;
  entries: BoardEntry[];
}

/** A sortable board column. Sorting is client-side: `/leaderboard` returns
 *  every account in one payload, so re-ordering needs no round trip and can
 *  cover columns the API has no sort key for. */
export type BoardColumn =
  | "capital"
  | "invested"
  | "unrealized"
  | "realized"
  | "trades";

export interface BoardSort {
  column: BoardColumn;
  dir: "desc" | "asc";
}

/** The board's opening order: biggest paper gain first. */
export const DEFAULT_BOARD_SORT: BoardSort = {
  column: "unrealized",
  dir: "desc",
};

function columnValue(entry: BoardEntry, column: BoardColumn): number {
  if (column === "trades") return entry.trades;
  return Number(entry[column]);
}

/** Clicking a column sorts by it, biggest first; clicking the SAME column
 *  again flips the direction. Starting descending is the useful default —
 *  nobody opens a leaderboard to see who is last. */
export function nextBoardSort(
  current: BoardSort,
  column: BoardColumn,
): BoardSort {
  if (current.column !== column) return { column, dir: "desc" };
  return { column, dir: current.dir === "desc" ? "asc" : "desc" };
}

/** A new array, ordered by `sort`. Ties break on address so the rows keep a
 *  fixed order across polls instead of swapping places on every refetch. */
export function sortBoard(
  entries: ReadonlyArray<BoardEntry>,
  sort: BoardSort,
): BoardEntry[] {
  const sign = sort.dir === "desc" ? -1 : 1;
  return [...entries].sort((a, b) => {
    const av = columnValue(a, sort.column);
    const bv = columnValue(b, sort.column);
    if (av !== bv) return sign * (av - bv);
    return a.address.localeCompare(b.address);
  });
}

const BOARD_USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Base-unit integer string (6 decimals) to dollars. */
export function formatBoardAmount(raw: string): string {
  return BOARD_USD.format(Number(raw) / 1e6);
}

export function useLeaderboard() {
  return useQuery({
    // One fetch, whatever the column: the response carries every account, and
    // the board re-orders it locally. Sorting no longer costs a round trip.
    queryKey: ["leaderboard"],
    queryFn: () => apiFetch<BoardResponse>("/leaderboard?sort=earned"),
    refetchInterval: 30_000,
    placeholderData: keepPreviousData,
  });
}

export type BoardViewState = "loading" | "error" | "empty" | "rows";

/** Decide what the board's list body shows. TanStack Query keeps the last
 *  successful `data` around across a failed background refetch — `error` and
 *  `data` can both be set at once, e.g. a transient poll failure mid-redeploy.
 *  A board that is still good must keep rendering, not flip to an error
 *  screen; the error state is only for a *first* load that has nothing to
 *  show yet. */
export function boardViewState(
  data: BoardResponse | undefined,
  error: unknown,
  entries: BoardEntry[],
): BoardViewState {
  if (data) return entries.length === 0 ? "empty" : "rows";
  return error ? "error" : "loading";
}

/** One point of `GET /leaderboard/{address}/history`. Amounts are base-unit
 *  integer strings; `returnPct` is already a percentage. */
export interface BoardHistoryPoint {
  t: number;
  capital: string;
  earned: string;
  returnPct: number;
}

export interface BoardHistory {
  points: BoardHistoryPoint[];
}

/** One account's equity curve. Polled at half the board's rate: a new point
 *  only exists once the valuation pass has run (every five minutes), so
 *  fetching faster would re-download the same curve per row per poll. */
export function useBoardHistory(address: string) {
  return useQuery({
    queryKey: ["leaderboard-history", address],
    queryFn: () =>
      apiFetch<BoardHistory>(
        `/leaderboard/${encodeURIComponent(address)}/history`,
      ),
    refetchInterval: 60_000,
    staleTime: 55_000,
    retry: false,
  });
}

/** History to sparkline samples, plotting **earned** rather than capital —
 *  the figure the board ranks on by default, so the curve and the Earned
 *  column beside it tell the same story. Capital would be a flat line at
 *  \$100k with the whole story buried in its last two digits.
 *
 *  `equityPoints` pads a single point to two so a fresh account renders a flat
 *  line instead of a lone dot. */
export function boardTrendPoints(
  history: BoardHistory | undefined,
): SparklineSample[] {
  if (!history || history.points.length === 0) return [];
  return equityPoints(
    history.points.map((d) => ({ t: d.t, p: Number(d.earned) })),
  );
}

/** Same sign convention as the Return column's colour. */
export function trendTone(pct: number): "up" | "down" | "neutral" {
  return pct > 0 ? "up" : pct < 0 ? "down" : "neutral";
}

/** Case-insensitive address match. Addresses arrive checksummed from the
 *  board and can be stored either way on the session, so comparing raw
 *  strings silently fails to find the reader on their own leaderboard. */
export function isSameAddress(a: string | undefined, b: string | undefined): boolean {
  if (!a || !b) return false;
  return a.toLowerCase() === b.toLowerCase();
}

/** The reader's 1-based position in `entries` as currently ordered, or null
 *  when they are signed out or have never traded. Derived from the array
 *  rather than from `entry.rank`, so it follows whatever column the board is
 *  sorted by instead of the server's ordering. */
export function findMyRank(
  entries: ReadonlyArray<BoardEntry>,
  address: string | undefined,
): number | null {
  if (!address) return null;
  const i = entries.findIndex((e) => isSameAddress(e.address, address));
  return i === -1 ? null : i + 1;
}
