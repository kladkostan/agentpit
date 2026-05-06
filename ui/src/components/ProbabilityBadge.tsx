import { cn } from "@/lib/utils";

export type ProbabilitySide = "yes" | "no";

interface ProbabilityBadgeProps {
  side: ProbabilitySide;
  probability: number | null;
  className?: string;
}

function formatProbability(probability: number | null): string {
  if (probability === null || Number.isNaN(probability)) {
    return "—¢";
  }
  const cents = Math.round(probability * 100);
  return `${cents}¢`;
}

export function ProbabilityBadge({
  side,
  probability,
  className,
}: ProbabilityBadgeProps) {
  const label = side === "yes" ? "Yes" : "No";
  const sideClasses =
    side === "yes"
      ? "bg-emerald-100 text-emerald-900 hover:bg-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-200 dark:hover:bg-emerald-900/50"
      : "bg-rose-100 text-rose-900 hover:bg-rose-200 dark:bg-rose-900/30 dark:text-rose-200 dark:hover:bg-rose-900/50";

  return (
    <button
      type="button"
      className={cn(
        "inline-flex h-9 flex-1 items-center justify-center gap-1 rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
        sideClasses,
        className,
      )}
      disabled={probability === null}
      aria-label={`${label} ${formatProbability(probability)}`}
    >
      <span>{label}</span>
      <span className="tabular-nums">{formatProbability(probability)}</span>
    </button>
  );
}
