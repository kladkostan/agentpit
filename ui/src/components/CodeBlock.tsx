import { Check, Copy } from "lucide-react";
import { commandsOnly, tokenizeSnippet } from "@/lib/getStarted";
import { useCopyFeedback } from "@/lib/useCopyFeedback";
import { cn } from "@/lib/utils";

/** Dark-canvas code card (dark in BOTH themes — code reads best on ink).
 *
 *  `code` is the single source of truth for what is DISPLAYED. What gets
 *  copied is deliberately not identical: the explanatory comments are dropped,
 *  because interactive zsh runs a pasted `#` line rather than ignoring it and
 *  answers `command not found: #` once per line. */
export function CodeBlock({
  title,
  code,
  chips = [],
  className,
}: {
  title: string;
  code: string;
  chips?: string[];
  className?: string;
}) {
  const { copied, copy } = useCopyFeedback();
  const onCopy = () => copy(commandsOnly(code));

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-slate-700/60 bg-slate-950 shadow-sm",
        className,
      )}
    >
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <span className="font-mono text-[11px] uppercase tracking-widest text-slate-500">
          {title}
        </span>
        <button
          type="button"
          onClick={onCopy}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors",
            copied
              ? "text-emerald-400"
              : "text-slate-400 hover:bg-slate-800 hover:text-slate-200",
          )}
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-[13px] leading-relaxed text-slate-200">
        <TintedCode code={code} chips={chips} />
      </pre>
    </div>
  );
}

function TintedCode({ code, chips }: { code: string; chips: string[] }) {
  return (
    <>
      {tokenizeSnippet(code, chips).map((t, i) =>
        t.kind === "comment" ? (
          <span key={i} className="italic text-slate-500">
            {t.value}
          </span>
        ) : t.kind === "string" ? (
          <span key={i} className="text-emerald-300/90">
            {t.value}
          </span>
        ) : t.kind === "chip" ? (
          <span
            key={i}
            className="rounded bg-emerald-500/15 px-1 py-0.5 font-semibold text-emerald-300"
          >
            {t.value}
          </span>
        ) : (
          <span key={i}>{t.value}</span>
        ),
      )}
    </>
  );
}
