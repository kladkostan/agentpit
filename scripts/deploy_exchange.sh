#!/usr/bin/env bash
# Deploy the agentpit local stack (AgentpitUSD + Faucet + CTFExchange) to the local forked node.
# Usage: ./scripts/deploy_exchange.sh
#
# Requires the node from run_node.sh to be running on RPC_URL.
# Writes all resulting addresses to agentpit/deployments/local.json so the
# Python side can load them.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTPIT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$AGENTPIT_DIR/.env"
CTF_EXCHANGE_DIR="${CTF_EXCHANGE_DIR:-$AGENTPIT_DIR/../ctf-exchange}"

# Faucet drip amount: 1,000,000 apUSD (6 decimals) = 1_000_000_000_000.
SIGNUP_GRANT_RAW="${SIGNUP_GRANT_RAW:-1000000000000}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found. Copy .env.example and edit." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

for var in PK ADMIN RPC_URL CTF PROXY_FACTORY SAFE_FACTORY; do
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

echo "Deploying agentpit stack to $RPC_URL"
echo "  deployer:      $DEPLOYER"
echo "  admin:         $ADMIN"
echo "  ctf:           $CTF"
echo "  proxy_factory: $PROXY_FACTORY"
echo "  safe_factory:  $SAFE_FACTORY"
echo "  signup grant:  $SIGNUP_GRANT_RAW raw apUSD"
echo

# Fund the deployer with 10,000 native MATIC on the local fork so it has gas.
# 0x21E19E0C9BAB2400000 == 10_000 * 1e18.
cast rpc anvil_setBalance "$DEPLOYER" 0x21E19E0C9BAB2400000 --rpc-url "$RPC_URL" >/dev/null

OUTPUT="$(cd "$CTF_EXCHANGE_DIR" && forge script ExchangeDeployment \
    --private-key "$PK" \
    --rpc-url "$RPC_URL" \
    --json \
    --broadcast \
    -s "deployAgentpitStack(address,address,address,address,uint256)" \
    "$ADMIN" "$CTF" "$PROXY_FACTORY" "$SAFE_FACTORY" "$SIGNUP_GRANT_RAW")"

# The script returns (address usd, address faucet, address exchange).
# forge --json prints the returns map; pick fields by their declared names.
RETURNS_JSON="$(echo "$OUTPUT" | grep -E '^\{' | jq -c 'select(.returns)' 2>/dev/null | head -n1)"

if [ -z "$RETURNS_JSON" ]; then
  echo "Failed to parse forge output." >&2
  echo "Raw output:" >&2
  echo "$OUTPUT" >&2
  exit 1
fi

USD="$(echo "$RETURNS_JSON" | jq -r '.returns.usd.value')"
FAUCET="$(echo "$RETURNS_JSON" | jq -r '.returns.faucet.value')"
EXCHANGE="$(echo "$RETURNS_JSON" | jq -r '.returns.exchange.value')"

for var in USD FAUCET EXCHANGE; do
  if [ -z "${!var}" ] || [ "${!var}" = "null" ]; then
    echo "Failed to extract $var from forge output." >&2
    echo "Raw output:" >&2
    echo "$OUTPUT" >&2
    exit 1
  fi
done

echo "AgentpitUSD deployed: $USD"
echo "Faucet      deployed: $FAUCET"
echo "Exchange    deployed: $EXCHANGE"

mkdir -p "$AGENTPIT_DIR/deployments"
cat > "$AGENTPIT_DIR/deployments/local.json" <<EOF
{
  "chain_id": 137,
  "rpc_url": "$RPC_URL",
  "admin": "$ADMIN",
  "usd": "$USD",
  "faucet": "$FAUCET",
  "ctf": "$CTF",
  "proxy_factory": "$PROXY_FACTORY",
  "safe_factory": "$SAFE_FACTORY",
  "exchange": "$EXCHANGE",
  "signup_grant_raw": "$SIGNUP_GRANT_RAW"
}
EOF

echo "Wrote $AGENTPIT_DIR/deployments/local.json"
