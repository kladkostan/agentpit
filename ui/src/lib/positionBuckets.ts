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

/** Which filter tab is actually showing, correcting for a selection that no
 *  longer applies. Claiming the last unclaimed position drops the total to
 *  zero and, with it, the Unclaimed button itself — staying on that tab
 *  would land on a filter with no button reading as active and nothing in
 *  the list, which reads as "something broke" rather than "you're done".
 *  Falls back to "active" for as long as there is nothing left to claim. */
export function effectivePositionFilter(
  filter: "active" | "unclaimed" | "closed",
  unclaimed: number,
): "active" | "unclaimed" | "closed" {
  return filter === "unclaimed" && unclaimed === 0 ? "active" : filter;
}
