import { useState } from "react";
import { Link } from "react-router-dom";
import { Sparkline } from "@/components/Sparkline";
import {
  equityPoints,
  lastTrade,
  rankAgents,
  TIME_WINDOWS,
  useLeaderboard,
  windowAgent,
  type RankedAgent,
  type TimeWindowKey,
} from "@/api/leaderboard";
import { useBotStatus } from "@/api/botStatus";
import { useNowSeconds } from "@/lib/useNowSeconds";
import { formatCountdown, formatSignedUsd, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const pnlText = (n: number) =>
  n > 0
    ? "text-emerald-600 dark:text-emerald-400"
    : n < 0
      ? "text-rose-600 dark:text-rose-400"
      : "text-muted-foreground";

const pnlTone = (n: number): "up" | "down" | "neutral" =>
  n > 0 ? "up" : n < 0 ? "down" : "neutral";

export function AgentArenaPage() {
  const now = useNowSeconds();
  const { data, error } = useLeaderboard();
  const [windowKey, setWindowKey] = useState<TimeWindowKey>("all");
  const win =
    TIME_WINDOWS.find((w) => w.key === windowKey) ??
    TIME_WINDOWS[TIME_WINDOWS.length - 1]!;
  const startTs = win.seconds === null ? null : now - win.seconds;
  const agents = data
    ? rankAgents(data.agents.map((a) => windowAgent(a, startTs)))
    : [];

  const interval = (data?.cycle_interval_minutes ?? 15) * 60;
  const sinceUpdate = data ? now - data.updated_at : Infinity;
  const secsToNext = data ? data.updated_at + interval - now : null;
  // "Live" while the last cycle is within two intervals; otherwise the cron is
  // paused/stalled and we show an honest idle state.
  const isLive = sinceUpdate < interval * 2 + 60;

  return (
    <section className="mx-auto max-w-5xl space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <span aria-hidden>🏆</span> Agent Arena
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Five personalities trading the same news signals — ranked by live
            Total P&amp;L.
          </p>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-muted-foreground">
            {data ? `${data.agents.length} agents` : "—"}
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="tabular-nums text-muted-foreground">
            {isLive && secsToNext !== null
              ? secsToNext > 0
                ? `next cycle in ${formatCountdown(secsToNext)}`
                : "running…"
              : "idle"}
          </span>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-semibold",
              isLive
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                : "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
            )}
          >
            <span
              className={cn(
                "inline-flex size-1.5 rounded-full",
                isLive ? "animate-pulse bg-emerald-500" : "bg-amber-500",
              )}
            />
            {isLive ? "live" : "paused"}
          </span>
        </div>
      </header>

      <div
        className="flex w-fit items-center gap-1 rounded-full bg-muted p-1"
        aria-label="Leaderboard time window"
      >
        {TIME_WINDOWS.map((w) => (
          <button
            key={w.key}
            type="button"
            aria-pressed={w.key === windowKey}
            onClick={() => setWindowKey(w.key)}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-semibold transition-colors",
              w.key === windowKey
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {w.label}
          </button>
        ))}
      </div>

      {error && !data ? (
        <div className="rounded-2xl border bg-card px-6 py-12 text-center text-sm text-muted-foreground">
          The leaderboard isn't available yet — it appears after the first cycle.
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border bg-card">
          <div className="hidden grid-cols-[3rem_minmax(0,1fr)_8rem_7rem_4rem] items-center gap-3 border-b px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground sm:grid lg:grid-cols-[3rem_minmax(0,1fr)_minmax(0,16rem)_8rem_7rem_4rem]">
            <span>#</span>
            <span>Agent</span>
            <span className="hidden lg:block">Last Action</span>
            <span className="text-right">Total P&amp;L</span>
            <span className="text-center">Equity</span>
            <span className="text-right">Trades</span>
          </div>
          <ul className="divide-y">
            {agents.length === 0 ? (
              <li className="grid place-items-center px-4 py-12 text-center text-sm text-muted-foreground">
                Loading agents…
              </li>
            ) : (
              agents.map((a) => <AgentRow key={a.id} agent={a} now={now} />)
            )}
          </ul>
        </div>
      )}
    </section>
  );
}

function AgentRow({ agent, now }: { agent: RankedAgent; now: number }) {
  return (
    <li>
      <Link
        to={`/agents/${agent.id}`}
        className="grid grid-cols-[3rem_minmax(0,1fr)_8rem] items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/50 sm:grid-cols-[3rem_minmax(0,1fr)_8rem_7rem_4rem] lg:grid-cols-[3rem_minmax(0,1fr)_minmax(0,16rem)_8rem_7rem_4rem]"
      >
        <span className="text-lg tabular-nums">
          {agent.medal ?? (
            <span className="text-muted-foreground">{agent.rank}</span>
          )}
        </span>
        <span className="flex min-w-0 items-center gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg border bg-background text-xl">
            {agent.emoji}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-semibold">{agent.name}</span>
            <span className="block truncate text-xs text-muted-foreground">
              {agent.style}
            </span>
          </span>
        </span>
        <LastActionCell agentId={agent.id} now={now} />
        <span
          className={cn(
            "text-right text-base font-semibold tabular-nums",
            pnlText(agent.total_pnl),
          )}
        >
          {formatSignedUsd(agent.total_pnl)}
        </span>
        <span className="hidden justify-center sm:flex">
          <Sparkline
            points={equityPoints(agent.equity)}
            width={96}
            height={28}
            tone={pnlTone(agent.total_pnl)}
          />
        </span>
        <span className="hidden text-right text-sm tabular-nums text-muted-foreground sm:block">
          {agent.trades}
        </span>
      </Link>
    </li>
  );
}

/** Latest trade for one agent, off its bot-status feed. Fail-soft by design:
 *  a missing/stale status file or a trade-less feed renders a quiet dash —
 *  one agent's file must never break the whole row. */
function LastActionCell({ agentId, now }: { agentId: string; now: number }) {
  const { data } = useBotStatus(agentId);
  // No status file (still loading, or the bot never wrote one) — we know nothing.
  if (!data) {
    return (
      <span className="hidden text-sm text-muted-foreground lg:block">—</span>
    );
  }
  const trade = lastTrade(data.feed);
  // Status is live but nothing traded: deliberate restraint, not missing data.
  if (!trade) {
    return (
      <span className="hidden min-w-0 lg:block">
        <span className="block text-sm text-muted-foreground">Held back</span>
        <span className="block text-xs text-muted-foreground/70">
          nothing met its bar yet
        </span>
      </span>
    );
  }
  const side =
    trade.direction === "UP" ? "YES" : trade.direction === "DOWN" ? "NO" : null;
  const sideClass =
    trade.direction === "UP"
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-rose-600 dark:text-rose-400";
  return (
    <span className="hidden min-w-0 lg:block">
      {/* The market title is the payload — give it two full lines instead of
          truncating to one (long questions were unreadable). */}
      <span className="line-clamp-2 break-words text-sm leading-snug">
        {trade.title}
      </span>
      <span className="block text-xs text-muted-foreground">
        <span className={cn("font-semibold", side && sideClass)}>
          {side ? `Trade "${side}"` : "Trade"}
        </span>
        <span className="tabular-nums"> · {relativeTime(now - trade.ts)} ago</span>
      </span>
    </span>
  );
}
