#!/usr/bin/env bash
# Run a local anvil node — a clean chain with NO Polygon fork.
# Usage: ./scripts/run_node.sh
#
# The node listens on 127.0.0.1:8545 with chain id 31337 (anvil's default).
# The chain id is not load-bearing: EIP-712 order signing reads it from
# deployments/local.json (order_signer uses deployment.chain_id) and the web3
# client verifies node == local.json, so any value works as long as the node,
# local.json, and signing agree. 31337 is chosen because the vendored
# ctf-exchange .gitignore already excludes broadcast/*/31337/, so forge's
# per-deploy broadcast logs stay out of git. Every contract is deployed from
# scratch by scripts/deploy_exchange.sh — nothing is inherited from Polygon.

set -euo pipefail

if ! command -v anvil >/dev/null 2>&1; then
  echo "Error: anvil not found. Install Foundry: https://book.getfoundry.sh/getting-started/installation" >&2
  exit 1
fi

echo "Starting clean local node on 127.0.0.1:8545 (chain id 31337, no fork)"

# --state persists the full chain to disk (load on start, dump every 30s + on
# exit) so a crash/restart recovers instead of losing every contract + balance.
# Missing file on first run -> starts fresh and creates it.
exec anvil \
  --host 127.0.0.1 \
  --port 8545 \
  --chain-id 31337 \
  --state /Users/yavorsky/dev/agentpit/.anvil-state.json \
  --state-interval 30
