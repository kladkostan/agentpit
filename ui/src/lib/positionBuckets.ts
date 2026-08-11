/** Which of the three states a position is in.
 *
 *  A position is open, or it is closed, or it is decided but not collected.
 *  The third had no name, so settled money sat under "active" — priced by a
 *  market that can no longer be traded. */
export function positionBucket(p: { redeemable: boolean }): "unclaimed" | "active" {
  return p.redeemable ? "unclaimed" : "active";
}

/** What the account is owed and has not collected, in dollars. */
export function unclaimedTotal(
  positions: readonly { redeemable: boolean; currentValue: number }[],
): number {
  return positions.reduce(
    (sum, p) => (p.redeemable ? sum + p.currentValue : sum),
    0,
  );
}
