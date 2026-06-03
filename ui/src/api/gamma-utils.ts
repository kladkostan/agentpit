/** Convert an ISO8601 string to unix seconds, or null (null/invalid -> null). */
export function isoToUnix(iso: string | null): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : Math.floor(ms / 1000);
}
