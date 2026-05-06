#!/usr/bin/env bash
# Fund an address with USDC.e on the forked chain by impersonating a whale.
# Usage:
#   ./scripts/fund_address.sh                       # funds $ADMIN with 1M USDC.e
#   ./scripts/fund_address.sh 0xRECIPIENT
#   ./scripts/fund_address.sh 0xRECIPIENT 50000     # 50,000 USDC.e
#
# Default whale is Aave V3's aPolUSDC custody contract on Polygon. If its
# balance at your fork block is too low, set WHALE in .env to any other
# address holding enough USDC.e (e.g. a DEX pool, bridge, or treasury).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTPIT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$AGENTPIT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

for var in RPC_URL COLLATERAL ADMIN; do
  if [ -z "${!var:-}" ]; then
    echo "Error: $var is not set in $ENV_FILE" >&2
    exit 1
  fi
done

if ! command -v cast >/dev/null 2>&1; then
  echo "Error: cast not found. Install Foundry." >&2
  exit 1
fi

RECIPIENT="${1:-$ADMIN}"
AMOUNT_USDC="${2:-1000000}"

# USDC.e has 6 decimals
AMOUNT="$(echo "$AMOUNT_USDC * 1000000" | bc)"

# Aave V3 aPolUSDC custody contract on Polygon — reliably holds large USDC.e.
WHALE="${WHALE:-0x625E7708f30cA75bfd92586e17077590C60eb4cD}"

echo "Funding $RECIPIENT with $AMOUNT_USDC USDC.e (raw: $AMOUNT)"
echo "  whale: $WHALE"

WHALE_BAL="$(cast call "$COLLATERAL" "balanceOf(address)(uint256)" "$WHALE" --rpc-url "$RPC_URL" | awk '{print $1}')"

if [ "$(echo "$WHALE_BAL >= $AMOUNT" | bc)" != "1" ]; then
  echo "Error: whale balance $WHALE_BAL is less than required $AMOUNT" >&2
  echo "Set WHALE in .env to a different USDC.e holder." >&2
  exit 1
fi

# Give the whale native MATIC so it can pay gas for the transfer.
cast rpc anvil_setBalance "$WHALE" 0xde0b6b3a7640000 --rpc-url "$RPC_URL" >/dev/null

cast rpc anvil_impersonateAccount "$WHALE" --rpc-url "$RPC_URL" >/dev/null
cast send "$COLLATERAL" "transfer(address,uint256)" "$RECIPIENT" "$AMOUNT" \
    --from "$WHALE" --unlocked --rpc-url "$RPC_URL" >/dev/null
cast rpc anvil_stopImpersonatingAccount "$WHALE" --rpc-url "$RPC_URL" >/dev/null

NEW_BAL="$(cast call "$COLLATERAL" "balanceOf(address)(uint256)" "$RECIPIENT" --rpc-url "$RPC_URL" | awk '{print $1}')"
echo "Done. $RECIPIENT USDC.e balance: $NEW_BAL"
