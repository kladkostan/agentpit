/** Turning the Expires menu into the two fields the API takes.
 *
 *  Two rules from Polymarket, neither guessable from the field names:
 *  an order dies a minute BEFORE its stated expiration, so a client asking
 *  for a lifetime of N sends `now + 60 + N`; and an expiration under three
 *  minutes out is rejected outright.
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

const SECONDS: Record<string, number> = {
  "5m": 300,
  "1h": 3600,
  "12h": 43200,
  "24h": 86400,
};

function lifetimeSeconds(label: string, nowMs: number): number | null {
  if (label === "Never") return null;
  if (label === "End of day") {
    const midnight = new Date(nowMs);
    midnight.setHours(24, 0, 0, 0);
    return Math.floor((midnight.getTime() - nowMs) / 1000);
  }
  return SECONDS[label] ?? null;
}

export function expiryForLabel(
  label: string,
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
export function isExpiryDisabled(label: string, nowMs: number): boolean {
  const lifetime = lifetimeSeconds(label, nowMs);
  if (lifetime === null) return false;
  return EXPIRY_GRACE_SECONDS + lifetime < EXPIRY_MIN_LEAD_SECONDS;
}
