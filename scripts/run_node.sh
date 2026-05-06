#!/usr/bin/env bash
# Run a local anvil node forking Polygon mainnet.
# Usage: ./scripts/run_node.sh
#
# Reads POLYGON_RPC from agentpit/.env. The local node listens on
# 127.0.0.1:8545 and inherits chain id 137 from the fork — so EIP-712 order
# signatures match Polygon mainnet semantics.
#
# To pin the fork to a specific block (for determinism across restarts), add
# FORK_BLOCK=<number> to .env.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTPIT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$AGENTPIT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found. Copy .env.example and edit." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

if [ -z "${POLYGON_RPC:-}" ]; then
  echo "Error: POLYGON_RPC not set in $ENV_FILE" >&2
  exit 1
fi

if ! command -v anvil >/dev/null 2>&1; then
  echo "Error: anvil not found. Install Foundry: https://book.getfoundry.sh/getting-started/installation" >&2
  exit 1
fi

ANVIL_ARGS=(
  --fork-url "$POLYGON_RPC"
  --host 127.0.0.1
  --port 8545
)

if [ -n "${FORK_BLOCK:-}" ]; then
  ANVIL_ARGS+=(--fork-block-number "$FORK_BLOCK")
  echo "Forking Polygon at block $FORK_BLOCK"
else
  echo "Forking Polygon at latest block"
fi

exec anvil "${ANVIL_ARGS[@]}"
