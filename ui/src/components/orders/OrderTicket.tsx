import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { placeMarketOrder, placeOrder, useOrderbook } from "@/api/orders";
import { useRequireAuth } from "@/auth/useRequireAuth";
import {
  MAX_PROB,
  MIN_PROB,
  SHARES_SCALE,
  SLIPPAGE_CAP,
  computeMarketBuy,
  computeMarketSell,
  dollarsFromShares,
  sharesFromDollars,
} from "@/components/orders/orderMath";
import type { OrderSide } from "@/types/order";
import { ApiError } from "@/api/client";

type Mode = "Limit" | "Market";

interface OrderTicketProps {
  marketId: number;
  outcome: string;
  isTradingDisabled: boolean;
  disabledReason?: string;
}

export function OrderTicket({
  marketId,
  outcome,
  isTradingDisabled,
  disabledReason,
}: OrderTicketProps) {
  const [side, setSide] = useState<OrderSide>("BUY");
  const [mode, setMode] = useState<Mode>("Limit");
  const [limitPrice, setLimitPrice] = useState<string>("0.50");
  const [limitShares, setLimitShares] = useState<string>("");
  const [marketAmount, setMarketAmount] = useState<string>("");

  const requireAuth = useRequireAuth();
  const queryClient = useQueryClient();
  const { data: book } = useOrderbook(marketId, outcome);

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
      const price = Number(limitPrice);
      const shares = Number(limitShares);
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
      const amount = Number(side === "BUY" ? marketAmount : limitShares);
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
    /* unchanged from Task 12 — preserved exactly */
    if (mode === "Limit") {
      const price = Number(limitPrice);
      const shares = Number(limitShares);
      if (!Number.isFinite(price) || !Number.isFinite(shares)) return null;
      if (price <= 0 || price >= 1 || shares <= 0) return null;
      return {
        priceLabel: `$${price.toFixed(2)}`,
        sharesLabel: shares.toFixed(2),
        totalLabel: `$${dollarsFromShares(shares, price).toFixed(2)}`,
        capWarning: null as string | null,
      };
    }
    const amount = Number(side === "BUY" ? marketAmount : limitShares);
    if (!book) return null;
    if (!Number.isFinite(amount) || amount <= 0) return null;
    if (side === "BUY") {
      const comp = computeMarketBuy(book.asks, amount);
      if (!comp) return null;
      const shares = sharesFromDollars(amount, comp.priceCap);
      return {
        priceLabel: `≤ $${comp.priceCap.toFixed(2)}`,
        sharesLabel: `~${shares.toFixed(2)}`,
        totalLabel: `$${amount.toFixed(2)}`,
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
      priceLabel: `≥ $${comp.priceCap.toFixed(2)}`,
      sharesLabel: amount.toFixed(2),
      totalLabel: `~$${total.toFixed(2)}`,
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

  return (
    <section className="space-y-4 rounded-lg border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Order ticket</h2>
        <span className="text-xs text-muted-foreground">{outcome}</span>
      </div>

      <div className="grid grid-cols-2 gap-1 rounded-md bg-muted p-1">
        {(["BUY", "SELL"] as const).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSide(s)}
            className={cn(
              "rounded-sm py-1.5 text-sm font-medium transition",
              side === s
                ? s === "BUY"
                  ? "bg-emerald-600 text-white shadow"
                  : "bg-rose-600 text-white shadow"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {s === "BUY" ? "Buy" : "Sell"}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-1 rounded-md bg-muted p-1">
        {(["Limit", "Market"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={cn(
              "rounded-sm py-1.5 text-sm font-medium transition",
              mode === m
                ? "bg-background shadow"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {m}
          </button>
        ))}
      </div>

      {mode === "Limit" ? (
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="limit-price">Limit price ($)</Label>
            <Input
              id="limit-price"
              type="number"
              inputMode="decimal"
              min="0.01"
              max="0.99"
              step="0.01"
              value={limitPrice}
              onChange={(e) => setLimitPrice(e.target.value)}
              disabled={isTradingDisabled}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="limit-shares">Shares</Label>
            <Input
              id="limit-shares"
              type="number"
              inputMode="decimal"
              min="0"
              step="1"
              value={limitShares}
              onChange={(e) => setLimitShares(e.target.value)}
              disabled={isTradingDisabled}
            />
          </div>
        </div>
      ) : side === "BUY" ? (
        <div className="space-y-1.5">
          <Label htmlFor="market-amount">Amount ($)</Label>
          <Input
            id="market-amount"
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            value={marketAmount}
            onChange={(e) => setMarketAmount(e.target.value)}
            disabled={isTradingDisabled}
          />
          <p className="text-xs text-muted-foreground">
            Max slippage: {SLIPPAGE_CAP.toFixed(2)} above best ask
            {bestAsk !== null ? ` ($${bestAsk.toFixed(2)})` : ""}
          </p>
        </div>
      ) : (
        <div className="space-y-1.5">
          <Label htmlFor="market-shares">Shares to sell</Label>
          <Input
            id="market-shares"
            type="number"
            inputMode="decimal"
            min="0"
            step="1"
            value={limitShares}
            onChange={(e) => setLimitShares(e.target.value)}
            disabled={isTradingDisabled}
          />
          <p className="text-xs text-muted-foreground">
            Max slippage: {SLIPPAGE_CAP.toFixed(2)} below best bid
            {bestBid !== null ? ` ($${bestBid.toFixed(2)})` : ""}
          </p>
        </div>
      )}

      <dl className="space-y-1 rounded-md border bg-muted/30 p-3 text-xs">
        <Row label="Price" value={preview?.priceLabel ?? "—"} />
        <Row label="Shares" value={preview?.sharesLabel ?? "—"} />
        <Row label="Total" value={preview?.totalLabel ?? "—"} />
        {preview?.capWarning ? (
          <Row label="" value={preview.capWarning} muted />
        ) : null}
      </dl>

      <Button
        type="button"
        size="lg"
        disabled={!canSubmit}
        className="w-full"
        onClick={onSubmit}
      >
        {isTradingDisabled
          ? (disabledReason ?? "Trading disabled")
          : limitMutation.isPending || marketMutation.isPending
            ? "Placing…"
            : `${side === "BUY" ? "Buy" : "Sell"} ${outcome}`}
      </Button>
    </section>
  );
}

function Row({
  label,
  value,
  muted,
}: {
  label: string;
  value: string;
  muted?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between">
      <dt className="text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "tabular-nums",
          muted ? "text-muted-foreground" : "font-medium",
        )}
      >
        {value}
      </dd>
    </div>
  );
}
