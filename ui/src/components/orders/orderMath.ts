export const SLIPPAGE_CAP = 0.02;
export const MIN_PROB = 0.01;
export const MAX_PROB = 0.99;
export const SHARES_SCALE = 1_000_000;

/** Display shares from dollar amount at a price. Returns 0 for invalid inputs. */
export function sharesFromDollars(amount: number, price: number): number {
  if (amount <= 0 || price <= 0) return 0;
  return amount / price;
}

/** Dollar cost of N display shares at a price. */
export function dollarsFromShares(shares: number, price: number): number {
  if (shares <= 0 || price <= 0) return 0;
  return shares * price;
}
