import { useMemo, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import {
    AlertCircle,
    ArrowUpRight,
    Search,
    Upload,
} from "lucide-react";
import { usePortfolio } from "@/api/portfolio";
import { useAuth } from "@/auth/useAuth";
import { Button } from "@/components/ui/button";
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

const SHARES_SCALE = 1_000_000;

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
    const [positionFilter, setPositionFilter] = useState<PositionFilter>("active");
    const [search, setSearch] = useState("");
    const { user } = useAuth();
    const { data, isLoading, error } = usePortfolio(Boolean(user));
    const avatarStyle = getAvatarStyle(user?.eth_address || user?.email);

    const positions = useMemo(() => {
        if (!data) return [];
        return [...data.positions]
            .filter((p) => p.balance > 0)
            .sort((a, b) => b.balance - a.balance);
    }, [data]);

    const filteredPositions = useMemo(() => {
        if (positionFilter === "closed") return [];
        const q = search.trim().toLowerCase();
        if (!q) return positions;
        return positions.filter((p) => {
            const hay = `${p.question} ${p.outcome_label}`.toLowerCase();
            return hay.includes(q);
        });
    }, [positions, positionFilter, search]);

    if (!user) return <Navigate to="/" replace />;

    return (
        <section className="mx-auto max-w-5xl space-y-6">
            <h1 className="text-3xl font-semibold tracking-tight">Profile</h1>
            <div className="grid gap-3 lg:grid-cols-2">
                <Card className="rounded-2xl border-border/80">
                    <CardContent className="p-4 sm:p-5">
                        <div className="flex items-start justify-between gap-3">
                            <div className="flex min-w-0 items-center gap-3">
                                <div
                                    className="flex size-14 shrink-0 items-center justify-center rounded-full text-lg font-semibold text-white"
                                    style={avatarStyle}
                                >
                                    {displayName(user.email, user.handle).slice(0, 1).toUpperCase()}
                                </div>
                                <div className="min-w-0">
                                    <Tooltip title={user.eth_address} arrow>
                                        <h1 className="truncate cursor-help text-2xl font-semibold leading-none tracking-tight">
                                            {shortAddress(user.eth_address)}
                                        </h1>
                                    </Tooltip>
                                    <p className="mt-2 text-sm! text-muted-foreground">
                                        Joined {DATE.format(new Date(user.created_at * 1000))} • 0 views
                                    </p>
                                </div>
                            </div>
                            <Button variant="ghost" size="sm" className="text-muted-foreground">
                                <Upload className="size-4" />
                            </Button>
                        </div>

                        <div className="mt-4 grid grid-cols-3 divide-x rounded-lg border bg-muted/20">
                            <TopMetric
                                label="Positions Value"
                                value={USD.format(data?.usdc_balance ?? 0)}
                                tooltip={USD.format(data?.usdc_balance ?? 0)}
                            />
                            <TopMetric label="Biggest Win" value="-" />
                            <TopMetric label="Predictions" value={positions.length.toString()} />
                        </div>

                    </CardContent>
                </Card>

                <Card className="rounded-2xl border-border/80">
                    <CardContent className="p-4 sm:p-5">
                        <div className="flex items-center justify-between">
                            <p className="text-sm text-sm text-muted-foreground">Profit/Loss</p>
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
                        <p className="mt-2 text-2xl font-semibold leading-none tracking-tight">$0.00</p>
                        <p className="mt-1 text-sm text-muted-foreground">Past Day</p>
                        <div className="mt-8 h-14 rounded-md bg-gradient-to-t from-blue-100 via-blue-50 to-transparent" />
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
                <>
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
                </>
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
                    <p className="text-2xl font-bold leading-none tracking-tight cursor-help">
                        {truncatedValue}
                    </p>
                </Tooltip>
            ) : (
                <p className="text-2xl font-bold leading-none tracking-tight" title={value}>
                    {truncatedValue}
                </p>
            )}
            <p className="mt-1 text-sm text-muted-foreground font-medium">{label}</p>
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
    positions: {
        market_id: number;
        question: string;
        token_id: string;
        outcome_label: string;
        balance: number;
    }[];
    positionFilter: PositionFilter;
    onPositionFilterChange: (next: PositionFilter) => void;
    search: string;
    onSearchChange: (next: string) => void;
}) {
    const rows = positions;

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

            <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-sm">
                    <thead className="border-b text-left text-xs uppercase tracking-[0.1em] text-muted-foreground">
                        <tr>
                            <th className="px-4 py-3">Market</th>
                            <th className="px-4 py-3">Avg</th>
                            <th className="px-4 py-3">Current</th>
                            <th className="px-4 py-3 text-right">Value</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.length === 0 ? (
                            <tr>
                                <td colSpan={4} className="px-4 py-14 text-center text-muted-foreground">
                                    No positions found
                                </td>
                            </tr>
                        ) : (
                            rows.map((position) => (
                                <tr key={`${position.market_id}-${position.token_id}`} className="border-b hover:bg-muted/20">
                                    <td className="px-4 py-4 align-top">
                                        <p className="line-clamp-2 font-medium">{position.question}</p>
                                        <p className="mt-1 text-xs uppercase tracking-[0.08em] text-muted-foreground">
                                            {position.outcome_label}
                                        </p>
                                    </td>
                                    <td className="px-4 py-4 text-muted-foreground">-</td>
                                    <td className="px-4 py-4 text-muted-foreground">-</td>
                                    <td className="px-4 py-4 text-right">
                                        <p className="font-medium">
                                            {SHARES.format(position.balance / SHARES_SCALE)} shares
                                        </p>
                                        <Button asChild size="sm" variant="link" className="h-auto p-0 text-xs">
                                            <Link to={`/markets/${position.market_id}`}>
                                                View market
                                                <ArrowUpRight className="ml-1 size-3.5" />
                                            </Link>
                                        </Button>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

function ActivityList({
    positions,
}: {
    positions: {
        market_id: number;
        outcome_label: string;
        balance: number;
        question: string;
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
                <div key={`activity-${position.market_id}-${position.outcome_label}`} className="flex items-center justify-between p-4">
                    <div className="min-w-0">
                        <p className="text-sm font-medium">Position update: {position.outcome_label}</p>
                        <p className="mt-1 truncate text-xs text-muted-foreground">{position.question}</p>
                    </div>
                    <p className="text-sm text-muted-foreground">{SHARES.format(position.balance / SHARES_SCALE)} shares</p>
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
