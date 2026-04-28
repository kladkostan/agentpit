# AgentPit — Product Requirements Document
**Version:** 1.0  
**Date:** 2026-04-28  
**Status:** Living document
---
## 1. Purpose
This document defines what AgentPit is, why it exists, who uses it, and what it must do. It is the primary reference for product decisions and the starting point for any engineer joining the project.
---
## 2. Problem Statement
Building and testing AI agents that trade on Polymarket prediction markets is hard because:
1. **Real money is at risk.** Every API call that posts a wrong order costs real USDC.
2. **Rate limits and API costs.** Iterating quickly against the live Polymarket CLOB API is slow and expensive.
3. **No local order book.** There is no way to run a realistic multi-agent simulation without a live counterparty.
4. **Resolution is slow.** Real markets resolve in days or weeks; a test cycle cannot wait.
5. **No replay / determinism.** Live market data is non-deterministic; reproducing a bug requires exact market state.
6. **LLM agent integration gap.** Existing Polymarket tooling has no integration layer for LLM-driven agents with memories, channels, and scheduled tasks.
---
## 3. Goals
| # | Goal | Success criterion |
|---|------|------------------|
| G1 | Replicate the Polymarket trading surface locally | All `py_clob_client` order calls work identically with `host=""` |
| G2 | Run multi-agent market simulations without real money | `mint_usdc` provides unlimited test collateral; tokens are simulated in SQLite |
| G3 | Sync real Polymarket markets into the local DB | `fetch_and_sync_polymarket_markets` imports all live markets ≥ $1M liquidity |
| G4 | Mirror real market resolution on-chain | Local market states update to RESOLVED via CTF contract reads |
| G5 | Give AI agents a persistent, structured trading environment | `nanobot/` agents interact with AgentPit via REST; state persists across sessions |
| G6 | Require zero infrastructure to run | Single `uvicorn` command, SQLite only, no Docker / Redis / Postgres |
| G7 | Let agents switch seamlessly between simulation and live trading | One constructor argument (`host=""` vs `host=URL`) changes the mode |
---
## 4. Non-Goals
- **Not a production trading system.** AgentPit is a research and development tool, not a high-availability exchange.
- **Not a blockchain node.** All token mechanics are simulated in SQLite. Only CTF resolution reads hit the real chain.
- **Not a multi-tenant SaaS.** There is no authentication layer, user isolation at the DB level, or rate limiting.
- **Not a Polymarket fork.** AgentPit does not replicate Polymarket's full fee model, liquidity provider incentives, or neg-risk markets beyond what `py_clob_client` already supports.
- **Not a real-time system.** Market state updates are pull-based (sync on demand or via cron), not pushed via WebSocket.
---
## 5. Users
### Primary — AI Agent Engineers
Engineers building LLM-powered trading agents using `nanobot/`. They need to:
- Iterate on agent strategy in a safe sandbox before deploying live.
- Run many agents in parallel against shared simulated markets.
- Inspect trade history, portfolios, and P&L without connecting to Polymarket.
### Secondary — Polymarket Strategy Researchers
Quantitative researchers who want to backtest strategies against real market structures (questions, outcomes, liquidity) without live execution risk.
### Tertiary — Framework Contributors
Engineers extending `nanobot/` with new skills, channels, or providers who need a running AgentPit server as a dependency for integration tests.
---
## 6. Functional Requirements
### 6.1 Market Management
| ID | Requirement |
|----|-------------|
| MKT-1 | Create a market with a question, description, and 2–N outcome tokens. A `condition_id` is auto-computed from the question text. |
| MKT-2 | Markets follow a strict state machine: `DRAFT → ACTIVE → CLOSED → RESOLVED` (or `CANCELLED` from any pre-resolution state). |
| MKT-3 | Invalid state transitions (e.g. DRAFT → CLOSE) return `400` with a descriptive message. |
| MKT-4 | A market can be resolved by specifying the 0-based winning outcome index. |
| MKT-5 | Cancelling a market automatically refunds all users who hold complete sets of outcome tokens. |
| MKT-6 | Markets can be listed with `limit`/`offset` pagination. |
| MKT-7 | A market can be fetched by its integer `market_id`. Returns `404` if not found. |
### 6.2 Simulated Token Economy
| ID | Requirement |
|----|-------------|
| TOK-1 | Any user can mint unlimited simulated USDC via `POST /mint_usdc`. No supply cap. |
| TOK-2 | USDC balances and outcome token holdings are stored per-user as hex-encoded `uint256` values in SQLite. |
| TOK-3 | `split_position`: burn N USDC → receive N of each outcome token (complete set purchase). |
| TOK-4 | `merge_positions`: burn N of each outcome token → receive N USDC (complete set sale). |
| TOK-5 | `redeem_position` (post-resolution): burn all tokens → receive N USDC per winning token held. Losing tokens pay nothing. |
| TOK-6 | All token operations are atomic (SQLite `with db:` transactions). Partial states are not possible. |
| TOK-7 | Insufficient balance errors return `400` with the exact shortfall (`have X, need Y`). |
| TOK-8 | USDC can be transferred between Ethereum addresses via `POST /transfer_usdc`. |
### 6.3 Order Book and Matching
| ID | Requirement |
|----|-------------|
| ORD-1 | Accept Polymarket-compatible EIP-712 signed orders via `ClobClient.post_order()`. |
| ORD-2 | Support all four Polymarket order types: GTC, GTD, FOK, FAK. |
| ORD-3 | Match orders using price-time priority (CLOB semantics). |
| ORD-4 | FOK orders are dry-run matched first; they cancel entirely if any remainder would exist. |
| ORD-5 | FAK orders fill as much as possible; unfilled remainder is immediately cancelled. |
| ORD-6 | GTD orders expire automatically (lazily swept on each new order submission). |
| ORD-7 | Order IDs are EIP-712 struct hashes — identical to Polymarket's order ID scheme. |
| ORD-8 | Individual and batch order cancellation via `ClobClient.cancel()` / `cancel_orders()`. |
| ORD-9 | Confirmed trades are recorded in the `trades` table with price, size, and timestamp. |
### 6.4 Polymarket Sync
| ID | Requirement |
|----|-------------|
| SYN-1 | Fetch all live Polymarket markets from the Gamma API with pagination (500/page). |
| SYN-2 | Filter out markets without a `condition_id`, below $1M liquidity, expired, or archived. |
| SYN-3 | Skip any market whose `condition_id` does not exist on the Polygon CTF contract. |
| SYN-4 | Sync is idempotent — re-running creates zero duplicate markets. |
| SYN-5 | `MARKET_STATE` is updated for all synced markets: query CLOB API for `closed`, query CTF for resolution. |
| SYN-6 | Sync is one-directional (Polymarket → local). Local market state is never written back. |
| SYN-7 | Field name inconsistencies in the Gamma API (camelCase/snake_case/aliases) are normalised transparently. |
### 6.5 Portfolio and History
| ID | Requirement |
|----|-------------|
| PRT-1 | `GET /portfolio/{api_key}` returns current USDC balance and all non-zero outcome token positions across all markets. |
| PRT-2 | `GET /markets/history/{api_key}` returns a chronological log of all SPLIT, MERGE, and REDEEM transactions. |
| PRT-3 | Each transaction record includes the type, market, amount, and type-specific details (collateral burned/minted, payout). |
### 6.6 Agents and Personalities
| ID | Requirement |
|----|-------------|
| AGT-1 | Create named personality profiles (`beliefs`, `methods`, `needs`) that drive agent behaviour. |
| AGT-2 | Create agents linked to an existing personality. Each agent has mutable `state`, `history`, and `todo` fields. |
| AGT-3 | Personality and agent creation return `409` on duplicate IDs; agent creation returns `404` for missing personality. |
### 6.7 Users
| ID | Requirement |
|----|-------------|
| USR-1 | Create a user with a unique `user_id` (1–15 alphanumeric/underscore chars). |
| USR-2 | Each user gets a UUID `api_key` and a freshly generated Ethereum keypair. |
| USR-3 | Duplicate `user_id` returns `409`. Invalid handle returns `400`. |
---
## 7. Non-Functional Requirements
### 7.1 Correctness
| ID | Requirement |
|----|-------------|
| NF-1 | Token balances must never go negative. Underflow is caught by `check_state` before any DB write. |
| NF-2 | `uint256` overflow is caught and raises `OverflowError`. |
| NF-3 | All DB writes are wrapped in SQLite transactions. Any exception rolls back the entire operation. |
| NF-4 | Errors propagate — no silent exception swallowing anywhere in the stack. |
### 7.2 Consistency
| ID | Requirement |
|----|-------------|
| NF-5 | All write endpoints hold a `ReaderWriterLock` exclusive lock during DB access. |
| NF-6 | Read endpoints hold a shared lock, allowing concurrent reads. |
| NF-7 | The DB module boundary is enforced: `table_read` never writes; `table_write` never does unguarded reads. |
### 7.3 Compatibility
| ID | Requirement |
|----|-------------|
| NF-8 | Order IDs, EIP-712 signatures, and price encoding must be byte-for-byte compatible with Polymarket. |
| NF-9 | `py_clob_client` API surface is unchanged from upstream — local routing is invisible to callers. |
| NF-10 | Condition IDs computed locally (EasyNet oracle) must not collide with Polymarket condition IDs. |
### 7.4 Developer Experience
| ID | Requirement |
|----|-------------|
| NF-11 | Full setup in two commands: `make init` + `uvicorn …`. |
| NF-12 | All tests run against in-memory SQLite — no external services needed for the standard suite. |
| NF-13 | `400` errors from `check_state` include the source file, line number, and failing expression. |
| NF-14 | Live log streaming in pytest output (`pytest.ini` `log_cli = true`). |
| NF-15 | Integration tests (live Polymarket API, live Polygon RPC) are isolated behind `@pytest.mark.integration`. |
---
## 8. System Boundaries
```
┌─────────────────────────────────────────────────────────┐
│                  IN SCOPE                               │
│  AgentPit HTTP API        Trading Engine (CLOB)         │
│  Simulated USDC + Tokens  Polymarket Sync (pull only)   │
│  Market Lifecycle         nanobot agent framework       │
│  py_clob_client (local)   SQLite persistence            │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                 OUT OF SCOPE                            │
│  Real USDC / on-chain transactions                      │
│  Polymarket write API (order posting to live exchange)  │
│  High-availability / horizontal scaling                 │
│  User authentication / access control                   │
│  Real-time market data streaming (WebSocket)            │
│  Fee collection / protocol economics                    │
└─────────────────────────────────────────────────────────┘
```
---
## 9. Data Model Summary
| Entity | Key fields | Owned by |
|--------|-----------|---------|
| `Market` | `market_id`, `condition_id`, `erc1155_tokens`, `market_state`, `resolved_outcome` | AgentPit Server |
| `User` | `user_id`, `api_key`, `eth_private_key` | AgentPit Server |
| `ERC-20 balance` | `eth_address → { asset_address: hex_uint256 }` | ERC20Simulator |
| `ERC-1155 balance` | `eth_address → { token_id: hex_uint256 }` | ERC1155Simulator |
| `Transaction` | `api_key`, `type`, `market_id`, `details` | AgentPit Server |
| `Order` | `order_id` (EIP-712), `side`, `price`, `status`, `remaining_amount` | TradingEngine |
| `Trade` | `trade_id`, `taker_order_id`, `maker_orders`, `price`, `trade_size` | TradingEngine |
| `Agent` | `agent_id`, `personality_id`, `state`, `history`, `todo` | AgentPit Server |
| `Personality` | `personality_id`, `title`, `spec (beliefs/methods/needs)` | AgentPit Server |
Full schemas: see [`agentpit_api.md — Database Schema`](agentpit_api.md#database-schema-sqlite).
---
## 10. Integration Points
| System | Direction | Protocol | Purpose |
|--------|-----------|----------|---------|
| Polymarket Gamma API (`gamma-api.polymarket.com`) | Pull | HTTPS/JSON | Fetch market metadata for sync |
| Polymarket CLOB API (`clob.polymarket.com`) | Pull | HTTPS/JSON | Check per-market `closed` status during sync |
| Polygon CTF Contract (`0x4D97DC…`) | Pull | Web3/RPC | Verify condition existence; read resolution payouts |
| `nanobot/` agent framework | Internal | Python function calls / REST | Agents call AgentPit server via HTTP; cron triggers sync |
| `py_clob_client` | Internal | Python in-process | Routes order calls to `TradingEngine` when `host=""` |
---
## 11. Constraints
| Constraint | Detail |
|------------|--------|
| **Python 3.10+** | Uses `match`, `X \| Y` union types, and `list[str]` generics |
| **SQLite only** | No Postgres, Redis, or message queue. Single-file DB. |
| **Single process** | `TradingEngine` and `AgentPitServer` each own their own DB connection and lock. They are not designed for multi-process deployment. |
| **Polygon RPC dependency** | CTF reads require the Tenderly Polygon RPC (`https://tenderly.rpc.polygon.community`). Sync fails if unreachable. |
| **No fee simulation** | `FEE_RATE_BPS` is stored and echoed in trades but no fee is actually deducted from token balances. |
---
## 12. Key Workflows
### Workflow A — Agent Development Cycle
```
1. make init && uvicorn agentpit.fastapi.main:app --reload
2. POST /create_user {"user_id": "agent_alice"}          → api_key
3. POST /mint_usdc   {"api_key": ..., "amount": 100000}  → funded wallet
4. Trigger polymarket sync (manual or via nanobot/cron)  → markets in DB
5. Agent queries GET /markets → picks a market
6. Agent calls POST /split_position                      → holds Yes+No tokens
7. Agent posts limit orders via ClobClient(host="")      → TradingEngine matches
8. Agent redeems after resolution via POST /redeem_position
9. Inspect GET /portfolio and GET /markets/history
10. Iterate strategy; repeat from step 5
```
### Workflow B — Polymarket Sync and State Tracking
```
1. fetch_and_sync_polymarket_markets(db)
   → Gamma API: fetch all markets ≥ $1M liquidity
   → CTF: confirm each condition_id exists on Polygon
   → DB: insert new markets; skip existing
2. For each synced market:
   → CLOB API: is market closed?
   → CTF: is condition resolved? who won?
   → DB: update MARKET_STATE accordingly
3. Schedule via nanobot/cron every N minutes for continuous tracking
```
### Workflow C — Switching from Simulation to Live
```python
# Simulation (local)
client = ClobClient(host="", key=private_key, chain_id=137)
client.set_api_creds(...)
client.post_order(signed_order)           # → TradingEngine
# Live (real Polymarket)
client = ClobClient(host="https://clob.polymarket.com",
                    key=private_key, chain_id=137)
client.set_api_creds(client.create_or_derive_api_creds())
client.post_order(signed_order)           # → Polymarket CLOB API
```
No other code changes required.
---
## 13. Known Limitations and Future Work
| Area | Current Limitation | Potential Improvement |
|------|-------------------|-----------------------|
| **CTF performance** | New Web3 HTTP connection per sync call; no caching | Cache Web3 instance per sync run; use multicall batching |
| **Portfolio query** | O(markets) scan to find token holdings | Add a `positions` index table keyed by `(eth_address, token_id)` |
| **GTD expiry** | Lazy sweep on each new order — stale orders stay in DB until next activity | Background expiry thread or TTL-based sweep |
| **TradingEngine test coverage** | No dedicated unit tests for the matching engine | Add `tests/trading/test_engine.py` with in-memory DB fixtures |
| **PredictionMarket vs server split** | Server bypasses `PredictionMarket` and calls simulators directly (different USDC flow: burn vs. escrow) | Unify both paths through `PredictionMarket` |
| **No neg-risk market support** | Neg-risk CTF markets have different token structures | Extend `ERC1155Simulator` and sync logic for neg-risk |
| **Fee simulation** | `FEE_RATE_BPS` stored but not applied | Deduct fees from taker USDC on fill |
| **Multi-process / scaling** | Single SQLite connection per server instance | Migrate to Postgres for horizontal agent scaling |
| **nanobot docs** | `nanobot/` framework has no spec in `docs/` | Add `nanobot_framework_spec.md` |
---
## 14. Documentation Reference
| Document | What it covers |
|----------|---------------|
| [`high_level_design.md`](high_level_design.md) | Architecture overview, component diagram, data flow, design decisions |
| [`agentpit_api.md`](agentpit_api.md) | All REST endpoints, DB schema, error format, lifecycle walkthrough |
| [`contract_simulators_spec.md`](contract_simulators_spec.md) | ERC-20 / ERC-1155 / PredictionMarket internals |
| [`trading_engine_spec.md`](trading_engine_spec.md) | CLOB matching, order types, price encoding |
| [`polymarket_sync_spec.md`](polymarket_sync_spec.md) | Gamma API sync pipeline, field normalisation, state sync |
| [`conditional_token_framework_spec.md`](conditional_token_framework_spec.md) | On-chain CTF reads and resolution model |
| [`tests_overview.md`](tests_overview.md) | Test map, how to run, coverage gaps |
