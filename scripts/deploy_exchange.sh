#!/usr/bin/env bash
# Deploy CTFExchange to the local forked node.
# Usage: ./scripts/deploy_exchange.sh
#
# Requires the node from run_node.sh to be running on RPC_URL.
# Writes the resulting exchange address (and all dependency addresses) to
# agentpit/deployments/local.json so the Python side can load them.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTPIT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$AGENTPIT_DIR/.env"
CTF_EXCHANGE_DIR="${CTF_EXCHANGE_DIR:-$AGENTPIT_DIR/../ctf-exchange}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found. Copy .env.example and edit." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

for var in PK ADMIN RPC_URL COLLATERAL CTF PROXY_FACTORY SAFE_FACTORY; do
  if [ -z "${!var:-}" ]; then
    echo "Error: $var is not set in $ENV_FILE" >&2
    exit 1
  fi
done

if [ ! -d "$CTF_EXCHANGE_DIR" ]; then
  echo "Error: ctf-exchange repo not found at $CTF_EXCHANGE_DIR" >&2
  echo "Clone it as a sibling of agentpit, or set CTF_EXCHANGE_DIR." >&2
  exit 1
fi

if ! command -v forge >/dev/null 2>&1; then
  echo "Error: forge not found. Install Foundry: https://book.getfoundry.sh/getting-started/installation" >&2
  exit 1
fi

DEPLOYER="$(cast wallet address --private-key "$PK")"

echo "Deploying CTFExchange to $RPC_URL"
echo "  deployer:      $DEPLOYER"
echo "  admin:         $ADMIN"
echo "  collateral:    $COLLATERAL"
echo "  ctf:           $CTF"
echo "  proxy_factory: $PROXY_FACTORY"
echo "  safe_factory:  $SAFE_FACTORY"
echo

# Fund the deployer with 10,000 native MATIC on the local fork so it has gas.
# 0x21E19E0C9BAB2400000 == 10_000 * 1e18.
cast rpc anvil_setBalance "$DEPLOYER" 0x21E19E0C9BAB2400000 --rpc-url "$RPC_URL" >/dev/null

OUTPUT="$(cd "$CTF_EXCHANGE_DIR" && forge script ExchangeDeployment \
    --private-key "$PK" \
    --rpc-url "$RPC_URL" \
    --json \
    --broadcast \
    -s "deployExchange(address,address,address,address,address)" \
    "$ADMIN" "$COLLATERAL" "$CTF" "$PROXY_FACTORY" "$SAFE_FACTORY")"

EXCHANGE="$(echo "$OUTPUT" | grep -E '^\{' | jq -r 'select(.returns) | .returns.exchange.value' 2>/dev/null | head -n1)"

if [ -z "$EXCHANGE" ] || [ "$EXCHANGE" = "null" ]; then
  echo "Failed to parse exchange address from forge output." >&2
  echo "Raw output:" >&2
  echo "$OUTPUT" >&2
  exit 1
fi

echo "Exchange deployed: $EXCHANGE"

mkdir -p "$AGENTPIT_DIR/deployments"
cat > "$AGENTPIT_DIR/deployments/local.json" <<EOF
{
  "chain_id": 137,
  "rpc_url": "$RPC_URL",
  "admin": "$ADMIN",
  "collateral": "$COLLATERAL",
  "ctf": "$CTF",
  "proxy_factory": "$PROXY_FACTORY",
  "safe_factory": "$SAFE_FACTORY",
  "exchange": "$EXCHANGE"
}
EOF

echo "Wrote $AGENTPIT_DIR/deployments/local.json"
