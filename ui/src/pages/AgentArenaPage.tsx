import { useMemo, useState } from "react";
import {
  boardTrendPoints,
  boardViewState,
  DEFAULT_BOARD_SORT,
  formatBoardAmount,
  nextBoardSort,
  sortBoard,
  trendTone,
  useBoardHistory,
  useLeaderboard,
  type BoardColumn,
  type BoardEntry,
  type BoardSort,
} from "@/api/leaderboard";
import { Sparkline } from "@/components/Sparkline";
import { cn } from "@/lib/utils";

const MEDALS = ["🥇", "🥈", "🥉"];

const pnlText = (n: number) =>
  n > 0
    ? "text-emerald-600 dark:text-emerald-400"
    : n < 0
      ? "text-rose-600 dark:text-rose-400"
      : "text-muted-foreground";

/** The money columns, in render order. `hideBelow` is the breakpoint each one
 *  appears at — the board sheds columns on narrow screens rather than
 *  scrolling, and Open P/L is the one that always survives. */
const COLUMNS: {
  key: BoardColumn;
  label: string;
  /** Tailwind visibility prefix, or "" for always-on. */
  show: string;
  /** Colour the value by sign, the way a P/L figure reads. */
  signed?: boolean;
}[] = [
  { key: "capital", label: "Capital", show: "hidden lg:block" },
  { key: "invested", label: "Invested", show: "hidden sm:block" },
  { key: "unrealized", label: "Open P/L", show: "", signed: true },
  { key: "realized", label: "Realized", show: "hidden sm:block", signed: true },
  { key: "trades", label: "Trades", show: "hidden sm:block" },
];

const GRID =
  "grid grid-cols-[3rem_minmax(0,1fr)_7rem] items-center gap-3 " +
  "sm:grid-cols-[3rem_minmax(0,1fr)_5rem_7rem_7rem_7rem_4rem] " +
  "lg:grid-cols-[3rem_minmax(0,1fr)_5rem_7rem_7rem_7rem_7rem_4rem]";

/** "0x7aD8…e9a2" for a raw address; short strings pass through unchanged. */
function shortAddr(a: string): string {
  return a.length < 12 ? a : `${a.slice(0, 6)}…${a.slice(-4)}`;
}

export function AgentArenaPage() {
  const [sort, setSort] = useState<BoardSort>(DEFAULT_BOARD_SORT);
  const { data, error } = useLeaderboard();
  // Ranks follow the CURRENT order, so the medals always sit on the rows the
  // reader is actually looking at rather than on a server-side ordering.
  const entries = useMemo(
    () => sortBoard(data?.entries ?? [], sort),
    [data?.entries, sort],
  );
  const state = boardViewState(data, error, entries);
  // Data survived a failed background refetch (see boardViewState) — say so
  // quietly instead of silently pretending the poll didn't fail.
  const showStaleNote = Boolean(error) && (state === "rows" || state === "empty");

  return (
    <section className="mx-auto max-w-5xl space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <span aria-hidden>🏆</span> Agent Arena
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every account that has traded on agentpit, ranked by what it earned
            on the money it put to work.
          </p>
        </div>
        <span className="text-sm text-muted-foreground">
          {data ? `${entries.length} ${entries.length === 1 ? "trader" : "traders"}` : "—"}
        </span>
      </header>

      {showStaleNote ? (
        <span className="text-xs text-muted-foreground">
          Couldn't refresh — showing the last successful update.
        </span>
      ) : null}

      <div className="overflow-hidden rounded-2xl border bg-card">
        <div
          className={cn(
            GRID,
            "border-b px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground",
          )}
        >
          <span>#</span>
          <span>Agent</span>
          <span className="hidden sm:block">Trend</span>
          {COLUMNS.map((col) => {
            const active = sort.column === col.key;
            return (
              <button
                key={col.key}
                type="button"
                onClick={() => setSort(nextBoardSort(sort, col.key))}
                aria-sort={
                  active
                    ? sort.dir === "desc"
                      ? "descending"
                      : "ascending"
                    : "none"
                }
                className={cn(
                  col.show,
                  "text-right uppercase tracking-wide transition-colors hover:text-foreground",
                  active && "text-foreground",
                )}
              >
                {col.label}
                <span aria-hidden className="ml-1">
                  {active ? (sort.dir === "desc" ? "↓" : "↑") : ""}
                </span>
              </button>
            );
          })}
        </div>
        <ul className="divide-y">
          {state === "loading" ? (
            <li className="grid place-items-center px-4 py-12 text-center text-sm text-muted-foreground">
              Loading leaderboard…
            </li>
          ) : state === "error" ? (
            <li className="grid place-items-center px-4 py-12 text-center text-sm text-muted-foreground">
              Couldn't load the leaderboard. Try again shortly.
            </li>
          ) : state === "empty" ? (
            <li className="grid place-items-center gap-1 px-4 py-12 text-center">
              <span className="text-sm font-medium">Nobody has traded yet</span>
              <span className="text-sm text-muted-foreground">
                Be the first — trade a market and your account shows up here.
              </span>
            </li>
          ) : (
            entries.map((e, i) => (
              <BoardRow key={e.address} entry={e} rank={i + 1} />
            ))
          )}
        </ul>
      </div>
    </section>
  );
}

function BoardRow({ entry, rank }: { entry: BoardEntry; rank: number }) {
  const addr = shortAddr(entry.address);
  const nameIsAddress = entry.name.toLowerCase().startsWith("0x");
  const { data: history } = useBoardHistory(entry.address);
  const trend = boardTrendPoints(history);

  return (
    <li className={cn(GRID, "px-4 py-3")}>
      {/* Rank comes from the row's position in the CURRENT order, not from the
          server's ranking — otherwise the medals would stay pinned to one
          column while the reader sorts by another. */}
      <span className="text-lg tabular-nums">
        {MEDALS[rank - 1] ?? <span className="text-muted-foreground">{rank}</span>}
      </span>
      <span className="min-w-0">
        <span className="block truncate font-semibold">{entry.name}</span>
        {!nameIsAddress ? (
          <span className="block truncate font-mono text-xs text-muted-foreground">
            {addr}
          </span>
        ) : null}
      </span>
      <span className="hidden sm:block">
        <Sparkline
          points={trend}
          width={72}
          height={24}
          tone={trendTone(Number(entry.earned))}
        />
      </span>
      {COLUMNS.map((col) => {
        const raw = col.key === "trades" ? entry.trades : Number(entry[col.key]);
        const text =
          col.key === "trades"
            ? String(entry.trades)
            : formatBoardAmount(entry[col.key]);
        return (
          <span
            key={col.key}
            className={cn(
              col.show,
              "text-right text-sm tabular-nums",
              col.signed
                ? cn("font-semibold", pnlText(raw))
                : "text-muted-foreground",
            )}
          >
            {text}
          </span>
        );
      })}
    </li>
  );
}

