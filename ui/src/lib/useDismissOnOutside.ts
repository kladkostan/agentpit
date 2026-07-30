import { useEffect, useRef, type RefObject } from "react";

/** Close a popover when the user presses outside it, or hits Escape.
 *
 *  Listens on `pointerdown` rather than `click`. A click only fires on release,
 *  so pressing on something underneath would let that element act while the menu
 *  was still open, and a press that starts inside but releases outside would
 *  close the menu even though the user never left it. Pointerdown also runs
 *  before React's synthetic click, so the menu is gone by the time the press
 *  reaches whatever is beneath it.
 *
 *  The callback is held in a ref so an inline arrow does not re-subscribe the
 *  listeners on every render. */
export function useDismissOnOutside(
  ref: RefObject<HTMLElement | null>,
  onDismiss: () => void,
  active: boolean,
): void {
  const handler = useRef(onDismiss);
  handler.current = onDismiss;

  useEffect(() => {
    if (!active) return;

    const onPointerDown = (event: PointerEvent) => {
      const el = ref.current;
      if (!el) return;
      if (event.target instanceof Node && el.contains(event.target)) return;
      handler.current();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") handler.current();
    };

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [ref, active]);
}
