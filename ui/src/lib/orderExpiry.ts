/** Turning the Expires menu into the two fields the API takes.
 *
 *  Two rules from Polymarket, neither guessable from the field names:
 *  an order dies a minute BEFORE its stated expiration, so a client asking
 *  for a lifetime of N sends `now + 60 + N`; and an expiration under three
 *  minutes out is rejected outright.
 *
 *  Documented, not folklore: Polymarket docs, page `trading/place-orders.mdx`,
 *  "GTD orders expire one minute before their stated expiration as a
 *  security threshold. To set an effective lifetime of N seconds, use
 *  `now + 60 + N`. In addition, the expiration must be at least 3 minutes
 *  in the future — orders expiring sooner are rejected."
 */
export const EXPIRY_GRACE_SECONDS = 60;
export const EXPIRY_MIN_LEAD_SECONDS = 180;

export const EXPIRY_OPTIONS = [
  "Never",
  "5m",
  "1h",
  "12h",
  "24h",
  "End of day",
] as const;

/** One of the menu's own labels -- not `string`. The server validates
 *  order_type/expiration together and rejects anything it doesn't recognise,
 *  so a UI that accepted an arbitrary string here could silently degrade an
 *  unrecognised label to GTC/never instead of erroring, which is exactly the
 *  silent failure the server's own validator refuses to allow. Typing this
 *  as a member of EXPIRY_OPTIONS turns a typo'd label into a compile error
 *  instead. */
export type ExpiryLabel = (typeof EXPIRY_OPTIONS)[number];

const SECONDS: Record<string, number> = {
  "5m": 300,
  "1h": 3600,
  "12h": 43200,
  "24h": 86400,
};

function lifetimeSeconds(label: ExpiryLabel, nowMs: number): number | null {
  if (label === "Never") return null;
  if (label === "End of day") {
    const midnight = new Date(nowMs);
    midnight.setHours(24, 0, 0, 0);
    // Floor midnight and now SEPARATELY, then subtract -- not the gap first.
    // `expiryForLabel` below floors `nowMs` again when it adds this lifetime
    // back to `now`, so flooring the gap here too double-counts whatever
    // sub-second remainder `nowMs` carries, landing ~1s before midnight.
    // Flooring each side once and subtracting cancels that out exactly.
    return Math.floor(midnight.getTime() / 1000) - Math.floor(nowMs / 1000);
  }
  return SECONDS[label] ?? null;
}

export function expiryForLabel(
  label: ExpiryLabel,
  nowMs: number,
): { order_type: "GTC" | "GTD"; expiration: number } {
  const lifetime = lifetimeSeconds(label, nowMs);
  if (lifetime === null) return { order_type: "GTC", expiration: 0 };
  return {
    order_type: "GTD",
    expiration: Math.floor(nowMs / 1000) + EXPIRY_GRACE_SECONDS + lifetime,
  };
}

/** True when the choice cannot be honoured — only "End of day", and only in
 *  the last minutes before midnight, where the request would be refused. */
export function isExpiryDisabled(label: ExpiryLabel, nowMs: number): boolean {
  const lifetime = lifetimeSeconds(label, nowMs);
  if (lifetime === null) return false;
  return EXPIRY_GRACE_SECONDS + lifetime < EXPIRY_MIN_LEAD_SECONDS;
}
