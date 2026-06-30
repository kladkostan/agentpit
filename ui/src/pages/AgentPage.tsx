import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowDownRight, ArrowUpRight, Minus, Play } from "lucide-react";
import type { Position } from "@/api/portfolio";
import { usePositions } from "@/api/portfolio";
import { useBotStatus, type BotFeedItem, type BotStatus } from "@/api/botStatus";
import {
  resolveAgentIdentity,
  useLeaderboard,
  type AgentIdentity,
} from "@/api/leaderboard";
import { useNowSeconds } from "@/lib/useNowSeconds";
import { Sparkline } from "@/components/Sparkline";
import type { SparklineSample } from "@/lib/chartGeometry";
import { formatClock, formatCountdown } from "@/lib/format";
import { cn } from "@/lib/utils";

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
// Trade sizes range from fractional (0.02 sh) to triple-digit, so keep up to two
// decimals — rounding to whole shares turned a real 0.02-share fill into "0".
const SHARES = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

/** localhost sidecar that fires an immediate OpenClaw run. Override via VITE_BOT_TRIGGER_URL. */
const TRIGGER_URL =
  typeof import.meta.env.VITE_BOT_TRIGGER_URL === "string" &&
  import.meta.env.VITE_BOT_TRIGGER_URL.length > 0
    ? import.meta.env.VITE_BOT_TRIGGER_URL
    : "http://127.0.0.1:8799/run";

const PNL_TONE = (n: number): "up" | "down" | "neutral" =>
  n > 0 ? "up" : n < 0 ? "down" : "neutral";

const pnlText = (n: number) =>
  n > 0
    ? "text-emerald-600 dark:text-emerald-400"
    : n < 0
      ? "text-rose-600 dark:text-rose-400"
      : "text-foreground";

export function AgentPage() {
  const now = useNowSeconds();
  const { agentId } = useParams();
  const { data: leaderboard } = useLeaderboard();
  const { identity, status: idStatus } = resolveAgentIdentity(
    leaderboard,
    agentId,
  );
  const { data: status, error: statusError } = useBotStatus(agentId);
  const { data: openData } = usePositions(identity?.address);

  const open = useMemo(
    () =>
      (openData ?? [])
        .filter((p) => p.size > 0)
        .sort((a, b) => b.currentValue - a.currentValue),
    [openData],
  );

  // Live, on-chain open book — the metric card must agree with the list below
  // it, so both derive from `/positions`, not the bot's (laggy) ledger count.
  const openExposure = useMemo(
    () => open.reduce((sum, p) => sum + p.currentValue, 0),
    [open],
  );

  // Average realized result per closed trade (null until at least one closes).
  const avgTrade =
    status && status.summary.closed_trades > 0
      ? status.summary.realized_pnl / status.summary.closed_trades
      : null;

  // Realized P/L curve, published by the bot (agentpit doesn't track positions the
  // bot sells out of, only ones held to resolution — so this comes from its ledger).
  const pnlPoints = useMemo<SparklineSample[]>(() => {
    const s = status?.pnl_series ?? [];
    return s.length >= 2
      ? s.map((d) => ({ t: d.t, p: d.p }))
      : [
          { t: 0, p: 0 },
          { t: 1, p: 0 },
        ];
  }, [status]);

  const interval = (status?.cycle_interval_minutes ?? 15) * 60;
  const nextAt = status ? status.updated_at + interval : null;
  const secsToNext = nextAt ? nextAt - now : null;
  const sinceUpdate = status ? now - status.updated_at : Infinity;
  // "Live" while the last cycle is within two intervals; otherwise the cron is
  // paused/stalled and we show an honest idle state rather than a fake pulse.
  const isLive = sinceUpdate < interval * 2 + 60;

  if (idStatus === "not-found") {
    return (
      <section className="mx-auto max-w-5xl py-16 text-center">
        <p className="text-sm text-muted-foreground">
          No agent "{agentId}" in the arena.
        </p>
        <Link
          to="/agents"
          className="mt-3 inline-block text-sm text-primary hover:underline"
        >
          ← Back to Agent Arena
        </Link>
      </section>
    );
  }

  return (
    <section className="mx-auto max-w-6xl space-y-6">
      <style>{KEYFRAMES}</style>

      <HeroBanner
        identity={identity}
        status={status}
        isLive={isLive}
        secsToNext={secsToNext}
        hasError={Boolean(statusError) && !status}
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric
          label="Realized profit / loss"
          value={status ? USD.format(status.summary.realized_pnl) : "—"}
          valueClass={status ? pnlText(status.summary.realized_pnl) : ""}
          accent={
            <Sparkline
              points={pnlPoints}
              width={108}
              height={26}
              tone={PNL_TONE(status?.summary.realized_pnl ?? 0)}
              className="opacity-90"
            />
          }
        />
        <Metric
          label="Open positions"
          value={openData ? String(open.length) : "—"}
          sub={openData ? `${USD.format(openExposure)} at risk` : undefined}
        />
        <Metric
          label="Closed trades"
          value={status ? String(status.summary.closed_trades) : "—"}
          sub={
            status
              ? `${status.summary.wins}W · ${status.summary.losses}L`
              : undefined
          }
        />
        <Metric
          label="Avg trade P/L"
          value={avgTrade !== null ? USD.format(avgTrade) : "—"}
          valueClass={avgTrade !== null ? pnlText(avgTrade) : ""}
          sub={
            status ? `across ${status.summary.closed_trades} closed` : undefined
          }
        />
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        <PositionsPanel positions={open} />
        <ActivityFeed feed={status?.feed ?? []} now={now} />
      </div>
    </section>
  );
}

/* ----------------------------------------------------------------- hero --- */

function HeroBanner({
  identity,
  status,
  isLive,
  secsToNext,
  hasError,
}: {
  identity: AgentIdentity | null;
  status: BotStatus | undefined;
  isLive: boolean;
  secsToNext: number | null;
  hasError: boolean;
}) {
  // identity is null only briefly while the leaderboard loads for an arena
  // agent — fall back to neutral placeholders so the hero never flashes empty.
  const emoji = identity?.emoji ?? "🤖";
  const name = identity?.name ?? "…";
  const style = identity?.style ?? "";
  const addr = identity ? shortAddr(identity.address) : "";

  return (
    <div
      className="relative overflow-hidden rounded-2xl border bg-card px-6 py-6 sm:px-8"
      style={{
        backgroundImage:
          "radial-gradient(120% 140% at 100% 0%, hsl(var(--primary) / 0.06), transparent 55%), linear-gradient(hsl(var(--border) / 0.5) 1px, transparent 1px), linear-gradient(90deg, hsl(var(--border) / 0.5) 1px, transparent 1px)",
        backgroundSize: "auto, 34px 34px, 34px 34px",
        backgroundPosition: "center, center, center",
      }}
    >
      <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <div className="grid size-12 shrink-0 place-items-center rounded-xl border bg-background/70 text-2xl shadow-sm">
            {emoji}
          </div>
          <div>
            {identity?.isArena ? (
              <Link
                to="/agents"
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                ← Agent Arena
              </Link>
            ) : null}
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">{name}</h1>
              <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
                paper · demo
              </span>
            </div>
            <p className="font-mono text-xs text-muted-foreground">
              {addr ? `${addr} · ${style}` : style}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4 sm:gap-5">
          <Heartbeat live={isLive} />
          <div className="text-right">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
              {hasError
                ? "Awaiting first cycle"
                : isLive
                  ? "Next cycle"
                  : "Last cycle"}
            </div>
            <div className="font-mono text-lg font-semibold tabular-nums">
              {hasError
                ? "—"
                : isLive && secsToNext !== null
                  ? secsToNext > 0
                    ? `in ${formatCountdown(secsToNext)}`
                    : "running…"
                  : status
                    ? (formatClock(status.updated_at) ?? "—")
                    : "—"}
            </div>
          </div>
          <RunNowButton />
        </div>
      </div>
    </div>
  );
}

function Heartbeat({ live }: { live: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className="relative grid size-3 place-items-center">
        {live && (
          <span className="absolute inline-flex size-3 animate-ping rounded-full bg-emerald-500/70" />
        )}
        <span
          className={cn(
            "relative inline-flex size-2.5 rounded-full",
            live ? "bg-emerald-500" : "bg-amber-500",
          )}
        />
      </span>
      <span
        className={cn(
          "text-xs font-semibold uppercase tracking-widest",
          live
            ? "text-emerald-600 dark:text-emerald-400"
            : "text-amber-600 dark:text-amber-400",
        )}
      >
        {live ? "Live" : "Idle"}
      </span>
    </div>
  );
}

function RunNowButton() {
  const [state, setState] = useState<"idle" | "running" | "error">("idle");

  async function run() {
    if (state === "running") return;
    setState("running");
    try {
      const r = await fetch(TRIGGER_URL, { method: "POST" });
      if (!r.ok && r.status !== 202) throw new Error(String(r.status));
      // A model-driven cycle takes ~1 min; hold the state, then release.
      window.setTimeout(() => setState("idle"), 75_000);
    } catch {
      setState("error");
      window.setTimeout(() => setState("idle"), 4_000);
    }
  }

  return (
    <button
      type="button"
      onClick={run}
      disabled={state === "running"}
      title="Fire one cycle immediately instead of waiting for the 15-minute schedule"
      className={cn(
        "inline-flex shrink-0 items-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-semibold transition-colors",
        state === "running"
          ? "cursor-not-allowed border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
          : state === "error"
            ? "border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-400"
            : "border-primary bg-primary text-primary-foreground hover:opacity-90",
      )}
    >
      {state === "running" ? (
        <>
          <span className="inline-flex size-2 animate-pulse rounded-full bg-emerald-500" />
          Running…
        </>
      ) : state === "error" ? (
        "Trigger offline"
      ) : (
        <>
          <Play className="size-4" fill="currentColor" /> Run cycle now
        </>
      )}
    </button>
  );
}

/* -------------------------------------------------------------- metrics --- */

function Metric({
  label,
  value,
  valueClass,
  sub,
  accent,
}: {
  label: string;
  value: string;
  valueClass?: string | undefined;
  sub?: string | undefined;
  accent?: React.ReactNode | undefined;
}) {
  return (
    <div className="rounded-xl border bg-card px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 flex items-end justify-between gap-2">
        <div
          className={cn(
            "text-2xl font-semibold tabular-nums leading-none",
            valueClass,
          )}
        >
          {value}
        </div>
        {accent}
      </div>
      {sub ? (
        <div className="mt-1.5 text-xs text-muted-foreground tabular-nums">
          {sub}
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------ positions --- */

function PositionsPanel({ positions }: { positions: Position[] }) {
  return (
    <div className="flex flex-col rounded-2xl border bg-card lg:h-[640px]">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide">
          Open positions
        </h2>
        <span className="text-xs text-muted-foreground tabular-nums">
          {positions.length}
        </span>
      </div>
      {positions.length === 0 ? (
        <p className="grid flex-1 place-items-center px-4 py-10 text-center text-sm text-muted-foreground">
          No open positions right now.
        </p>
      ) : (
        <ul className="min-h-0 flex-1 divide-y overflow-auto">
          {positions.map((p) => (
            <li
              key={p.asset}
              className="flex items-center gap-3 px-4 py-2.5"
            >
              <Avatar icon={p.icon} title={p.title} />
              <div className="min-w-0 flex-1">
                <Link
                  to={`/markets/${p.slug}`}
                  className="line-clamp-1 text-sm font-medium hover:underline"
                >
                  {p.title}
                </Link>
                <div className="text-xs tabular-nums text-muted-foreground">
                  {p.outcome} ·{" "}
                  <span title="entry price">{(p.avgPrice * 100).toFixed(1)}¢</span>
                  <span className="px-1 opacity-60">→</span>
                  <span title="current price" className="text-foreground/80">
                    {(p.curPrice * 100).toFixed(1)}¢
                  </span>
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm font-semibold tabular-nums">
                  {USD.format(p.currentValue)}
                </div>
                <div
                  className={cn(
                    "text-xs tabular-nums",
                    pnlText(p.cashPnl),
                  )}
                >
                  {p.cashPnl >= 0 ? "+" : ""}
                  {p.percentPnl.toFixed(1)}%
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* -------------------------------------------------------------- feed ----- */

function ActivityFeed({ feed, now }: { feed: BotFeedItem[]; now: number }) {
  return (
    <div className="flex flex-col rounded-2xl border bg-card lg:h-[640px]">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide">
          Live activity
        </h2>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="inline-flex size-1.5 animate-pulse rounded-full bg-emerald-500" />
          streaming
        </span>
      </div>
      {feed.length === 0 ? (
        <p className="grid flex-1 place-items-center px-4 py-12 text-center text-sm text-muted-foreground">
          The agent's trades and reasoning will appear here as cycles run.
        </p>
      ) : (
        <ul className="min-h-0 flex-1 overflow-auto">
          {feed.map((item, i) => (
            <FeedRow
              key={item.decision_id}
              item={item}
              now={now}
              fresh={i === 0}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function FeedRow({
  item,
  now,
  fresh,
}: {
  item: BotFeedItem;
  now: number;
  fresh: boolean;
}) {
  // Color + arrow reflect the action taken, not the model's lean: a held-off
  // row stays neutral (gray minus) even when the model leaned a direction.
  const up = item.traded && item.direction === "UP";
  const down = item.traded && item.direction === "DOWN";
  const cents = item.recent_move * 100;
  const moveLabel = `${cents >= 0 ? "+" : ""}${cents.toFixed(1)}¢`;
  const tone = up
    ? "text-emerald-600 dark:text-emerald-400"
    : down
      ? "text-rose-600 dark:text-rose-400"
      : "text-muted-foreground";
  const Arrow = up ? ArrowUpRight : down ? ArrowDownRight : Minus;
  const action = item.traded
    ? `${item.side || "BUY"} ${up ? "YES" : down ? "NO" : ""}`.trim()
    : "no trade";

  return (
    <li
      className="flex items-start gap-3 border-b px-4 py-3 last:border-b-0"
      style={{
        animation: "agentRise .45s cubic-bezier(.2,.7,.3,1) both",
      }}
    >
      <div
        className={cn(
          "mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg border",
          up
            ? "border-emerald-500/30 bg-emerald-500/10"
            : down
              ? "border-rose-500/30 bg-rose-500/10"
              : "bg-muted",
        )}
      >
        <Arrow className={cn("size-4", tone)} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="line-clamp-1 text-sm font-medium">{item.title}</span>
          {item.demo ? (
            <span className="shrink-0 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
              momentum
            </span>
          ) : null}
        </div>

        {/* The model's actual reasoning about this market — the heart of the feed. */}
        {item.rationale ? (
          <p className="mt-1 line-clamp-3 text-xs italic leading-relaxed text-muted-foreground">
            “{item.rationale}”
          </p>
        ) : null}

        {/* The news it actually read — clickable, to prove the reasoning is grounded. */}
        {item.sources && item.sources.length > 0 ? (
          <div className="mt-1.5 flex flex-col gap-0.5">
            {item.sources.slice(0, 2).map((src, i) => (
              <a
                key={i}
                href={src.url}
                target="_blank"
                rel="noreferrer"
                className="group inline-flex items-center gap-1.5 text-xs text-sky-700 hover:underline dark:text-sky-400"
                onClick={(e) => e.stopPropagation()}
              >
                <span aria-hidden>📰</span>
                <span className="line-clamp-1">{src.title}</span>
                {src.source ? (
                  <span className="shrink-0 text-muted-foreground">· {src.source}</span>
                ) : null}
              </a>
            ))}
          </div>
        ) : null}

        {/* What it decided + did. */}
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <span
            className={cn(
              "rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
              up
                ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                : down
                  ? "bg-rose-500/10 text-rose-700 dark:text-rose-400"
                  : "bg-muted text-muted-foreground",
            )}
          >
            {action}
          </span>
          {item.traded && item.price != null ? (
            <span className="tabular-nums text-muted-foreground">
              {SHARES.format(item.size ?? 0)} shares @ ${item.price.toFixed(3)}
            </span>
          ) : (
            <span className="text-muted-foreground">held off</span>
          )}
          {Math.abs(cents) >= 0.05 ? (
            <span className={cn("tabular-nums", tone)}>· momentum {moveLabel}</span>
          ) : null}
        </div>
      </div>

      <time className="mt-0.5 shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
        {item.ts ? relativeTime(now - item.ts) : ""}
      </time>
      {fresh ? <span className="sr-only">newest</span> : null}
    </li>
  );
}

/* ------------------------------------------------------------- helpers --- */

function Avatar({ icon, title }: { icon: string; title: string }) {
  if (icon) {
    return (
      <img
        src={icon}
        alt=""
        className="size-8 shrink-0 rounded-lg object-cover"
        loading="lazy"
      />
    );
  }
  return (
    <div className="grid size-8 shrink-0 place-items-center rounded-lg bg-muted text-xs font-semibold text-muted-foreground">
      {title.slice(0, 1).toUpperCase()}
    </div>
  );
}

function shortAddr(a: string): string {
  return a.length < 12 ? a : `${a.slice(0, 6)}…${a.slice(-4)}`;
}

function relativeTime(secsAgo: number): string {
  if (secsAgo < 0) secsAgo = 0;
  if (secsAgo < 60) return `${secsAgo}s`;
  if (secsAgo < 3600) return `${Math.floor(secsAgo / 60)}m`;
  if (secsAgo < 86_400) return `${Math.floor(secsAgo / 3600)}h`;
  return `${Math.floor(secsAgo / 86_400)}d`;
}

const KEYFRAMES = `
@keyframes agentRise {
  from { opacity: 0; transform: translateY(7px); }
  to   { opacity: 1; transform: none; }
}`;
