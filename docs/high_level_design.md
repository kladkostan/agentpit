# AgentPit — High-Level Design
## What Is AgentPit?
AgentPit is a **local prediction-market simulation platform** built on top of the Polymarket ecosystem. It lets engineers and AI agents trade outcome tokens, manage markets, and run strategies — entirely offline, against real Polymarket market data — without spending real money or hitting rate limits.
The system has three independent layers that work together:
```
┌──────────────────────────────────────────────────────────────┐
│                     External World                           │
│   Polymarket Gamma API   •   Polymarket CLOB API             │
│   Polygon CTF Contract (on-chain resolution)                 │
└───────────────────────┬──────────────────────────────────────┘
                        │  sync (one-way, pull only)
┌───────────────────────▼──────────────────────────────────────┐
│                   AgentPit Server                            │
│  FastAPI HTTP API  ──►  AgentPitServer (subclasses FastAPI)  │
│                                                              │
│  ┌─────────────────┐   ┌──────────────────┐                 │
│  │ Market Lifecycle │   │ Token Simulation │                 │
│  │ DRAFT→ACTIVE→    │   │ ERC-20  (USDC)   │                 │
│  │ CLOSED→RESOLVED  │   │ ERC-1155 (tokens)│                 │
│  └────────┬────────┘   └────────┬─────────┘                 │
│           │                     │                            │
│           └──────────┬──────────┘                           │
│                      ▼                                       │
│              SQLite Database                                 │
│   (markets, users, orders, trades, tokens, transactions)     │
└──────────────────────────────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│              py_clob_client  +  TradingEngine                │
│  ClobClient(host="") ──► TradingEngine (local CLOB)          │
│  ClobClient(host=URL) ──► Real Polymarket CLOB API           │
└──────────────────────────────────────────────────────────────┘
```
---
## Repository Layout
```
agentpit/
├── fastapi/              # HTTP server (AgentPitServer subclasses FastAPI)
├── db/                   # SQLite layer: table_create, table_read, table_write, table_utils
├── contract_simulators/  # In-process ERC-20 / ERC-1155 / PredictionMarket
├── polymarket/           # Gamma API sync + on-chain CTF reads
├── datastructures/       # Pydantic models (Market, Trade, Order, ...)
├── utils/                # Parsing, condition_id computation
└── trading_engine.py     # In-process CLOB matching engine
py_clob_client/           # Vendored Polymarket client (extended for local mode)
nanobot/                  # AI agent framework (bus, channels, skills, cron, CLI)
tests/                    # pytest suite
docs/                     # This document + component specs
```
---
## Component Overview
### 1. AgentPit Server (`agentpit/fastapi/`)
The HTTP entry point. `AgentPitServer` subclasses `FastAPI` and is both the application and its own router. It owns a single SQLite connection and a `ReaderWriterLock` that serialises writes.
All business logic is thin: the server validates requests, acquires the lock, delegates to `db/`, `contract_simulators/`, or utility code, then returns a typed Pydantic response.
**Exposes:** 20 REST endpoints across markets, USDC, positions, portfolio, agents/personalities.
→ See **[`agentpit_api.md`](agentpit_api.md)** for the full endpoint reference.
---
### 2. SQLite Database (`agentpit/db/`)
All state is stored in a single SQLite file (default: `:memory:` for tests, configurable via `AGENTPIT_DB_PATH`).
The DB layer is split into three modules to keep concerns separate:
| Module | Responsibility |
|--------|---------------|
| `table_create.py` | `CREATE TABLE IF NOT EXISTS` for all 9 tables on startup |
| `table_read.py` | All `SELECT` queries — never writes |
| `table_write.py` | All `INSERT` / `UPDATE` — never reads except to validate preconditions |
| `table_utils.py` | JSON ownership map helpers shared by the simulators |
**Key tables:** `markets`, `users`, `orders`, `trades`, `erc20_token_ownership`, `erc1155_token_ownership`, `transactions`, `agents`, `personalities`.
→ Schema detail in **[`agentpit_api.md` — Database Schema section](agentpit_api.md#database-schema-sqlite)**.
---
### 3. Contract Simulators (`agentpit/contract_simulators/`)
Simulate Ethereum ERC-20 and ERC-1155 token contracts entirely in SQLite — no Web3 calls, no gas.
| Class | What it simulates |
|-------|------------------|
| `ERC20Simulator` | USDC fungible token (mint, burn, transfer, balance) |
| `ERC1155Simulator` | Outcome tokens per market (mint, burn, transfer, balance) |
| `PredictionMarket` | High-level complete-set split/merge orchestrator |
Balances are stored as hex-encoded `uint256` values in JSON ownership maps. All operations are wrapped in SQLite transactions (`with db:`) for atomicity.
→ See **[`contract_simulators_spec.md`](contract_simulators_spec.md)** for full method reference, storage model, and worked examples.
---
### 4. Polymarket Sync (`agentpit/polymarket/`)
A one-directional pull sync from Polymarket into the local DB. Never writes back to Polymarket.
**Two components:**
#### `polymarket_sync.py`
- Paginates the **Gamma API** to fetch live markets (500/page)
- Normalises inconsistent camelCase/snake_case field names
- Verifies each market's `condition_id` exists on-chain before inserting
- Creates missing markets in the local DB
- Updates `MARKET_STATE` (ACTIVE → CLOSED → RESOLVED) by querying the CLOB API and CTF contract
#### `conditional_token_framework.py`
- Read-only Web3 wrapper around the Gnosis CTF contract on Polygon
- `condition_exists()` — guards market creation (unknown conditions are skipped)
- `get_onchain_resolution_status()` — reads `payoutDenominator` + `payoutNumerators` to determine winner
→ See **[`polymarket_sync_spec.md`](polymarket_sync_spec.md)** for the full sync pipeline.  
→ See **[`conditional_token_framework_spec.md`](conditional_token_framework_spec.md)** for on-chain resolution logic.
---
### 5. Trading Engine (`agentpit/trading_engine.py`)
A self-contained SQLite-backed **Central Limit Order Book (CLOB)** engine. Implements price-time priority matching, all four order types (GTC/GTD/FOK/FAK), lazy GTD expiry, and trade recording.
Used exclusively in **local mode** — when `ClobClient` is constructed with `host=""`, all order calls route to `TradingEngine` instead of the live Polymarket API.
```
ClobClient(host="")           →  TradingEngine  (local, in-process)
ClobClient(host="https://...") →  Polymarket CLOB API (remote, HTTP)
```
This makes it transparent to swap between local simulation and live trading without changing agent code.
→ See **[`trading_engine_spec.md`](trading_engine_spec.md)** for matching algorithm, order types, price encoding, and DB schemas.
---
### 6. `py_clob_client` (vendored + extended)
The official Polymarket Python client, vendored into this repo and extended with `# BEGIN_AGENTPIT … # END_AGENTPIT` blocks. When `host == ""`, these blocks intercept API calls and route them to the local `TradingEngine` or `AgentPitServer`.
This allows the same agent code to run against both the local simulation and real Polymarket.
---
### 7. `nanobot/` — Agent Framework
An independent AI agent runtime that is the primary consumer of the AgentPit server. It provides:
| Subsystem | Purpose |
|-----------|---------|
| `bus/` | In-process message bus connecting components |
| `channels/` | Communication adapters (Telegram, Slack, email, CLI, …) |
| `session/` | Conversation and context management |
| `skills/` | Pluggable agent capabilities (web search, code execution, …) |
| `providers/` | LLM provider adapters (OpenAI, Gemini, …) |
| `cron/` | Scheduled task runner (e.g. periodic Polymarket sync) |
| `cli/` | Command-line interface |
`nanobot/` has its own test suite under `tests/morph/`.
---
## Data Flow
### Market Creation and Trading
```
User / Agent
    │
    │  POST /markets
    ▼
AgentPitServer
    │  TableWrite.create_market()  (compute condition_id locally)
    ▼
SQLite: markets table
    │  POST /mint_usdc
    ▼
ERC20Simulator.mint()  →  erc20_token_ownership table
    │  POST /split_position
    ▼
ERC20Simulator.burn(USDC)
ERC1155Simulator.mint(yes_token)
ERC1155Simulator.mint(no_token)
TableWrite.log_transaction(SPLIT)
    →  erc1155_token_ownership + transactions tables
```
### Polymarket Sync
```
nanobot/cron  (or manual call)
    │
    ▼
fetch_and_sync_polymarket_markets(db)
    │
    ├─► Gamma API  →  normalize  →  TableWrite.create_market (is_polygon=True)
    │                                   └── CTF.condition_exists() gating
    │
    └─► for each market with polymarket_id:
            CLOB API  →  closed?   →  update_market_state_to_closed
            CTF       →  resolved? →  update_market_state_to_resolved(winner)
```
### Local Order Matching
```
Agent
    │
    │  ClobClient(host="").post_order(signed_order, GTC)
    ▼
TradingEngine.process_new_order()
    │
    ├── _process_expired_orders()       (sweep GTD orders)
    ├── add_order_to_db()               (insert as 'live')
    ├── _match_and_fill_order()         (price-time priority matching)
    │       └── _fill_order()           (update REMAINING_AMOUNT, insert trade)
    └── return OrderResponse (JSON)
```
---
## Key Design Decisions
| Decision | Rationale |
|----------|-----------|
| **SQLite as the only datastore** | Zero infrastructure — start with `make init && uvicorn …`. In-memory mode for tests means no cleanup needed. |
| **`AgentPitServer` subclasses `FastAPI`** | Server is both the app and its own router; no separate `APIRouter` registration step needed. |
| **DB layer split by operation** (`table_read` / `table_write`) | Prevents accidental writes in read paths; makes data flow auditable. Errors propagate — no silent swallowing. |
| **Simulators store hex-uint256 in JSON** | Mirrors on-chain storage semantics exactly; avoids integer precision issues with Python's arbitrary-precision ints. |
| **Sync is lazy and one-directional** | No background threads or webhooks. Sync is triggered explicitly (or by cron). The local DB is the source of truth for local state; Polymarket is the source of truth for market existence and resolution. |
| **`host=""` toggles local vs remote** | Agents need zero code changes to switch between simulation and live trading. All Polymarket API calls pass through the same `ClobClient` interface. |
| **EIP-712 order IDs** | Identical to Polymarket's own order hashing — a locally matched order ID is valid on Polymarket too. |
| **Pydantic strict mode on simulators** | `@validate_call(config=_STRICT)` catches wrong argument types at the boundary; avoids silent type coercion bugs when ints are passed as strings. |
| **`check_state` raises `HTTPException(400)`** | Validation failures deep in business logic surface as clean 400 responses with call-site detail, not 500s. |
---
## Environment and Configuration
| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENTPIT_DB_PATH` | `:memory:` | SQLite file path; use a real path to persist across restarts |
All other constants (contract addresses, Gamma/CLOB/RPC URLs) are module-level in their respective files — no `.env` file is needed for basic operation.
Secrets (private keys for live Polymarket trading) are stored in environment variables and never hardcoded. See the root `README.md` for setup.
---
## Starting the Server
```bash
make init    # pip install -r requirements.txt
# In-memory DB (development / testing)
uvicorn agentpit.fastapi.main:app --host 0.0.0.0 --port 8000 --reload
# Persistent DB
AGENTPIT_DB_PATH=/path/to/agentpit.db \
  uvicorn agentpit.fastapi.main:app --host 0.0.0.0 --port 8000 --reload
```
---
## Documentation Index
| Document | Covers |
|----------|--------|
| **[agentpit_api.md](agentpit_api.md)** | All 20 REST endpoints, DB schema, error format, full lifecycle walkthrough |
| **[contract_simulators_spec.md](contract_simulators_spec.md)** | ERC-20 / ERC-1155 / PredictionMarket simulator internals, storage model, call map |
| **[trading_engine_spec.md](trading_engine_spec.md)** | CLOB matching algorithm, order types, price encoding, FOK/FAK/GTD logic |
| **[polymarket_sync_spec.md](polymarket_sync_spec.md)** | Gamma API sync pipeline, field normalisation, market state sync |
| **[conditional_token_framework_spec.md](conditional_token_framework_spec.md)** | On-chain CTF condition checks, resolution payout model |
| **[tests_overview.md](tests_overview.md)** | Full test map, how to run tests, coverage gaps |
