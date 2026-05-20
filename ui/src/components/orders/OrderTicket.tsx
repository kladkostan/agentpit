import { useMemo, useState } from "react";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { getOrderbook, placeMarketOrder, placeOrder, useOrderbook } from "@/api/orders";
import { usePortfolio } from "@/api/portfolio";
import { useAuth } from "@/auth/useAuth";
import { useRequireAuth } from "@/auth/useRequireAuth";
import {
  MAX_PROB,
  MIN_PROB,
  SHARES_SCALE,
  SLIPPAGE_CAP,
  bestAskMicro,
  bestBidMicro,
  computeMarketBuy,
  computeMarketSell,
  dollarsFromShares,
  pickSellOutcome,
  sharesFromDollars,
} from "@/components/orders/orderMath";
import type { Erc1155Token } from "@/types/market";
import type { OrderSide, OrderbookResponse } from "@/types/order";
import { ApiError } from "@/api/client";

type Mode = "Limit" | "Market";

interface OrderTicketProps {
  marketId: number;
  tokens: Erc1155Token[];
  outcome: string;
  question: string;
  endDate: number | null;
  isTradingDisabled: boolean;
  disabledReason?: string;
  onOutcomeChange?: (outcome: string) => void;
}

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatDollars(n: number): string {
  return USD.format(n);
}

function endsInLabel(endDate: number | null): string | null {
  if (endDate === null) return null;
  const msLeft = endDate * 1000 - Date.now();
  if (msLeft <= 0) return "Closed";
  const days = Math.ceil(msLeft / 86_400_000);
  if (days <= 1) {
    const hours = Math.max(1, Math.ceil(msLeft / 3_600_000));
    return `Ends in ${hours} hour${hours === 1 ? "" : "s"}`;
  }
  return `Ends in ${days} days`;
}

/** Permissive decimal parser — strips locale commas and grouping. */
function parseDecimal(input: string): number {
  const trimmed = input.trim().replace(/,/g, ".");
  if (trimmed === "") return NaN;
  return Number(trimmed);
}

export function OrderTicket({
  marketId,
  tokens,
  outcome,
  question,
  endDate,
  isTradingDisabled,
  disabledReason,
  onOutcomeChange,
}: OrderTicketProps) {
  const [side, setSide] = useState<OrderSide>("BUY");
  const [mode, setMode] = useState<Mode>("Limit");
  const [limitPrice, setLimitPrice] = useState<string>("0.50");
  const [limitShares, setLimitShares] = useState<string>("");
  const [marketAmount, setMarketAmount] = useState<string>("");

  const requireAuth = useRequireAuth();
  const queryClient = useQueryClient();
  const { data: book } = useOrderbook(marketId, outcome);
  const { user } = useAuth();
  const { data: portfolio } = usePortfolio(Boolean(user));

  const heldByOutcome = useMemo(() => {
    const map = new Map<string, number>();
    if (!portfolio) return map;
    for (const p of portfolio.positions) {
      if (p.market_id !== marketId) continue;
      map.set(p.outcome_label, p.balance / SHARES_SCALE);
    }
    return map;
  }, [portfolio, marketId]);

  const heldOfCurrent = heldByOutcome.get(outcome) ?? 0;

  function selectSide(next: OrderSide) {
    setSide(next);
    if (next === "SELL" && onOutcomeChange) {
      const target = pickSellOutcome(outcome, heldByOutcome);
      if (target !== outcome) onOutcomeChange(target);
    }
  }

  const bestAsk =
    book && book.asks.length > 0
      ? Math.min(...book.asks.map((a) => a.PRICE)) / 1_000_000
      : null;
  const bestBid =
    book && book.bids.length > 0
      ? Math.max(...book.bids.map((b) => b.PRICE)) / 1_000_000
      : null;

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: ["orderbook", marketId, outcome],
    });
    void queryClient.invalidateQueries({ queryKey: ["portfolio"] });
  };

  const limitMutation = useMutation({
    mutationFn: async () => {
      const price = parseDecimal(limitPrice);
      const shares = parseDecimal(limitShares);
      return placeOrder({
        market_id: marketId,
        outcome,
        side,
        price,
        size: Math.floor(shares * SHARES_SCALE),
        order_type: "GTC",
      });
    },
    onSuccess: (res) => {
      if (!res.success) {
        toast.error(`Order failed: ${res.errorMsg ?? "unknown"}`);
        return;
      }
      const filled = Number(res.filledSize) / SHARES_SCALE;
      const remaining = Number(res.remainingSize) / SHARES_SCALE;
      toast.success(
        remaining > 0
          ? `Order placed: ${filled.toFixed(2)} filled, ${remaining.toFixed(
              2,
            )} resting`
          : `Order filled: ${filled.toFixed(2)} shares`,
      );
      setLimitShares("");
      invalidate();
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : String(err));
    },
  });

  const marketMutation = useMutation({
    mutationFn: async () => {
      if (!book) throw new Error("Orderbook not loaded yet");
      const amount = parseDecimal(side === "BUY" ? marketAmount : limitShares);
      return placeMarketOrder({
        marketId,
        outcome,
        side,
        amount,
        book,
      });
    },
    onSuccess: (res) => {
      const tail = res.cancelledRemainder
        ? ` (${res.remainingShares.toFixed(2)} unfilled, cancelled)`
        : "";
      const avg = res.avgPrice !== null ? ` @ avg $${res.avgPrice.toFixed(2)}` : "";
      if (res.filledShares <= 0) {
        toast.error(`No fills${tail || ""}`);
      } else {
        toast.success(
          `${side === "BUY" ? "Bought" : "Sold"} ${res.filledShares.toFixed(2)}${avg}${tail}`,
        );
      }
      if (res.cancelError) {
        toast.warning(`Auto-cancel failed: ${res.cancelError}`);
      }
      if (side === "BUY") {
        setMarketAmount("");
      } else {
        setLimitShares("");
      }
      invalidate();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : String(err));
    },
  });

  const preview = useMemo(() => {
    if (mode === "Limit") {
      const price = parseDecimal(limitPrice);
      const shares = parseDecimal(limitShares);
      if (!Number.isFinite(price) || !Number.isFinite(shares)) return null;
      if (price <= 0 || price >= 1 || shares <= 0) return null;
      const cost = dollarsFromShares(shares, price);
      return {
        price,
        shares,
        cost,
        capWarning: null as string | null,
      };
    }
    const amount = parseDecimal(side === "BUY" ? marketAmount : limitShares);
    if (!book) return null;
    if (!Number.isFinite(amount) || amount <= 0) return null;
    if (side === "BUY") {
      const comp = computeMarketBuy(book.asks, amount);
      if (!comp) return null;
      const shares = sharesFromDollars(amount, comp.priceCap);
      return {
        price: comp.priceCap,
        shares,
        cost: amount,
        capWarning:
          comp.priceCap >= MAX_PROB
            ? `Cap clamped to ${MAX_PROB.toFixed(2)}`
            : null,
      };
    }
    const comp = computeMarketSell(book.bids, amount);
    if (!comp) return null;
    const total = dollarsFromShares(amount, comp.priceCap);
    return {
      price: comp.priceCap,
      shares: amount,
      cost: total,
      capWarning:
        comp.priceCap <= MIN_PROB
          ? `Cap clamped to ${MIN_PROB.toFixed(2)}`
          : null,
    };
  }, [mode, side, limitPrice, limitShares, marketAmount, book]);

  const canSubmit =
    !isTradingDisabled &&
    preview !== null &&
    !limitMutation.isPending &&
    !marketMutation.isPending &&
    (mode === "Limit" ||
      (side === "BUY" ? bestAsk !== null : bestBid !== null));

  const onSubmit = requireAuth(() => {
    if (mode === "Limit") {
      limitMutation.mutate();
    } else {
      marketMutation.mutate();
    }
  });

  const isBuy = side === "BUY";
  const endsLabel = endsInLabel(endDate);
  const ctaTone = isBuy
    ? "bg-[#0F6E56] hover:bg-[#0F6E56]/90"
    : "bg-rose-700 hover:bg-rose-700/90";

  const ctaLabel = (() => {
    if (isTradingDisabled) return disabledReason ?? "Trading disabled";
    if (limitMutation.isPending || marketMutation.isPending) return "Placing…";
    if (!preview) return `${isBuy ? "Buy" : "Sell"} ${outcome}`;
    const cents = Math.round(preview.price * 100);
    const sharesStr = formatNumber(preview.shares);
    return `${isBuy ? "Buy" : "Sell"} ${sharesStr} ${outcome.toUpperCase()} at ${cents}¢`;
  })();

  // Live cost hint shown next to the Shares label as user types.
  const sharesValue = parseDecimal(limitShares);
  const priceForCost = (() => {
    if (mode === "Limit") return parseDecimal(limitPrice);
    if (side === "BUY") return bestAsk ?? NaN;
    return bestBid ?? NaN;
  })();
  const liveCost =
    Number.isFinite(sharesValue) &&
    sharesValue > 0 &&
    Number.isFinite(priceForCost) &&
    priceForCost > 0
      ? sharesValue * priceForCost
      : null;

  return (
    <section className="sticky top-20 w-full max-w-[360px] self-start overflow-hidden rounded-2xl border border-border/80 bg-card shadow-[0_1px_0_0_hsl(var(--border)),0_24px_60px_-24px_rgba(0,0,0,0.18)]">
      <header className="space-y-1.5 border-b border-border/60 px-5 py-4">
        <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-muted-foreground/80">
          Market
        </p>
        <h2 className="text-[15px] font-medium leading-[1.35] text-foreground">
          {question}
        </h2>
        {endsLabel ? (
          <p className="text-xs text-muted-foreground">{endsLabel}</p>
        ) : null}
      </header>

      <div className="space-y-3.5 px-5 py-5">
        <OutcomePicker
          marketId={marketId}
          tokens={tokens}
          selected={outcome}
          side={side}
          onSelect={(label) => onOutcomeChange?.(label)}
        />

        <SegmentedSide side={side} onSelect={selectSide} />

        <SegmentedMode mode={mode} onSelect={setMode} />

        {mode === "Limit" ? (
          <div className="space-y-3">
            <Field label="Limit price" hint="USDC">
              <ValueInput
                id="limit-price"
                value={limitPrice}
                onChange={setLimitPrice}
                disabled={isTradingDisabled}
                suffix="per share"
              />
            </Field>
            <Field
              label="Shares"
              hint={
                liveCost !== null ? (
                  <span>
                    ≈ <span className="text-foreground/80">{formatDollars(liveCost)}</span>{" "}
                    cost
                  </span>
                ) : null
              }
            >
              <ValueInput
                id="limit-shares"
                value={limitShares}
                onChange={setLimitShares}
                disabled={isTradingDisabled}
              />
            </Field>
            {!isBuy ? (
              <Hint>
                You hold{" "}
                <span className="font-medium tabular-nums text-foreground/80">
                  {heldOfCurrent.toFixed(2)}
                </span>{" "}
                {outcome} shares
              </Hint>
            ) : null}
          </div>
        ) : isBuy ? (
          <div className="space-y-2">
            <Field label="Amount" hint="USDC">
              <ValueInput
                id="market-amount"
                value={marketAmount}
                onChange={setMarketAmount}
                disabled={isTradingDisabled}
                suffix="to spend"
              />
            </Field>
            <Hint>
              Max slippage {SLIPPAGE_CAP.toFixed(2)} over best ask
              {bestAsk !== null ? (
                <>
                  {" "}({Math.round(bestAsk * 100)}¢)
                </>
              ) : null}
            </Hint>
          </div>
        ) : (
          <div className="space-y-2">
            <Field
              label="Shares to sell"
              hint={
                liveCost !== null ? (
                  <span>
                    ≈ <span className="text-foreground/80">{formatDollars(liveCost)}</span>{" "}
                    received
                  </span>
                ) : null
              }
            >
              <ValueInput
                id="market-shares"
                value={limitShares}
                onChange={setLimitShares}
                disabled={isTradingDisabled}
              />
            </Field>
            <Hint>
              You hold{" "}
              <span className="font-medium tabular-nums text-foreground/80">
                {heldOfCurrent.toFixed(2)}
              </span>{" "}
              {outcome} shares · max slippage {SLIPPAGE_CAP.toFixed(2)} under
              best bid
              {bestBid !== null ? <> ({Math.round(bestBid * 100)}¢)</> : null}
            </Hint>
          </div>
        )}

        {preview && isBuy ? (
          <PayoutSummary
            pay={preview.cost}
            shares={preview.shares}
            outcome={outcome}
          />
        ) : null}

        {preview?.capWarning ? (
          <p className="text-[11px] text-amber-700 dark:text-amber-400">
            {preview.capWarning}
          </p>
        ) : null}

        <Button
          type="button"
          disabled={!canSubmit}
          className={cn(
            "h-11 w-full rounded-lg text-sm font-medium text-white transition-all",
            !isTradingDisabled && ctaTone,
            !canSubmit && "opacity-60",
          )}
          onClick={onSubmit}
        >
          {ctaLabel}
        </Button>
      </div>
    </section>
  );
}

/* ---------- Outcome picker (cents, sans, strong selected state) ---------- */

function OutcomePicker({
  marketId,
  tokens,
  selected,
  side,
  onSelect,
}: {
  marketId: number;
  tokens: Erc1155Token[];
  selected: string;
  side: OrderSide;
  onSelect: (label: string) => void;
}) {
  const results = useQueries({
    queries: tokens.map(([, label]) => ({
      queryKey: ["orderbook", marketId, label],
      queryFn: () => getOrderbook(marketId, label),
      refetchInterval: 5000,
      refetchIntervalInBackground: false,
    })),
  });

  return (
    <div
      role="tablist"
      aria-label="Outcomes"
      className="grid gap-2"
      style={{
        gridTemplateColumns: `repeat(${tokens.length}, minmax(0, 1fr))`,
      }}
    >
      {tokens.map(([id, label], i) => {
        const book = results[i]?.data as OrderbookResponse | undefined;
        // Show the price you'd actually trade at for the current side: the
        // best ask when buying, the best bid when selling — not the mid.
        const micro =
          side === "BUY"
            ? bestAskMicro(book?.asks ?? [])
            : bestBidMicro(book?.bids ?? []);
        const cents = micro !== null ? micro / 10_000 : null;
        const isActive = label === selected;
        const isPositive = i === 0;
        const tone = isPositive ? "emerald" : "rose";
        return (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={isActive}
            onClick={() => onSelect(label)}
            className={cn(
              "flex flex-col items-start gap-1 rounded-lg border px-3 py-2.5 text-left transition-all",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              isActive
                ? tone === "emerald"
                  ? "border-[1.5px] border-emerald-600 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200"
                  : "border-[1.5px] border-rose-600 bg-rose-500/10 text-rose-800 dark:text-rose-200"
                : "border-border/80 text-muted-foreground hover:border-foreground/30 hover:text-foreground",
            )}
          >
            <span className="text-[11px] font-medium uppercase tracking-[0.08em]">
              {label.toUpperCase()}
            </span>
            <span className="flex items-baseline">
              <span className="text-[22px] font-medium leading-none tabular-nums">
                {cents !== null ? cents.toFixed(1) : "—"}
              </span>
              <span className="ml-0.5 text-[14px] leading-none opacity-70">
                ¢
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/* ---------- Buy / Sell (neutral segmented) ---------- */

function SegmentedSide({
  side,
  onSelect,
}: {
  side: OrderSide;
  onSelect: (next: OrderSide) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-0.5 rounded-lg bg-muted/60 p-[3px]">
      {(["BUY", "SELL"] as const).map((s) => {
        const active = side === s;
        return (
          <button
            key={s}
            type="button"
            onClick={() => onSelect(s)}
            className={cn(
              "rounded-md py-1.5 text-[13px] font-medium transition-all",
              active
                ? "bg-background text-foreground shadow-[0_0_0_0.5px_hsl(var(--border)),0_1px_2px_rgba(0,0,0,0.04)]"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {s === "BUY" ? "Buy" : "Sell"}
          </button>
        );
      })}
    </div>
  );
}

/* ---------- Limit / Market (fixed underline) ---------- */

function SegmentedMode({
  mode,
  onSelect,
}: {
  mode: "Limit" | "Market";
  onSelect: (next: "Limit" | "Market") => void;
}) {
  return (
    <div className="flex items-center gap-4 border-b border-border/60">
      {(["Limit", "Market"] as const).map((m) => {
        const active = mode === m;
        return (
          <button
            key={m}
            type="button"
            onClick={() => onSelect(m)}
            className={cn(
              "relative inline-block pb-2 pt-1 text-[13px] transition-colors",
              active
                ? "font-medium text-foreground"
                : "font-normal text-muted-foreground hover:text-foreground",
            )}
          >
            {m}
            <span
              aria-hidden
              className={cn(
                "absolute -bottom-[0.5px] left-0 right-0 h-[1.5px] transition-colors",
                active ? "bg-foreground" : "bg-transparent",
              )}
            />
          </button>
        );
      })}
    </div>
  );
}

/* ---------- Compact field shell ---------- */

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border/80 bg-background px-3 py-2.5 transition-colors focus-within:border-foreground/45">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[12px] text-muted-foreground">{label}</span>
        {hint ? (
          <span className="text-[11px] text-muted-foreground/80">{hint}</span>
        ) : null}
      </div>
      {children}
    </div>
  );
}

/* ---------- Locale-stable decimal input ---------- */

function ValueInput({
  id,
  value,
  onChange,
  disabled,
  suffix,
}: {
  id: string;
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
  suffix?: string;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <input
        id={id}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="min-w-0 flex-1 bg-transparent text-[22px] font-medium tabular-nums text-foreground outline-none placeholder:text-muted-foreground/60 disabled:opacity-60"
        placeholder="0"
      />
      {suffix ? (
        <span className="text-[13px] text-muted-foreground">{suffix}</span>
      ) : null}
    </div>
  );
}

/* ---------- Payout summary ---------- */

function PayoutSummary({
  pay,
  shares,
  outcome,
}: {
  pay: number;
  shares: number;
  outcome: string;
}) {
  // Each winning share pays $1.00; profit is the difference.
  const payout = shares * 1;
  const profit = payout - pay;
  const profitPct = pay > 0 ? (profit / pay) * 100 : 0;

  return (
    <div className="space-y-2 rounded-lg bg-emerald-500/8 px-3.5 py-3 text-[12px] dark:bg-emerald-500/10">
      <div className="flex items-baseline justify-between text-emerald-900 dark:text-emerald-200">
        <span>You pay</span>
        <span className="tabular-nums">{formatDollars(pay)}</span>
      </div>
      <div className="flex items-baseline justify-between text-emerald-900 dark:text-emerald-200">
        <span>
          If {outcome.toUpperCase()} wins, you get
        </span>
        <span className="tabular-nums">{formatDollars(payout)}</span>
      </div>
      <div className="-mx-3.5 border-t border-emerald-700/15 dark:border-emerald-300/15" />
      <div className="flex items-baseline justify-between font-medium text-emerald-900 dark:text-emerald-100">
        <span>Potential profit</span>
        <span className="tabular-nums">
          {profit >= 0 ? "+" : "−"}
          {formatDollars(Math.abs(profit))}{" "}
          <span className="font-normal text-emerald-700 dark:text-emerald-300">
            ({profit >= 0 ? "+" : "−"}
            {Math.abs(profitPct).toFixed(0)}%)
          </span>
        </span>
      </div>
    </div>
  );
}

/* ---------- Hint footnote ---------- */

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="px-1 text-[11px] text-muted-foreground">{children}</p>;
}

/* ---------- Helpers ---------- */

function formatNumber(n: number): string {
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(2);
}
