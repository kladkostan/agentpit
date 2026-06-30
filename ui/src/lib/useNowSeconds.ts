import { useEffect, useState } from "react";

/** A 1 Hz ticking clock (unix seconds) so countdowns and "live" judgements
 *  re-render each second. Shared by the agent detail + arena hub pages. */
export function useNowSeconds(): number {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    const id = window.setInterval(
      () => setNow(Math.floor(Date.now() / 1000)),
      1000,
    );
    return () => window.clearInterval(id);
  }, []);
  return now;
}
