import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  Copy,
  Search,
  XCircle,
} from "lucide-react";
import type { Position } from "@/api/portfolio";
import {
  usePositions,
  useClosedPositions,
  useUsdcBalance,
  useCredits,
  useTopUp,
  useTopUpStatus,
  topUpButtonState,
  claimPositionRequest,
} from "@/api/portfolio";
import { ApiError } from "@/api/client";
import {
  describeActivity,
  marketHref,
  useActivity,
  type ActivityEntry,
} from "@/api/activity";
import { useAuth } from "@/auth/useAuth";
import { Sparkline } from "@/components/Sparkline";
import { getAvatarStyle } from "@/lib/avatarColor";
import {
  formatCredits,
  formatCreditsExact,
  formatPnlPct,
  formatVolume,
  shortAddress,
} from "@/lib/format";
import {
  effectivePositionFilter,
  positionBucket,
  unclaimedTotal,
} from "@/lib/positionBuckets";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@mui/material";

type ProfileTab = "positions" | "activity";
type PositionFilter = "active" | "unclaimed" | "closed";

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const SHARES = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

const DATE = new Intl.DateTimeFormat("en-US", {
  month: "short",
  year: "numeric",
});

const PNL_WINDOWS = {
  "1D": { days: 1, label: "Past Day" },
  "1W": { days: 7, label: "Past Week" },
  "1M": { days: 30, label: "Past Month" },
  "1Y": { days: 365, label: "Past Year" },
} as const;
type PnlWindow = keyof typeof PNL_WINDOWS;

function displayName(email: string, handle: string | null): string {
  if (handle && handle.trim().length > 0) return handle;
  const [prefix] = email.split("@");
  return prefix ?? "user";
}

export function ProfilePage() {
  const [tab, setTab] = useState<ProfileTab>("positions");
  const [positionFilter, setPositionFilter] =
    useState<PositionFilter>("active");
  const [search, setSearch] = useState("");
  const [pnlWindow, setPnlWindow] = useState<PnlWindow>("1D");
  const { user, isLoading: authLoading } = useAuth();
  const {
    data: positionsData,
    isLoading: positionsLoading,
    error: positionsError,
  } = usePositions(user?.eth_address);
  const { data: closedData } = useClosedPositions(user?.eth_address);
  const { data: activityData } = useActivity(user?.eth_address);
  const { data: balance } = useUsdcBalance(Boolean(user));
  const { data: credits } = useCredits(Boolean(user));
  const { data: topUpStatus } = useTopUpStatus(Boolean(user));
  const topUp = useTopUp();
  const avatarStyle = getAvatarStyle(user?.eth_address || user?.email);
  const now = Math.floor(Date.now() / 1000);
  const topUpState = topUpButtonState(topUpStatus, topUp.isPending, now);

  const isLoading = positionsLoading;
  const error = positionsError;

  const positions = useMemo(() => {
    if (!positionsData) return [];
    return [...positionsData]
      .filter((p) => p.size > 0)
      .sort((a, b) => b.size - a.size);
  }, [positionsData]);

  const closedPositions = useMemo(() => {
    if (!closedData) return [];
    return [...closedData].sort((a, b) => b.currentValue - a.currentValue);
  }, [closedData]);

  // What the account has won but not yet claimed, across all open positions
  // (not just the ones the current filter/search happens to be showing).
  const unclaimed = useMemo(() => unclaimedTotal(positions), [positions]);

  // Claiming the last unclaimed position can drop `unclaimed` to zero while
  // `positionFilter` is still "unclaimed" — derived, not synced with an
  // effect, so there's no extra render and no window where the two disagree.
  const effectiveFilter = effectivePositionFilter(positionFilter, unclaimed);

  const filteredPositions = useMemo(() => {
    const base =
      effectiveFilter === "closed"
        ? closedPositions
        : positions.filter((p) => positionBucket(p) === effectiveFilter);
    const q = search.trim().toLowerCase();
    if (!q) return base;
    return base.filter((p) => {
      const hay = `${p.title} ${p.outcome}`.toLowerCase();
      return hay.includes(q);
    });
  }, [positions, closedPositions, effectiveFilter, search]);

  // Biggest realized profit across closed (resolved) positions.
  const biggestWin = useMemo(() => {
    const wins = closedPositions
      .map((p) => p.cashPnl)
      .filter((pnl) => pnl > 0);
    return wins.length ? Math.max(...wins) : null;
  }, [closedPositions]);

  // Distinct markets the user has ever held a position in (active + closed).
  const predictionCount = useMemo(() => {
    const ids = new Set<string>();
    for (const p of positions) ids.add(p.conditionId);
    for (const p of closedPositions) ids.add(p.conditionId);
    return ids.size;
  }, [positions, closedPositions]);

  // Current value of open positions (not the apUSD wallet balance).
  const positionsValue = useMemo(
    () => positions.reduce((sum, p) => sum + p.currentValue, 0),
    [positions],
  );

  // Cumulative realized P/L over the selected window, from closed positions by
  // their resolution time. (Open-position unrealized P/L isn't a time series.)
  const pnl = useMemo(() => {
    const cutoff = Date.now() / 1000 - PNL_WINDOWS[pnlWindow].days * 86_400;
    const events = closedPositions
      .map((p) => ({ t: Number(p.endDate) || 0, pnl: p.cashPnl }))
      .filter((e) => e.t >= cutoff)
      .sort((a, b) => a.t - b.t);
    const points: { t: number; p: number }[] = [];
    if (events.length === 0) return { total: 0, points };
    points.push({ t: cutoff, p: 0 });
    let cum = 0;
    for (const e of events) {
      cum += e.pnl;
      points.push({ t: e.t, p: cum });
    }
    return { total: cum, points };
  }, [closedPositions, pnlWindow]);

  if (authLoading) {
    return (
      <section className="mx-auto max-w-5xl space-y-6">
        <h1 className="text-3xl font-semibold tracking-tight">Profile</h1>
        <ProfileSkeleton />
      </section>
    );
  }
  if (!user) return <Navigate to="/" replace />;

  return (
    <section className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-3xl font-semibold tracking-tight">Profile</h1>
      <div className="grid gap-3 lg:grid-cols-3">
        <Card className="h-full rounded-2xl border-border/80 lg:col-span-2">
          <CardContent className="flex h-full flex-col justify-between p-6">
            <div className="flex min-w-0 items-center gap-3">
              <div
                className="flex size-14 shrink-0 items-center justify-center rounded-full text-lg font-semibold text-white"
                style={avatarStyle}
              >
                {displayName(user.email, user.handle).slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0">
                {/* The handle leads: it is the name this account carries on the
                    public board, and the one a person would say out loud. The
                    address stays directly beneath because it is what the
                    account actually IS -- set in mono so the two read as
                    different kinds of thing rather than as a heading and a
                    subheading. */}
                <h2 className="truncate text-xl font-semibold leading-tight tracking-tight">
                  {displayName(user.email, user.handle)}
                </h2>
                <CopyAddress address={user.eth_address} />
                <p className="mt-1.5 text-xs text-muted-foreground">
                  Joined {DATE.format(new Date(user.created_at * 1000))}
                </p>
              </div>
            </div>
            <div className="mt-6 grid grid-cols-2 divide-x divide-y rounded-lg border bg-muted/20 sm:grid-cols-5 sm:divide-y-0">
              <TopMetric
                label="apUSD"
                value={balance != null ? formatVolume(balance) : "—"}
                tooltip={balance != null ? USD.format(balance) : undefined}
              />
              <TopMetric
                label="Credits"
                value={credits != null ? formatCredits(credits) : "—"}
                tooltip={credits != null ? formatCreditsExact(credits) : undefined}
              />
              <TopMetric
                label="Positions"
                value={formatVolume(positionsValue)}
                tooltip={USD.format(positionsValue)}
              />
              <TopMetric
                label="Biggest Win"
                value={biggestWin !== null ? USD.format(biggestWin) : "-"}
              />
              <TopMetric
                label="Predictions"
                value={predictionCount.toString()}
              />
            </div>
            {/* Outside the stat grid on purpose: a quarter-width cell cannot
                hold "Available in 24h" without the button spilling past the
                divider, and shrinking the label to fit would hide the one
                thing it has to say. */}
            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="min-w-0 text-xs text-muted-foreground">
                Paper balance, restored to $100k once a day.
              </p>
              <Button
                size="sm"
                variant="outline"
                className="shrink-0"
                disabled={topUpState.disabled}
                onClick={() => topUp.mutate()}
              >
                {topUpState.label}
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="h-full rounded-2xl border-border/80">
          <CardContent className="flex h-full flex-col justify-between p-6">
            <div>
              <div className="flex items-center justify-between">
                <p className="text-sm text-muted-foreground">Profit/Loss</p>
                <div className="flex items-center gap-1 text-xs">
                  {(Object.keys(PNL_WINDOWS) as PnlWindow[]).map((key) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setPnlWindow(key)}
                      className={[
                        "rounded-md px-2 py-1 font-medium transition-colors",
                        key === pnlWindow
                          ? "bg-primary text-primary-foreground"
                          : "text-muted-foreground hover:text-foreground",
                      ].join(" ")}
                    >
                      {key}
                    </button>
                  ))}
                </div>
              </div>
              <p
                className={[
                  "mt-2 text-2xl font-semibold leading-none tracking-tight tabular-nums",
                  pnl.total > 0
                    ? "text-emerald-600 dark:text-emerald-400"
                    : pnl.total < 0
                      ? "text-rose-600 dark:text-rose-400"
                      : "",
                ].join(" ")}
              >
                {pnl.total >= 0 ? "+" : "−"}
                {USD.format(Math.abs(pnl.total))}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {PNL_WINDOWS[pnlWindow].label}
              </p>
            </div>
            <Sparkline
              points={pnl.points}
              width={460}
              height={56}
              tone={pnl.total >= 0 ? "up" : "down"}
              className="mt-6 h-14 w-full"
            />
          </CardContent>
        </Card>
      </div>

      {isLoading ? (
        <ProfileSkeleton />
      ) : error ? (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-destructive">
              <AlertCircle className="size-5" />
              Failed to load profile data
            </CardTitle>
            <CardDescription>
              {error instanceof Error ? error.message : "Unknown error"}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="rounded-xl border bg-card">
          <div className="flex items-center gap-6 border-b px-4 pb-0 pt-3">
            <button
              type="button"
              onClick={() => setTab("positions")}
              className={[
                "border-b-2 px-0 pb-3 text-xl font-semibold leading-none transition-colors",
                tab === "positions"
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              ].join(" ")}
            >
              Positions
            </button>
            <button
              type="button"
              onClick={() => setTab("activity")}
              className={[
                "border-b-2 px-0 pb-3 text-xl font-semibold leading-none transition-colors",
                tab === "activity"
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              ].join(" ")}
            >
              Activity
            </button>
          </div>

          {tab === "positions" ? (
            <PositionList
              positions={filteredPositions}
              positionFilter={effectiveFilter}
              onPositionFilterChange={setPositionFilter}
              search={search}
              onSearchChange={setSearch}
              unclaimed={unclaimed}
              userAddress={user.eth_address}
            />
          ) : (
            <ActivityList entries={activityData ?? []} />
          )}
        </div>
      )}
    </section>
  );
}

function TopMetric({
  label,
  value,
  tooltip,
  action,
}: {
  label: string;
  value: string;
  tooltip?: string | undefined;
  action?: ReactNode;
}) {
  // Truncate in CSS, not by counting characters: "$30,000.00" is only 10
  // characters and still overflows a quarter-width cell, which used to spill
  // the value across the divider into the next stat. `min-w-0` is what lets a
  // grid child shrink below its content at all.
  return (
    <div className="flex min-w-0 flex-col p-3">
      {tooltip ? (
        <Tooltip title={tooltip} arrow>
          <p className="cursor-help truncate text-xl font-bold leading-none tracking-tight">
            {value}
          </p>
        </Tooltip>
      ) : (
        <p
          className="truncate text-xl font-bold leading-none tracking-tight"
          title={value}
        >
          {value}
        </p>
      )}
      <p className="mt-1 truncate text-sm font-medium text-muted-foreground">
        {label}
      </p>
      {action ? <div className="mt-auto pt-2">{action}</div> : null}
    </div>
  );
}

function PositionList({
  positions,
  positionFilter,
  onPositionFilterChange,
  search,
  onSearchChange,
  unclaimed,
  userAddress,
}: {
  positions: Position[];
  positionFilter: PositionFilter;
  onPositionFilterChange: (next: PositionFilter) => void;
  search: string;
  onSearchChange: (next: string) => void;
  unclaimed: number;
  userAddress: string;
}) {
  const isClosed = positionFilter === "closed";
  const isUnclaimed = positionFilter === "unclaimed";

  const filterBtn = (key: PositionFilter, label: string) => (
    <button
      type="button"
      onClick={() => onPositionFilterChange(key)}
      className={[
        "rounded-md border px-4 py-2 text-sm font-medium transition-colors",
        positionFilter === key
          ? "border-foreground bg-foreground text-background"
          : "border-border bg-background text-foreground hover:bg-muted",
      ].join(" ")}
    >
      {label}
    </button>
  );

  return (
    <div>
      <div className="flex flex-col gap-2 border-b p-3 sm:flex-row sm:items-center">
        <div className="flex items-center gap-2">
          {filterBtn("active", "Active")}
          {unclaimed > 0
            ? filterBtn("unclaimed", `Unclaimed · ${USD.format(unclaimed)}`)
            : null}
          {filterBtn("closed", "Closed")}
        </div>
        <div className="relative sm:ml-auto sm:w-[360px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search positions"
            className="pl-9"
          />
        </div>
      </div>

      {positions.length === 0 ? (
        <p className="px-4 py-16 text-center text-muted-foreground">
          No positions found
        </p>
      ) : (
        <div className="divide-y">
          {positions.map((position) => {
            const won = position.currentValue > 0;
            const pnlUp = position.cashPnl >= 0;
            const pnlColor = pnlUp
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-rose-600 dark:text-rose-400";
            return (
              <div
                key={position.asset}
                className="flex items-center gap-3 px-4 py-4 hover:bg-muted/20"
              >
                {isClosed ? (
                  <span
                    className={`flex w-16 shrink-0 items-center gap-1.5 text-sm font-medium ${
                      won
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-rose-600 dark:text-rose-400"
                    }`}
                  >
                    {won ? (
                      <CheckCircle2 className="size-4" />
                    ) : (
                      <XCircle className="size-4" />
                    )}
                    {won ? "Won" : "Lost"}
                  </span>
                ) : null}
                {position.icon ? (
                  <img
                    src={position.icon}
                    alt=""
                    className="size-9 shrink-0 rounded-md object-cover"
                  />
                ) : (
                  <div className="size-9 shrink-0 rounded-md bg-muted" />
                )}
                <div className="min-w-0 flex-1">
                  <Link
                    to={marketHref(position)}
                    className="line-clamp-1 font-medium hover:underline"
                  >
                    {position.title}
                  </Link>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {SHARES.format(position.size)} {position.outcome} at{" "}
                    {Math.round(position.avgPrice * 100)}¢
                  </p>
                </div>
                <div className="hidden w-28 shrink-0 text-right sm:block">
                  <p className="font-medium tabular-nums">
                    {USD.format(position.initialValue)}
                  </p>
                  <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
                    cost
                  </p>
                </div>
                <div className="w-36 shrink-0 text-right">
                  <p className="font-semibold tabular-nums">
                    {USD.format(position.currentValue)}
                  </p>
                  <p className={`text-xs tabular-nums ${pnlColor}`}>
                    {pnlUp ? "+" : "−"}
                    {USD.format(Math.abs(position.cashPnl))} (
                    {formatPnlPct(position.percentPnl)}%)
                  </p>
                </div>
                {isUnclaimed ? (
                  <ClaimButton
                    conditionId={position.conditionId}
                    userAddress={userAddress}
                  />
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Collects a won-but-unclaimed position. The row itself carries the
 *  `conditionId` — never a market id — which is why `/positions/claim`
 *  resolves it rather than taking one directly. */
function ClaimButton({
  conditionId,
  userAddress,
}: {
  conditionId: string;
  userAddress: string;
}) {
  const queryClient = useQueryClient();
  const claim = useMutation({
    mutationFn: () => claimPositionRequest(conditionId),
    onSuccess: () => {
      toast.success("Claimed.");
      void queryClient.invalidateQueries({
        queryKey: ["positions", userAddress],
      });
      // Claiming pays out apUSD and spends native gas -- both balances at the
      // top of the page change. Without this they sit stale until whatever
      // next natural refetch happens to invalidate them.
      void queryClient.invalidateQueries({
        queryKey: ["balance-allowance", "COLLATERAL"],
      });
      void queryClient.invalidateQueries({ queryKey: ["credits"] });
    },
    onError: (err) => {
      const message =
        err instanceof ApiError ? err.message : "Failed to claim.";
      toast.error(message);
    },
  });

  return (
    <Button
      size="sm"
      variant="outline"
      className="shrink-0"
      disabled={claim.isPending}
      onClick={() => claim.mutate()}
    >
      {claim.isPending ? "Claiming…" : "Claim"}
    </Button>
  );
}

function ActivityList({ entries }: { entries: ActivityEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="p-10 text-center">
        <p className="text-base font-medium">No activity yet</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Your buys and sells will show up here.
        </p>
      </div>
    );
  }

  return (
    <div className="divide-y">
      {entries.slice(0, 8).map((entry, i) => (
        <div
          // The feed has no id of its own, and one account can fill the same
          // market twice in a second, so the index disambiguates.
          key={`activity-${entry.timestamp}-${entry.conditionId}-${i}`}
          className="flex items-center justify-between gap-4 p-4"
        >
          <div className="min-w-0">
            <p className="text-sm font-medium">
              {describeActivity(entry)}
              {entry.outcome ? ` ${entry.outcome}` : ""}
              {entry.price > 0 ? (
                <span className="text-muted-foreground">
                  {" "}
                  at {Math.round(entry.price * 100)}¢
                </span>
              ) : null}
            </p>
            <Link
              to={marketHref(entry)}
              className="mt-1 block truncate text-xs text-muted-foreground hover:underline"
            >
              {entry.title}
            </Link>
          </div>
          <div className="shrink-0 text-right">
            <p className="text-sm tabular-nums">
              {SHARES.format(entry.size)} shares
            </p>
            <p className="mt-0.5 text-xs tabular-nums text-muted-foreground">
              {USD.format(entry.usdcSize)}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

/** The address, short enough to sit on one line, and one click from the
 *  clipboard. It is the account's real identity -- worth handing to someone --
 *  and 42 characters of `break-all` made a card about a person read as a hash.
 *
 *  The label never changes on success, only the icon: swapping the text would
 *  shift the line under the reader's cursor, and the live region carries the
 *  confirmation for anyone not watching the icon. */
function CopyAddress({ address }: { address: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(address);
    } catch {
      // Clipboard blocked (insecure origin, denied permission). Say nothing
      // rather than claiming a copy that did not happen.
      return;
    }
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1500);
  }

  return (
    <>
      <button
        type="button"
        onClick={() => void copy()}
        title={address}
        aria-label={`Copy address ${address}`}
        className="mt-1 flex items-center gap-1.5 rounded font-mono text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        {shortAddress(address)}
        {copied ? (
          <Check className="size-3 text-emerald-500" aria-hidden />
        ) : (
          <Copy className="size-3 opacity-60" aria-hidden />
        )}
      </button>
      <span aria-live="polite" className="sr-only">
        {copied ? "Address copied" : ""}
      </span>
    </>
  );
}

function ProfileSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
      <Skeleton className="h-72 w-full" />
    </div>
  );
}
