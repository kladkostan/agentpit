#!/usr/bin/env bash
# Run a local anvil node — a clean chain with NO Polygon fork.
# Usage: ./scripts/run_node.sh
#
# The node listens on 127.0.0.1:8545 with chain id 137. Chain id 137 is kept
# (not inherited from any fork) so EIP-712 order signatures and
# deployments/local.json stay byte-identical to before. Every contract is
# deployed from scratch by scripts/deploy_exchange.sh — nothing is inherited
# from Polygon mainnet.

set -euo pipefail

if ! command -v anvil >/dev/null 2>&1; then
  echo "Error: anvil not found. Install Foundry: https://book.getfoundry.sh/getting-started/installation" >&2
  exit 1
fi

echo "Starting clean local node on 127.0.0.1:8545 (chain id 137, no fork)"

exec anvil \
  --host 127.0.0.1 \
  --port 8545 \
  --chain-id 137
