import { shortAddress } from "@/lib/format";

/**
 * Maps a failed `POST /positions/claim` response to user-facing copy.
 *
 * 402 is the claim path's own domain error: `PositionService.redeem` catches
 * web3's `Web3RPCError` when the wallet can't cover the transaction's gas
 * and re-raises `InsufficientGasError`, which the API maps to 402 rather
 * than the generic 400 every other business-rule failure gets. That status
 * alone is enough to tell "you need to fund this wallet" apart from
 * anything else that can go wrong claiming a position — no need to parse
 * the backend's detail text, which states the technical fact (gas) rather
 * than the product's own vocabulary for it (credits).
 *
 * The interface already knows the account's own address (`userAddress`),
 * so it composes the full instruction itself instead of relying on the
 * backend to embed it in a sentence meant for logs, not people. Shown
 * short, the same way the address reads everywhere else in the app (the
 * profile header, Settings) — a toast is not where a 42-character hex
 * string belongs, and the full value is always one click away on either
 * of those pages.
 */
export function claimErrorMessage(
  status: number | undefined,
  userAddress: string,
): string {
  if (status === 402) {
    return `Needs credits to claim. Send some to ${shortAddress(userAddress)}.`;
  }
  return "Failed to claim.";
}
