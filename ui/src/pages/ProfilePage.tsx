import { useMemo, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { AlertCircle, CheckCircle2, Search, XCircle } from "lucide-react";
import type { Position } from "@/api/portfolio";
import { usePositions, useClosedPositions } from "@/api/portfolio";
import { useAuth } from "@/auth/useAuth";
import { getAvatarStyle } from "@/lib/avatarColor";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@mui/material";

type ProfileTab = "positions" | "activity";
type PositionFilter = "active" | "closed";

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

function shortAddress(address: string): string {
  if (address.length < 12) return address;
  return `${address.slice(0, 6)}...${address.slice(-4)}`;
}

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
  const { user, isLoading: authLoading } = useAuth();
  const {
    data: positionsData,
    isLoading: positionsLoading,
    error: positionsError,
  } = usePositions(user?.eth_address);
  const { data: closedData } = useClosedPositions(user?.eth_address);
  const avatarStyle = getAvatarStyle(user?.eth_address || user?.email);

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

  const filteredPositions = useMemo(() => {
    const base = positionFilter === "closed" ? closedPositions : positions;
    const q = search.trim().toLowerCase();
    if (!q) return base;
    return base.filter((p) => {
      const hay = `${p.title} ${p.outcome}`.toLowerCase();
      return hay.includes(q);
    });
  }, [positions, closedPositions, positionFilter, search]);

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
      <div className="grid gap-3 lg:grid-cols-2">
        <Card className="h-full rounded-2xl border-border/80">
          <CardContent className="flex h-full flex-col justify-between p-6">
            <div className="flex min-w-0 items-center gap-3">
              <div
                className="flex size-14 shrink-0 items-center justify-center rounded-full text-lg font-semibold text-white"
                style={avatarStyle}
              >
                {displayName(user.email, user.handle).slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0">
                <Tooltip title={user.eth_address} arrow>
                  <h2 className="cursor-help truncate text-2xl font-semibold leading-none tracking-tight">
                    {shortAddress(user.eth_address)}
                  </h2>
                </Tooltip>
                <p className="mt-2 text-sm text-muted-foreground">
                  Joined {DATE.format(new Date(user.created_at * 1000))} • 0
                  views
                </p>
              </div>
            </div>
            <div className="mt-6 grid grid-cols-3 divide-x rounded-lg border bg-muted/20">
              <TopMetric
                label="Positions Value"
                value={USD.format(positionsValue)}
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
          </CardContent>
        </Card>

        <Card className="h-full rounded-2xl border-border/80">
          <CardContent className="flex h-full flex-col justify-between p-6">
            <div>
              <div className="flex items-center justify-between">
                <p className="text-sm text-muted-foreground">Profit/Loss</p>
                <div className="flex items-center gap-1 text-xs">
                  {[
                    { key: "1D", active: true },
                    { key: "1W", active: false },
                    { key: "1M", active: false },
                    { key: "1Y", active: false },
                  ].map((item) => (
                    <span
                      key={item.key}
                      className={[
                        "rounded-md px-2 py-1 font-medium",
                        item.active
                          ? "bg-primary text-primary-foreground"
                          : "text-muted-foreground",
                      ].join(" ")}
                    >
                      {item.key}
                    </span>
                  ))}
                </div>
              </div>
              <p className="mt-2 text-2xl font-semibold leading-none tracking-tight">
                $0.00
              </p>
              <p className="mt-1 text-sm text-muted-foreground">Past Day</p>
            </div>
            <div className="mt-6 h-14 rounded-md bg-gradient-to-t from-blue-100 via-blue-50 to-transparent dark:from-blue-950 dark:via-slate-900 dark:to-transparent" />
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
              positionFilter={positionFilter}
              onPositionFilterChange={setPositionFilter}
              search={search}
              onSearchChange={setSearch}
            />
          ) : (
            <ActivityList positions={positions} />
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
}: {
  label: string;
  value: string;
  tooltip?: string;
}) {
  const truncatedValue = value.length > 12 ? `${value.slice(0, 9)}...` : value;
  return (
    <div className="p-3">
      {tooltip ? (
        <Tooltip title={tooltip} arrow>
          <p className="cursor-help text-2xl font-bold leading-none tracking-tight">
            {truncatedValue}
          </p>
        </Tooltip>
      ) : (
        <p
          className="text-2xl font-bold leading-none tracking-tight"
          title={value}
        >
          {truncatedValue}
        </p>
      )}
      <p className="mt-1 text-sm font-medium text-muted-foreground">{label}</p>
    </div>
  );
}

function PositionList({
  positions,
  positionFilter,
  onPositionFilterChange,
  search,
  onSearchChange,
}: {
  positions: Position[];
  positionFilter: PositionFilter;
  onPositionFilterChange: (next: PositionFilter) => void;
  search: string;
  onSearchChange: (next: string) => void;
}) {
  const isClosed = positionFilter === "closed";

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
                    to={`/markets/${position.slug}`}
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
                    {Math.round(position.percentPnl)}%)
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ActivityList({
  positions,
}: {
  positions: {
    asset: string;
    outcome: string;
    size: number;
    title: string;
  }[];
}) {
  if (positions.length === 0) {
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
      {positions.slice(0, 8).map((position) => (
        <div
          key={`activity-${position.asset}-${position.outcome}`}
          className="flex items-center justify-between p-4"
        >
          <div className="min-w-0">
            <p className="text-sm font-medium">
              Position update: {position.outcome}
            </p>
            <p className="mt-1 truncate text-xs text-muted-foreground">
              {position.title}
            </p>
          </div>
          <p className="text-sm text-muted-foreground">
            {SHARES.format(position.size)} shares
          </p>
        </div>
      ))}
    </div>
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
