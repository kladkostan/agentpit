import { bestAsk, deriveNoAsk } from "@/components/orders/orderMath";
import { formatProbabilityPct } from "@/lib/format";
import { useOutcomeMid } from "@/lib/useYesMid";
import { cn } from "@/lib/utils";
import type { Market } from "@/types/market";

interface EventLeaderboardRowProps {
  market: Market;
  rank: number;
  isSelected: boolean;
  selectedOutcome: string | null;
  /** Row body click — toggles expand/collapse for this market. */
  onToggleMarket: (marketId: number, outcome: string) => void;
  /** Yes/No chip click — always selects, never collapses. */
  onPickOutcome: (marketId: number, outcome: string) => void;
}

function OutcomeIcon({ market }: { market: Market }) {
  const icon = market.icon_url;
  if (icon && (icon.startsWith("http") || icon.startsWith("/"))) {
    return (
      <img
        src={icon}
        alt=""
        className="size-9 rounded-md object-cover ring-1 ring-border"
        loading="lazy"
      />
    );
  }
  const glyph = icon ?? "•";
  return (
    <span
      aria-hidden
      className="flex size-9 items-center justify-center rounded-md bg-secondary text-xl leading-none"
    >
      {glyph}
    </span>
  );
}

function formatCents(value: number | null): string {
  if (value === null) return "—";
  return `${value.toFixed(1)}¢`;
}

export function EventLeaderboardRow({
  market,
  rank,
  isSelected,
  selectedOutcome,
  onToggleMarket,
  onPickOutcome,
}: EventLeaderboardRowProps) {
  const yesTokenId = market.erc1155_tokens[0]?.[0];
  const noTokenId = market.erc1155_tokens[1]?.[0];
  const yesLabel = market.erc1155_tokens[0]?.[1];
  const noLabel = market.erc1155_tokens[1]?.[1];
  const yes = useOutcomeMid(yesTokenId);
  const no = useOutcomeMid(noTokenId);
  // The Yes/No chips are buy entry points, so show the price to BUY each
  // outcome — the order book's best ask — which agrees with the book to the
  // cent. The big % stays the mid (the market's implied probability).
  const yesAsk = yes.data ? bestAsk(yes.data.asks) : null;
  const noAsk = deriveNoAsk(no.data?.asks ?? [], yes.data?.bids ?? []);
  // Convert dollars to cents for display
  const yesCents = yesAsk !== null ? yesAsk * 100 : null;
  const noCents = noAsk !== null ? noAsk * 100 : null;
  const yesPctLabel = formatProbabilityPct(yes.mid);
  const label = market.outcome_label ?? market.question;

  return (
    <div
      className={cn(
        "group flex items-stretch border-l-2 border-transparent border-b border-border/60 transition-colors",
        isSelected
          ? "border-l-foreground bg-foreground/[0.04]"
          : "hover:bg-foreground/[0.02]",
      )}
    >
      <button
        type="button"
        onClick={() => onToggleMarket(market.market_id, yesLabel ?? "")}
        aria-expanded={isSelected}
        className="flex flex-1 items-center gap-4 py-3 pl-3 pr-4 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="w-10 font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground/70 tabular-nums">
          #{rank}
        </span>
        <OutcomeIcon market={market} />
        <span className="min-w-0 flex-1 truncate text-[15px] font-medium tracking-tight transition-colors group-hover:text-foreground">
          {label}
        </span>
        <span className="flex w-[72px] items-baseline justify-end gap-1">
          <span
            className={cn(
              "text-2xl font-semibold leading-none tabular-nums",
              yes.mid === null && "text-muted-foreground/40",
            )}
          >
            {yesPctLabel}
          </span>
          <span className="text-sm font-semibold leading-none opacity-60">%</span>
        </span>
      </button>

      <div className="flex items-stretch gap-1.5 py-3 pr-4">
        <PriceChip
          tone="yes"
          label="Yes"
          price={formatCents(yesCents)}
          isActive={isSelected && selectedOutcome === yesLabel}
          onClick={() => onPickOutcome(market.market_id, yesLabel ?? "")}
        />
        <PriceChip
          tone="no"
          label="No"
          price={formatCents(noCents)}
          isActive={isSelected && selectedOutcome === noLabel}
          onClick={() => onPickOutcome(market.market_id, noLabel ?? "")}
        />
      </div>
    </div>
  );
}

function PriceChip({
  tone,
  label,
  price,
  isActive,
  onClick,
}: {
  tone: "yes" | "no";
  label: string;
  price: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex min-w-[78px] flex-col items-center justify-center rounded-lg border px-2.5 py-1.5 leading-tight transition-all",
        "outline-none focus-visible:ring-2 focus-visible:ring-ring",
        tone === "yes"
          ? isActive
            ? "border-emerald-500/70 bg-emerald-500/25 text-emerald-700 dark:text-emerald-200"
            : "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 hover:border-emerald-500/55 hover:bg-emerald-500/20 dark:text-emerald-300"
          : isActive
            ? "border-rose-500/70 bg-rose-500/25 text-rose-700 dark:text-rose-200"
            : "border-rose-500/25 bg-rose-500/10 text-rose-700 hover:border-rose-500/55 hover:bg-rose-500/20 dark:text-rose-300",
      )}
    >
      <span className="font-mono text-[9px] uppercase tracking-[0.18em] opacity-80">
        {label}
      </span>
      <span className="mt-0.5 text-xs font-semibold tabular-nums">{price}</span>
    </button>
  );
}
