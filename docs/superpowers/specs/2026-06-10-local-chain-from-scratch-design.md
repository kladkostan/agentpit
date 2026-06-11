# Local chain from scratch + ctf-exchange as a submodule

**Date:** 2026-06-10
**Status:** Approved (design)

## Problem

agentpit's local on-chain stack currently depends on Polygon in two ways that
make it fragile and externally-coupled:

1. **The node forks Polygon mainnet.** [`scripts/run_node.sh`](../../../scripts/run_node.sh)
   runs `anvil --fork-url $POLYGON_RPC`, and three contracts the deploy step
   does *not* build are inherited "for free" from the fork:

   | `.env` var | Contract | Used by |
   | --- | --- | --- |
   | `CTF` | Gnosis **ConditionalTokens** (ERC1155) | `splitPosition`/`mergePositions` in the exchange's `AssetOperations`, plus `prepareCondition`/`reportPayouts`/`redeemPositions`/`balanceOf` from Python `onchain/admin.py` |
   | `PROXY_FACTORY` | Polymarket proxy-wallet factory | proxy-wallet signature validation only |
   | `SAFE_FACTORY` | Gnosis Safe factory | safe-wallet signature validation only |

   The fork needs a live Polygon RPC, is non-deterministic across restarts, and
   ties local dev to a third party.

2. **Contract sources live in a sibling directory.** The deploy script shells
   into `../ctf-exchange` (a working copy of `Polymarket/ctf-exchange` with
   uncommitted agentpit-specific edits). There is no pinned, reproducible source
   of the contracts inside agentpit.

## Goal

- Local node is a **clean anvil chain** — no Polygon fork, no `POLYGON_RPC`.
- **Every contract is deployed from scratch**, including ConditionalTokens.
- Contract sources are **vendored as a git submodule** on the user's fork
  `yavrsky/ctf-exchange`, pinned to a commit — reproducible from a fresh clone.
- The new-user registration flow (faucet drip + approvals) keeps working.

## Key findings that shape the design

- **Only ConditionalTokens actually needs deploying.** Its full creation
  bytecode is already committed in the fork as
  `artifacts/ConditionalTokens.json` (Truffle-style artifact, `bytecode` is a
  hex string). No source compilation, no `conditional-tokens-contracts`
  submodule. The contract is self-contained (its own ERC1155, no ERC1820
  dependency), so the bytecode deploys standalone.

- **Signatures are EOA-only** (`signatureType = 0`, `onchain/order_signer.py`).
  `PROXY_FACTORY`/`SAFE_FACTORY` are consulted by `PolyFactoryHelper` *only* for
  proxy/safe signature types, which agentpit never produces. They can be
  `address(0)`. (`deployAgentpitStack` even documents "use 0x0 for local".)

- **The Faucet is independent of the CTF.** `Faucet.drip(to)` mints
  `AgentpitUSD`, a standalone 6-decimal ERC20 whose minter role is rotated to
  the Faucet at deploy time. Nothing in the faucet/token touches CTF, the fork,
  the factories, or chain id. The registration path
  (`auth_service._run_onboarding`: `fund_gas` → `faucet_drip` →
  `grant_user_approvals`) is unaffected. `grant_user_approvals` does call
  `ctf.setApprovalForAll` / `usd.approve(ctf)`, which the locally-deployed
  ConditionalTokens supports identically to the forked one. **The only way a
  submodule could break the faucet is if the contract sources were missing** —
  verified that `yavrsky/ctf-exchange@main` already contains `AgentpitUSD.sol`,
  `Faucet.sol`, `deployAgentpitStack`, and the ConditionalTokens artifact.

- **token ids do not depend on the CTF address.** `conditionId` derives from
  `(oracle, questionId, slotCount)`; `positionId` from `(collateral, collectionId)`.
  Swapping the CTF address changes nothing about how markets/tokens are computed
  — markets are created fresh on each deploy regardless.

- **`yavrsky/ctf-exchange` `.gitmodules` is not pruned** — it lists 12 nested
  submodules; the forge build needs only 4 (`forge-std`, `openzeppelin-contracts`,
  `solmate`, `solady`, per `remappings.txt` + `Script.sol`). A naive
  `--init --recursive` would pull all 12. Resolution: selective init of the 4.

- **One test depends on the fork.** [`tests/onchain/test_web3_poa.py`](../../../tests/onchain/test_web3_poa.py)
  reads historical Polygon block `80_000_000` (served through the fork) to assert
  the PoA middleware is installed. That block does not exist on a clean chain, so
  the test must be re-targeted (see Part D).

## Design

### Part A — vendor ctf-exchange as a submodule

1. Add the submodule at **`vendor/ctf-exchange`**:
   `git submodule add https://github.com/yavrsky/ctf-exchange.git vendor/ctf-exchange`.
   This pins the gitlink to the fork's current `main` (`0b71874`) and creates
   `.gitmodules` in agentpit. Reproducible; update later with an explicit pull.
2. Initialize **only the 4 needed nested libs**:
   `git -C vendor/ctf-exchange submodule update --init lib/forge-std lib/openzeppelin-contracts lib/solmate lib/solady`.
   The other 8 stay uninitialized — forge never imports them, so the build never
   reads them.

### Part B — clean node (no fork)

3. `scripts/run_node.sh`: drop `--fork-url`, the `POLYGON_RPC` requirement, and
   the `FORK_BLOCK` logic. Body becomes:
   `anvil --host 127.0.0.1 --port 8545 --chain-id 31337`.
   **Use chain id 31337** (anvil's default). The chain id is not load-bearing —
   order signing reads it from `local.json` (`deployment.chain_id`) and the web3
   client verifies node == local.json — and 31337 keeps forge's per-deploy
   broadcast logs out of git, since the vendored ctf-exchange `.gitignore`
   already excludes `broadcast/*/31337/` (but not `/137/`, which it treats as a
   real-Polygon deployment record).

### Part C — deploy

4. `scripts/deploy_exchange.sh`:
   - `CTF_EXCHANGE_DIR` default → `$AGENTPIT_DIR/vendor/ctf-exchange`
     (env override retained).
   - Idempotent guard: if the submodule is not checked out or the 4 libs are
     missing, auto-run `git submodule update --init` for them, so a fresh
     `git clone` of agentpit + one script "just works".
   - Deploy ConditionalTokens from the artifact (zero-arg constructor):
     ```bash
     CTF_BYTECODE=$(jq -r '.bytecode' "$CTF_EXCHANGE_DIR/artifacts/ConditionalTokens.json")
     CTF=$(cast send --private-key "$PK" --rpc-url "$RPC_URL" --create "$CTF_BYTECODE" --json | jq -r .contractAddress)
     ```
     If `.bytecode` is an object rather than a string, read `.bytecode.object`.
   - Set `PROXY_FACTORY=0x0000000000000000000000000000000000000000` and
     `SAFE_FACTORY=0x0000000000000000000000000000000000000000`.
   - The existing call
     `deployAgentpitStack($ADMIN, $CTF, $PROXY_FACTORY, $SAFE_FACTORY, $SIGNUP_GRANT_RAW)`
     is unchanged. **No Solidity changes.**
   - Write the freshly-deployed `ctf` and zero factories into
     `deployments/local.json` (all other keys unchanged).
   - Narrow the required-env check to `PK ADMIN RPC_URL`.

### Part D — config and the fork-dependent test

5. `.env` / `.env.example`: remove `POLYGON_RPC`, `FORK_BLOCK`, `COLLATERAL`,
   `CTF`, `PROXY_FACTORY`, `SAFE_FACTORY`. Keep `PK`, `ADMIN`, `RPC_URL`, and
   optional `SIGNUP_GRANT_RAW`.
6. `tests/onchain/test_web3_poa.py`: re-target from "read Polygon block 80M" to
   "assert `ExtraDataToPOAMiddleware` is injected into `web3.middleware_onion`".
   The middleware stays in `web3_client.py` (still needed by the polymarket-sync
   path against real Polygon); only its fork-based test changes.
7. Docs: replace any "clone ctf-exchange as a sibling" instruction with the
   submodule init commands.

### Out of scope (explicitly unchanged)

- Solidity contracts, contract ABIs, and the Python `onchain/contracts.py` /
  `deployment.py` shapes.
- `agentpit/polymarket/conditional_token_framework.py` `_FALLBACK_CTF_ADDRESS`
  (= real Polygon `0x4D97…`) — that is the **polymarket-sync** path reading real
  Polygon data, a separate concern from the local chain.
- Deploying real proxy/safe factories — not needed for EOA flows (YAGNI). If
  proxy/safe wallet flows are ever added, deploy them then.

## Data flow (unchanged for consumers)

`run_node.sh` (clean anvil, chain 31337) → `deploy_exchange.sh`
(ConditionalTokens → AgentpitUSD → Faucet → CTFExchange) →
`deployments/local.json` (same keys; `ctf` now local, factories `0x0`) → Python
loads it exactly as before.

## Verification

1. `./scripts/run_node.sh` (clean node, no Polygon RPC needed).
2. `./scripts/deploy_exchange.sh` (deploys all four contracts, writes local.json).
3. `pytest tests/onchain` — exercises split/merge/fill/match/resolution/redeem
   (proves the artifact-deployed CTF is functional) and
   `test_balance_allowance.py::test_collateral_balance_is_signup_grant` (proves
   the faucet grant lands). The suite self-skips if the node is down.
4. `python scripts/mirror_smoke.py`.
5. New PoA test passes without a fork.

## Risks

- **Uncommitted local edits in `../ctf-exchange`** (untracked `AgentpitUSD.sol`/
  `Faucet.sol`, modified `ExchangeDeployment.s.sol`) leave the loop — the deploy
  will use the fork's version. Before starting, diff the local working tree
  against `yavrsky/ctf-exchange@main` so nothing intended is lost.
- **chain id 31337** (anvil's default) is used rather than 137: the chain id is
  not load-bearing (signing reads it from `local.json`), and 31337 keeps forge's
  per-deploy broadcast logs gitignored in the vendored submodule (the fork's
  `.gitignore` excludes `broadcast/*/31337/` but not `/137/`).
- **`cast --create` with large bytecode** — ConditionalTokens deploys on mainnet,
  so the size limit is fine on anvil too.
