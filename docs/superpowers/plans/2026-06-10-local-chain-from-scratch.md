# Local Chain From Scratch + ctf-exchange Submodule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make agentpit's local on-chain stack fully self-contained — a clean anvil chain (no Polygon fork) with every contract (including ConditionalTokens) deployed from scratch, sourced from a pinned `yavrsky/ctf-exchange` git submodule.

**Architecture:** ConditionalTokens is deployed from its committed creation bytecode (`vendor/ctf-exchange/artifacts/ConditionalTokens.json`) via `cast send --create`; AgentpitUSD/Faucet/CTFExchange are deployed by the existing `deployAgentpitStack` forge script (unchanged Solidity) with `address(0)` proxy/safe factories (EOA-only signatures). The node runs `anvil --chain-id 137` with no fork. The contract repo is vendored as a submodule with only its 4 needed nested libs initialized.

**Tech Stack:** bash, Foundry (`anvil`, `cast`, `forge`), git submodules, Python 3.13 + web3 7.16, pytest.

---

## Background the engineer needs

- **Spec:** `docs/superpowers/specs/2026-06-10-local-chain-from-scratch-design.md`. Read it first.
- **What the fork currently supplies for free** (and we are replacing): the Gnosis ConditionalTokens contract (`CTF`), a Polymarket proxy factory, and a Gnosis Safe factory. The collateral is already agentpit's own `AgentpitUSD` (not from the fork).
- **Why factories can be zero:** agentpit only ever signs orders as EOAs (`signatureType = 0`, `agentpit/onchain/order_signer.py`). The factories are only read by `PolyFactoryHelper` for proxy/safe signatures, which never occur. `deployAgentpitStack` already documents "use 0x0 for local".
- **Why no Solidity changes:** the deploy entrypoint `deployAgentpitStack(address admin, address ctf, address proxyFactory, address safeFactory, uint256 signupGrantRaw)` already takes the CTF and factory addresses as parameters. We just feed it a locally-deployed CTF and zero factories.
- **The fork `yavrsky/ctf-exchange@main` already contains** `src/dev/mocks/AgentpitUSD.sol`, `src/dev/mocks/Faucet.sol`, the `deployAgentpitStack` function, and `artifacts/ConditionalTokens.json` (verified). The submodule will pull all of these.
- **Run Python via `.venv/bin/python`** (or `source .venv/bin/activate`). On-chain tests live under `tests/onchain/` and **self-skip** when the node is down or `deployments/local.json` is missing (`tests/onchain/conftest.py`).
- **Commit style:** this repo omits the `Co-Authored-By: Claude` trailer. Keep commits scoped per task.

---

## File map

| Path | Change | Responsibility |
| --- | --- | --- |
| `.gitmodules` | Create (via `git submodule add`) | Pin `vendor/ctf-exchange` → `yavrsky/ctf-exchange@main` |
| `vendor/ctf-exchange` | Create (submodule gitlink) | Vendored contract sources + ConditionalTokens artifact |
| `scripts/run_node.sh` | Rewrite | Boot a clean anvil chain (no fork) |
| `scripts/deploy_exchange.sh` | Rewrite | Ensure submodule, deploy CTF from artifact + the agentpit stack, write `local.json` |
| `.env.example` | Edit | Drop Polygon/fork vars; document the lean local config |
| `.env` | Edit (local, gitignored) | Same trim, keep the developer's real `PK`/`ADMIN` |
| `tests/onchain/test_web3_poa.py` | Rewrite | Assert the PoA middleware is installed without needing a fork |

---

## Task 0: Pre-flight — confirm the fork is the source of truth

**Files:** none (read-only safety check).

The agentpit contract edits in the sibling `../ctf-exchange` working tree are **uncommitted** (untracked `AgentpitUSD.sol`/`Faucet.sol`, modified `ExchangeDeployment.s.sol`). After this plan, deploys use the **fork's** committed version. Confirm nothing newer lives only in the local working tree before cutting over.

- [ ] **Step 1: Diff the local working tree against the fork**

Run:
```bash
cd /Users/yavorsky/dev/ctf-exchange
git fetch -q https://github.com/yavrsky/ctf-exchange.git main
git --no-pager diff FETCH_HEAD -- src/dev/mocks src/exchange/scripts src/common artifacts/ConditionalTokens.json
```
Expected: **empty (no diff)** → the fork already has everything; safe to proceed.

- [ ] **Step 2: If the diff is non-empty**, the local tree has changes not in the fork. STOP and surface the diff to the user: either commit+push those changes to `yavrsky/ctf-exchange@main` first, or confirm they are throwaway. Do not continue until the diff is empty or explicitly waived.

- [ ] **Step 3: Return to the agentpit repo**

Run: `cd /Users/yavorsky/dev/agentpit`

---

## Task 1: Vendor ctf-exchange as a submodule

**Files:**
- Create: `.gitmodules`
- Create: `vendor/ctf-exchange` (submodule gitlink)

- [ ] **Step 1: Add the submodule at `vendor/ctf-exchange`**

Run:
```bash
cd /Users/yavorsky/dev/agentpit
git submodule add https://github.com/yavrsky/ctf-exchange.git vendor/ctf-exchange
```
Expected: clones the fork, checks out `main`, creates `.gitmodules` and a gitlink. (This pins the gitlink to the fork's current `main` commit.)

- [ ] **Step 2: Initialize only the 4 needed nested libs**

Run:
```bash
git -C vendor/ctf-exchange submodule update --init \
  lib/forge-std lib/openzeppelin-contracts lib/solmate lib/solady
```
Expected: those 4 directories populate. The other 8 entries in the fork's `.gitmodules` stay uninitialized — forge does not import them.

- [ ] **Step 3: Verify the contracts compile with just those libs**

Run: `( cd vendor/ctf-exchange && forge build )`
Expected: build succeeds (compiles `CTFExchange`, `AgentpitUSD`, `Faucet`, the deploy script). If it complains about a missing lib, the missing remapped lib name is printed — init that one lib the same way and retry.

- [ ] **Step 4: Verify the ConditionalTokens artifact is present and has string bytecode**

Run:
```bash
jq -r '.bytecode | type' vendor/ctf-exchange/artifacts/ConditionalTokens.json
```
Expected: `string`. (If it prints `object`, note it — Task 3 reads `.bytecode.object` instead of `.bytecode`.)

- [ ] **Step 5: Commit**

```bash
git add .gitmodules vendor/ctf-exchange
git commit -m "build(contracts): vendor yavrsky/ctf-exchange as vendor/ submodule"
```

---

## Task 2: Clean node — drop the Polygon fork

**Files:**
- Rewrite: `scripts/run_node.sh`

- [ ] **Step 1: Replace `scripts/run_node.sh` with a clean-node launcher**

Full new contents:
```bash
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
```

- [ ] **Step 2: Start the node in the background and verify it is a clean chain**

Run (in a scratch terminal / background):
```bash
./scripts/run_node.sh &
sleep 2
cast chain-id --rpc-url http://127.0.0.1:8545
cast block-number --rpc-url http://127.0.0.1:8545
cast code 0x4D97DCd97eC945f40cF65F87097ACe5EA0476045 --rpc-url http://127.0.0.1:8545
```
Expected: chain-id `137`; block-number is low (`0` or single digits); `cast code` for the old Polygon CTF prints `0x` (empty) — proving there is no fork. Leave the node running for the next tasks.

- [ ] **Step 3: Commit**

```bash
git add scripts/run_node.sh
git commit -m "feat(node): run a clean anvil chain instead of forking Polygon"
```

---

## Task 3: Deploy script — deploy CTF from the artifact + the stack

**Files:**
- Rewrite: `scripts/deploy_exchange.sh`

- [ ] **Step 1: Replace `scripts/deploy_exchange.sh` with the from-scratch deploy**

Full new contents:
```bash
#!/usr/bin/env bash
# Deploy the full agentpit stack from scratch to the local clean node:
#   ConditionalTokens (CTF) + AgentpitUSD + Faucet + CTFExchange.
# Usage: ./scripts/deploy_exchange.sh
#
# Requires the node from run_node.sh running on RPC_URL. Nothing is inherited
# from Polygon — the CTF is deployed here from a committed artifact. Writes all
# resulting addresses to agentpit/deployments/local.json for the Python side.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTPIT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$AGENTPIT_DIR/.env"
CTF_EXCHANGE_DIR="${CTF_EXCHANGE_DIR:-$AGENTPIT_DIR/vendor/ctf-exchange}"

# EOA-only signatures → the proxy/safe factories are never invoked. Pass 0x0.
ZERO_ADDR="0x0000000000000000000000000000000000000000"
PROXY_FACTORY="$ZERO_ADDR"
SAFE_FACTORY="$ZERO_ADDR"

# Faucet drip amount: 1,000,000,000 apUSD (6 decimals) = 1_000_000_000_000_000.
SIGNUP_GRANT_RAW="${SIGNUP_GRANT_RAW:-1000000000000000}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found. Copy .env.example and edit." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

for var in PK ADMIN RPC_URL; do
  if [ -z "${!var:-}" ]; then
    echo "Error: $var is not set in $ENV_FILE" >&2
    exit 1
  fi
done

for bin in forge cast jq; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "Error: $bin not found." >&2
    exit 1
  fi
done

# --- Ensure the vendored contract submodule (+ its 4 libs) is checked out -----
# Only auto-init when using the default vendored path; an overridden
# CTF_EXCHANGE_DIR is the caller's responsibility.
if [ "$CTF_EXCHANGE_DIR" = "$AGENTPIT_DIR/vendor/ctf-exchange" ]; then
  if [ ! -f "$CTF_EXCHANGE_DIR/foundry.toml" ]; then
    echo "Initializing vendor/ctf-exchange submodule..."
    git -C "$AGENTPIT_DIR" submodule update --init vendor/ctf-exchange
  fi
  for lib in forge-std openzeppelin-contracts solmate solady; do
    if [ -z "$(ls -A "$CTF_EXCHANGE_DIR/lib/$lib" 2>/dev/null)" ]; then
      git -C "$CTF_EXCHANGE_DIR" submodule update --init "lib/$lib"
    fi
  done
fi

if [ ! -d "$CTF_EXCHANGE_DIR" ]; then
  echo "Error: ctf-exchange not found at $CTF_EXCHANGE_DIR" >&2
  exit 1
fi

DEPLOYER="$(cast wallet address --private-key "$PK")"

echo "Deploying agentpit stack from scratch to $RPC_URL"
echo "  deployer:      $DEPLOYER"
echo "  admin:         $ADMIN"
echo "  proxy_factory: $PROXY_FACTORY (stub)"
echo "  safe_factory:  $SAFE_FACTORY (stub)"
echo "  signup grant:  $SIGNUP_GRANT_RAW raw apUSD"
echo

# Fund the deployer with 10,000 native (0x21E19E0C9BAB2400000 == 10_000 * 1e18).
cast rpc anvil_setBalance "$DEPLOYER" 0x21E19E0C9BAB2400000 --rpc-url "$RPC_URL" >/dev/null

# --- 1. Deploy ConditionalTokens from its committed creation bytecode ---------
CTF_ARTIFACT="$CTF_EXCHANGE_DIR/artifacts/ConditionalTokens.json"
CTF_BYTECODE="$(jq -r 'if (.bytecode | type) == "object" then .bytecode.object else .bytecode end' "$CTF_ARTIFACT")"
if [ -z "$CTF_BYTECODE" ] || [ "$CTF_BYTECODE" = "null" ]; then
  echo "Error: could not read bytecode from $CTF_ARTIFACT" >&2
  exit 1
fi

CTF="$(cast send \
  --private-key "$PK" \
  --rpc-url "$RPC_URL" \
  --json \
  --create "$CTF_BYTECODE" | jq -r .contractAddress)"

if [ -z "$CTF" ] || [ "$CTF" = "null" ]; then
  echo "Error: ConditionalTokens deploy failed (no contractAddress)." >&2
  exit 1
fi
echo "ConditionalTokens deployed: $CTF"

# --- 2. Deploy AgentpitUSD + Faucet + CTFExchange via the forge script --------
OUTPUT="$(cd "$CTF_EXCHANGE_DIR" && forge script ExchangeDeployment \
    --private-key "$PK" \
    --rpc-url "$RPC_URL" \
    --json \
    --broadcast \
    -s "deployAgentpitStack(address,address,address,address,uint256)" \
    "$ADMIN" "$CTF" "$PROXY_FACTORY" "$SAFE_FACTORY" "$SIGNUP_GRANT_RAW")"

RETURNS_JSON="$(echo "$OUTPUT" | grep -E '^\{' | jq -c 'select(.returns)' 2>/dev/null | head -n1)"
if [ -z "$RETURNS_JSON" ]; then
  echo "Failed to parse forge output." >&2
  echo "$OUTPUT" >&2
  exit 1
fi

USD="$(echo "$RETURNS_JSON" | jq -r '.returns.usd.value')"
FAUCET="$(echo "$RETURNS_JSON" | jq -r '.returns.faucet.value')"
EXCHANGE="$(echo "$RETURNS_JSON" | jq -r '.returns.exchange.value')"

for var in USD FAUCET EXCHANGE; do
  if [ -z "${!var}" ] || [ "${!var}" = "null" ]; then
    echo "Failed to extract $var from forge output." >&2
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
```

- [ ] **Step 2: Run the deploy against the running clean node**

Run: `./scripts/deploy_exchange.sh`
Expected: prints `ConditionalTokens deployed: 0x…`, then the USD/Faucet/Exchange addresses, then `Wrote …/deployments/local.json`. No "var is not set" errors (only `PK ADMIN RPC_URL` are required now).

- [ ] **Step 3: Verify the deployed CTF has code and the factories are zero**

Run:
```bash
cast code "$(jq -r .ctf deployments/local.json)" --rpc-url http://127.0.0.1:8545 | head -c 12; echo
jq -r '.proxy_factory, .safe_factory' deployments/local.json
```
Expected: `cast code` prints a non-empty `0x60806040…` prefix (CTF is real); both factories print `0x0000000000000000000000000000000000000000`.

- [ ] **Step 4: Verify the CTF is functional (read a pure view)**

Run:
```bash
cast call "$(jq -r .ctf deployments/local.json)" \
  "getConditionId(address,bytes32,uint256)(bytes32)" \
  "$ADMIN" 0x0000000000000000000000000000000000000000000000000000000000000001 2 \
  --rpc-url http://127.0.0.1:8545
```
Expected: a 32-byte hex condition id (non-revert) — confirms the artifact-deployed ConditionalTokens responds.

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy_exchange.sh
git commit -m "feat(deploy): deploy ConditionalTokens from artifact, stub factories, source from vendor/"
```

---

## Task 4: Trim env config

**Files:**
- Edit: `.env.example` (committed)
- Edit: `.env` (local, gitignored)

- [ ] **Step 1: Rewrite `.env.example`**

Full new contents:
```bash
# FastAPI server
AGENTPIT_DB_PATH=agentpit.db
SYNC=true
LIQUIDITY_ENGINE=true

# Auth — pick a long random string for local dev; rotate per deployment in prod.
JWT_SECRET=<generate with: python -c "import secrets; print(secrets.token_urlsafe(48))">

# Local chain config. Copy to .env and fill in.
# .env is gitignored — never commit real keys here.
#
# The node is a clean anvil chain (scripts/run_node.sh) and every contract,
# including ConditionalTokens, is deployed from scratch (scripts/deploy_exchange.sh)
# from the vendor/ctf-exchange submodule. There is no Polygon fork, so no
# Polygon RPC or mainnet addresses are needed.

# === Deploy config (used by scripts/deploy_exchange.sh) ===
# Anvil prefunded account #0 — well-known dev key. SAFE FOR LOCAL ONLY.
PK=<private-key>
ADMIN=<admin-address>
RPC_URL=http://127.0.0.1:8545

# Optional override for the per-signup faucet grant (default 1,000,000,000 apUSD).
# SIGNUP_GRANT_RAW=1000000000000000
```

- [ ] **Step 2: Trim the local `.env`**

Edit `.env` to remove these now-unused lines: `POLYGON_RPC`, the `FORK_BLOCK` comment, `COLLATERAL`, `CTF`, `PROXY_FACTORY`, `SAFE_FACTORY` (and the "Polygon fork"/"Polygon mainnet addresses" comment headers). **Keep** the existing `AGENTPIT_DB_PATH`, `SYNC`, `LIQUIDITY_ENGINE`, `PK`, `ADMIN`, `RPC_URL`, and any `JWT_SECRET`/`SIGNUP_GRANT_RAW` already present. Do not change the real `PK`/`ADMIN` values.

Resulting `.env` shape (values are the developer's existing ones):
```bash
# FastAPI server
AGENTPIT_DB_PATH=agentpit.db
SYNC=true
LIQUIDITY_ENGINE=true

# === Deploy config (used by scripts/deploy_exchange.sh) ===
PK=<existing key, unchanged>
ADMIN=<existing admin, unchanged>
RPC_URL=http://127.0.0.1:8545
```

- [ ] **Step 3: Verify a re-deploy still works with the trimmed env**

Run: `./scripts/deploy_exchange.sh`
Expected: succeeds end-to-end and rewrites `deployments/local.json` (proves no removed var was actually required).

- [ ] **Step 4: Commit**

```bash
git add .env.example
git commit -m "chore(env): drop Polygon fork/mainnet vars from example config"
```
(`.env` is gitignored and not committed.)

---

## Task 5: Re-target the fork-dependent PoA test

**Files:**
- Rewrite: `tests/onchain/test_web3_poa.py`

The old test reads historical Polygon block `80_000_000`, which only exists through the fork. On a clean node it raises "block not found". Replace it with a direct assertion that `Web3Client` installs the PoA middleware (still needed by the polymarket-sync path against real Polygon). Verified that `ExtraDataToPOAMiddleware in web3.middleware_onion` is `True` on web3 7.16.

- [ ] **Step 1: Rewrite the test file**

Full new contents:
```python
"""Regression: the web3 client must install the PoA extraData middleware.

Real Polygon block headers carry >32-byte `extraData`; without
`ExtraDataToPOAMiddleware` web3 v7 raises `ExtraDataLengthError` when the
polymarket-sync path reads a real Polygon block. The local node is no longer a
Polygon fork, so we assert the middleware is installed on our Web3Client
directly rather than by fetching a historical Polygon block.
"""

from web3.middleware import ExtraDataToPOAMiddleware

from agentpit.config import Settings
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client


def test_web3_client_installs_poa_middleware():
    settings = Settings()
    deployment = Deployment.load(settings.deployment_path)
    client = Web3Client(settings, deployment)

    # Without the inject() call in Web3Client.__init__ this is False, and reading
    # any real Polygon block would raise web3.exceptions.ExtraDataLengthError.
    assert ExtraDataToPOAMiddleware in client.web3.middleware_onion
```

- [ ] **Step 2: Run the test (node + deploy from Tasks 2–3 still up)**

Run: `.venv/bin/python -m pytest tests/onchain/test_web3_poa.py -v`
Expected: `test_web3_client_installs_poa_middleware PASSED`. (It would `SKIP` only if the node is down or `local.json` is missing — make sure both are present.)

- [ ] **Step 3: Commit**

```bash
git add tests/onchain/test_web3_poa.py
git commit -m "test(onchain): assert PoA middleware install instead of reading a forked Polygon block"
```

---

## Task 6: Full verification gate

**Files:** none (behavioral gate).

- [ ] **Step 1: Fresh boot from a clean state**

Run (stop any running node first):
```bash
pkill -f "anvil" 2>/dev/null; sleep 1
./scripts/run_node.sh > /tmp/anvil.log 2>&1 &
sleep 2
./scripts/deploy_exchange.sh
```
Expected: node boots clean, deploy prints all four contract addresses and writes `local.json`.

- [ ] **Step 2: Run the full on-chain suite**

Run: `.venv/bin/python -m pytest tests/onchain -q`
Expected: all pass (none skipped). This exercises split/merge/fill/match (`test_trade_flow`, `test_resolution`), the faucet grant (`test_balance_allowance.py::test_collateral_balance_is_signup_grant`), and the mirror suites — proving the artifact-deployed CTF and the from-scratch stack are fully functional and registration/onboarding still works.

- [ ] **Step 3: Run the mirror smoke check**

Run: `.venv/bin/python scripts/mirror_smoke.py`
Expected: completes without error.

- [ ] **Step 4: Sanity-check a clean clone path (optional but recommended)**

Confirm the submodule guard in the deploy script works for a fresh checkout: in a throwaway clone (or after `git -C vendor/ctf-exchange submodule deinit -f lib/forge-std`), re-run `./scripts/deploy_exchange.sh` and confirm it re-initializes the missing lib and still deploys. Re-init afterward if you deinit'd anything.

- [ ] **Step 5: No code commit needed** — this task only verifies. If everything is green, the feature is complete.

---

## Self-review notes (already reconciled)

- **Spec coverage:** Part A (submodule) → Task 1; Part B (clean node) → Task 2; Part C (deploy CTF + stub factories + path) → Task 3; Part D config → Task 4, PoA test → Task 5; verification → Task 6; the "diff local vs fork" risk → Task 0.
- **No Solidity changes:** confirmed — `deployAgentpitStack` already accepts ctf/proxy/safe params.
- **`local.json` shape unchanged:** same keys; only `ctf` (now local) and the two factory values (now `0x0`) differ. `agentpit/onchain/deployment.py` reads them unchanged.
- **Out of scope, untouched:** `agentpit/polymarket/conditional_token_framework.py` `_FALLBACK_CTF_ADDRESS` (real-Polygon sync path), all ABIs, `contracts.py`.
