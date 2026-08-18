/** The limit-price field's own vocabulary.
 *
 *  The API takes a probability strictly inside (0, 1) snapped to a 0.001
 *  tick — see `_PRICE_TICK` and the `price` validator in
 *  agentpit/datastructures/place_order_request.py. In the cents this field
 *  shows, that grid is 0.1¢ … 99.9¢ with a single decimal. Off-grid input
 *  does not bounce: the server quantises it half-to-even, so 11.55¢ becomes
 *  11.6¢ without a word, and 99.95¢ snaps onto 1.000 and comes back a 422.
 *  Neither is something to show a trader after the fact, so the field
 *  refuses to hold such a value in the first place.
 *
 *  Normalised on the way in, not on submit — the same reasoning as
 *  `normaliseCode` in components/auth/codeFlow.ts: what the field shows is
 *  what the order will be placed at.
 *
 *  Not to be confused with MIN_PROB/MAX_PROB in ./orderMath: those are the
 *  0.01/0.99 caps a MARKET order's slippage is allowed to walk to, a
 *  different rule about a different order type.
 */
export const MIN_CENTS = 0.1;
export const MAX_CENTS = 99.9;

/** One tick of the server's grid, and so the smallest move the +/- buttons
 *  can make without asking for a price that does not exist. */
export const STEP_CENTS = 0.1;

/** Digits with at most one decimal point, and nothing else — no sign, no
 *  exponent, no second point. */
const SHAPE = /^\d*\.?\d*$/;

/** What the field should show once the user has typed `raw` into it,
 *  given that it showed `previous` a keystroke ago.
 *
 *  Two whole digits and one decimal are all the grid allows, and that shape
 *  is also what caps the value at 99.9 — there is no separate range test
 *  here to drift out of step with it.
 *
 *  A third digit typed onto the END with no decimal point in sight becomes
 *  the decimal: `11` and then `5` reads as 11.5, not 115. Only onto the end
 *  — a digit dropped into the middle of `99` would otherwise push the
 *  second 9 into the tenths and hand back 19.9, a price rewritten out of
 *  digits the trader never touched.
 *
 *  Input that cannot be shaped that way — a fourth digit, a second point, a
 *  letter — leaves the field as it was, so the keystroke is refused rather
 *  than silently reinterpreted as some other number.
 */
export function normaliseLimitCents(raw: string, previous: string): string {
  const typed = raw.trim().replace(/,/g, ".");
  if (typed === "") return "";
  if (!SHAPE.test(typed)) return previous;

  const point = typed.indexOf(".");
  let whole = point === -1 ? typed : typed.slice(0, point);
  let fraction = point === -1 ? "" : typed.slice(point + 1);

  if (point === -1) {
    if (whole.length > 3) return previous;
    if (whole.length === 3) {
      const appended =
        typed.length === previous.length + 1 && typed.startsWith(previous);
      if (!appended) return previous;
      fraction = whole.slice(2);
      whole = whole.slice(0, 2);
    }
  } else if (whole.length > 2 || fraction.length > 1) {
    return previous;
  }

  // "05" is 5 and "00" is 0, but a lone "0" stands: it is how someone on
  // their way to 0.5 starts, and the point they type next needs it there.
  whole = whole.replace(/^0+(?=\d)/, "");
  if (whole === "") whole = "0";

  return point === -1 && fraction === "" ? whole : `${whole}.${fraction}`;
}

/** Where the +/- buttons land from `current`.
 *
 *  A step is one tick, the same 0.1¢ the field lets a trader type, so the
 *  buttons can reach every price on the grid rather than only the whole
 *  cents. It also keeps the tenth already in the field: 11.5 steps to 11.6,
 *  never back to 12.
 *
 *  At the ends the step is clamped rather than refused, so + always reaches
 *  99.9 and - always reaches 0.1.
 */
export function stepLimitCents(current: string, delta: number): string {
  const trimmed = current.trim().replace(/,/g, ".");
  const parsed = trimmed === "" ? NaN : Number(trimmed);
  const from = Number.isFinite(parsed) ? parsed : 50;
  const next = Math.min(MAX_CENTS, Math.max(MIN_CENTS, from + delta));
  // Tenths are not exact in binary — 0.1 + 1 is 1.1000000000000001 — and the
  // grid is tenths, so the rendered value is rounded onto it.
  return String(Math.round(next * 10) / 10);
}
