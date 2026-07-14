import { useEffect, useRef, useState } from "react";

/** Clipboard write with a transient "copied" flag for ✓ feedback. */
export function useCopyFeedback(resetMs = 1500) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), resetMs);
    } catch {
      // Clipboard can be unavailable (http, permissions) — fail quiet.
    }
  };

  return { copied, copy };
}
