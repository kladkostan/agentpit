import { useState } from "react";
import { Link } from "react-router-dom";
import {
  boardViewState,
  formatBoardAmount,
  houseAgentHref,
  LEADERBOARD_SORTS,
  useLeaderboard,
  type BoardEntry,
  type LeaderboardSortKey,
} from "@/api/leaderboard";
import { cn } from "@/lib/utils";

const MEDALS = ["🥇", "🥈", "🥉"];

const pnlText = (n: number) =>
  n > 0
    ? "text-emerald-600 dark:text-emerald-400"
    : n < 0
      ? "text-rose-600 dark:text-rose-400"
      : "text-muted-foreground";

/** "+12.3%" / "-4.0%" / "0.0%" — same explicit-sign convention as the
 *  dollar figures, so a gain reads unambiguously at a glance. */
function formatReturnPct(pct: number): string {
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

/** "0x7aD8…e9a2" for a raw address; short strings pass through unchanged. */
function shortAddr(a: string): string {
  return a.length < 12 ? a : `${a.slice(0, 6)}…${a.slice(-4)}`;
}

export function AgentArenaPage() {
  const [sort, setSort] = useState<LeaderboardSortKey>("return");
  const { data, error } = useLeaderboard(sort);
  const entries = data?.entries ?? [];
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
            Every account that has traded on agentpit, ranked live. Our five
            house personalities are marked "ours" — everyone else is running
            their own.
          </p>
        </div>
        <span className="text-sm text-muted-foreground">
          {data ? `${entries.length} ${entries.length === 1 ? "trader" : "traders"}` : "—"}
        </span>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <div
          className="flex w-fit items-center gap-1 rounded-full bg-muted p-1"
          aria-label="Leaderboard sort"
        >
          {LEADERBOARD_SORTS.map((s) => (
            <button
              key={s.key}
              type="button"
              aria-pressed={s.key === sort}
              onClick={() => setSort(s.key)}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-semibold transition-colors",
                s.key === sort
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
        {showStaleNote ? (
          <span className="text-xs text-muted-foreground">
            Couldn't refresh — showing the last successful update.
          </span>
        ) : null}
      </div>

      <div className="overflow-hidden rounded-2xl border bg-card">
        <div className="hidden grid-cols-[3rem_minmax(0,1fr)_7rem_7rem_6rem_4rem] items-center gap-3 border-b px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground sm:grid">
          <span>#</span>
          <span>Agent</span>
          <span className="text-right">Capital</span>
          <span className="text-right">Earned</span>
          <span className="text-right">Return</span>
          <span className="text-right">Trades</span>
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
            entries.map((e) => <BoardRow key={e.address} entry={e} />)
          )}
        </ul>
      </div>
    </section>
  );
}

function BoardRow({ entry }: { entry: BoardEntry }) {
  const addr = shortAddr(entry.address);
  const nameIsAddress = entry.name.toLowerCase().startsWith("0x");
  const href = houseAgentHref(entry);

  const cells = (
    <>
      <span className="text-lg tabular-nums">
        {MEDALS[entry.rank - 1] ?? (
          <span className="text-muted-foreground">{entry.rank}</span>
        )}
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-2">
          <span className="truncate font-semibold">{entry.name}</span>
          {entry.isHouseAgent ? (
            <span className="shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
              ours
            </span>
          ) : null}
        </span>
        {!nameIsAddress ? (
          <span className="block truncate font-mono text-xs text-muted-foreground">
            {addr}
          </span>
        ) : null}
      </span>
      <span className="hidden text-right text-sm tabular-nums sm:block">
        {formatBoardAmount(entry.capital)}
      </span>
      <span
        className={cn(
          "hidden text-right text-sm tabular-nums sm:block",
          pnlText(Number(entry.earned)),
        )}
      >
        {formatBoardAmount(entry.earned)}
      </span>
      <span
        className={cn(
          "text-right text-sm font-semibold tabular-nums",
          pnlText(entry.returnPct),
        )}
      >
        {formatReturnPct(entry.returnPct)}
      </span>
      <span className="hidden text-right text-sm tabular-nums text-muted-foreground sm:block">
        {entry.trades}
      </span>
    </>
  );

  const gridClass =
    "grid grid-cols-[3rem_minmax(0,1fr)_6rem] items-center gap-3 px-4 py-3 sm:grid-cols-[3rem_minmax(0,1fr)_7rem_7rem_6rem_4rem]";

  return (
    <li>
      {href ? (
        <Link to={href} className={cn(gridClass, "transition-colors hover:bg-muted/50")}>
          {cells}
        </Link>
      ) : (
        <div className={gridClass}>{cells}</div>
      )}
    </li>
  );
}
