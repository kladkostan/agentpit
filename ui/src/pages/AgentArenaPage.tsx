import { Link } from "react-router-dom";
import { Sparkline } from "@/components/Sparkline";
import {
  equityPoints,
  rankAgents,
  useLeaderboard,
  type RankedAgent,
} from "@/api/leaderboard";
import { useNowSeconds } from "@/lib/useNowSeconds";
import { formatCountdown, formatSignedUsd } from "@/lib/format";
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
  const agents = data ? rankAgents(data.agents) : [];

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

      {error && !data ? (
        <div className="rounded-2xl border bg-card px-6 py-12 text-center text-sm text-muted-foreground">
          The leaderboard isn't available yet — it appears after the first cycle.
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border bg-card">
          <div className="hidden grid-cols-[3rem_minmax(0,1fr)_8rem_7rem_4rem] items-center gap-3 border-b px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground sm:grid">
            <span>#</span>
            <span>Agent</span>
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
              agents.map((a) => <AgentRow key={a.id} agent={a} />)
            )}
          </ul>
        </div>
      )}
    </section>
  );
}

function AgentRow({ agent }: { agent: RankedAgent }) {
  return (
    <li>
      <Link
        to={`/agents/${agent.id}`}
        className="grid grid-cols-[3rem_minmax(0,1fr)_8rem] items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/50 sm:grid-cols-[3rem_minmax(0,1fr)_8rem_7rem_4rem]"
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
