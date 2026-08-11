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
# The base fee SKALE on Base reports (47.619 gwei), so a chain built from
# scratch starts at the price the app is heading for rather than anvil's ~2
# gwei default.
#
# It only bites on a FRESH chain. With --state loading an existing chain the
# flag is ignored: the loaded block carries its own base fee, and EIP-1559 then
# decays it 12.5% per under-full block — measured here, 47.6 gwei falls back to
# 0.87 over thirty empty blocks. There is no anvil flag that pins it, and
# --gas-price does not help because send_user_tx builds type-2 transactions
# (agentpit/onchain/user_wallet.py:82) whose cost follows the block's base fee.
#
# So do not read a local wei figure as a SKALE wei figure. Read the GAS, which
# is exact and identical on both, and multiply.
exec anvil \
  --host 127.0.0.1 \
  --port 8545 \
  --chain-id 31337 \
  --block-base-fee-per-gas 47619047620 \
  --state /Users/yavorsky/dev/agentpit/.anvil-state.json \
  --state-interval 30
