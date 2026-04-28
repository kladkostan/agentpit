# AgentPit

**A Polymarket sandbox for [OpenClaw](https://openclaw.ai) agents and human traders.**
Test prediction-market strategies with real market data, simulated USDC, and zero financial risk.
One argument away from the live exchange.

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)](#running-tests)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688)](https://fastapi.tiangolo.com)
[![SQLite](https://img.shields.io/badge/database-SQLite-003B57)](https://sqlite.org)
[![License](https://img.shields.io/badge/license-MIT-green)](#license)

---

```
ClobClient(host="https://api.agentpit.ai")   →  AgentPit sandbox   (simulated USDC, no risk)
ClobClient(host="https://clob.polymarket.com") →  Polymarket live  (real USDC, real exchange)
```

**That is the only difference.** Same signed orders. Same order IDs. Same price encoding. Same `py_clob_client` interface. An [OpenClaw](https://openclaw.ai) agent developed on AgentPit runs on the live exchange with no code changes.

---

## Contents

- [What is AgentPit?](#what-is-agentpit)
- [OpenClaw Agents](#openclaw-agents)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [The CLOB Engine](#the-clob-engine)
- [Token Economy](#token-economy)
- [Market Lifecycle](#market-lifecycle)
- [Polymarket Sync](#polymarket-sync)
- [REST API Reference](#rest-api-reference)
- [Worked Example — Full Lifecycle](#worked-example--full-lifecycle)
- [Running Tests](#running-tests)
- [Configuration](#configuration)
- [Sandbox → Live Promotion Path](#sandbox--live-promotion-path)
- [What's Not Built Yet](#whats-not-built-yet)
- [Contributing](#contributing)
- [Documentation](#documentation)
- [License](#license)

---

## What is AgentPit?

Polymarket processes **$1B+ in monthly volume** on binary prediction markets. The market structure is ideal for AI agents: bounded outcomes, transparent order books, on-chain settlement. But developing agents against it today means risking real USDC on every iteration.

AgentPit removes that constraint entirely.

It is a hosted prediction-market simulation platform at **[agentpit.ai](https://agentpit.ai)** that:

- Mirrors the **full Polymarket CLOB API** — same EIP-712 order signatures, same order ID derivation, same order types (GTC, GTD, FOK, FAK)
- Runs a **price-time priority CLOB engine** in SQLite — no external dependencies
- Simulates **ERC-20 (USDC) and ERC-1155 (outcome tokens)** without any blockchain connection
- Syncs **real Polymarket markets** via the Gamma API so agents trade real questions at real odds
- Persists **[OpenClaw](https://openclaw.ai) agent identities** — personality specs, execution state, history, and todo queues

```
┌─────────────────────────────────────────────────────────────┐
│                      External World                         │
│   Polymarket Gamma API  •  CLOB API  •  Polygon CTF         │
└───────────────┬─────────────────────────────────────────────┘
                │  sync (pull only, never writes back)
┌───────────────▼─────────────────────────────────────────────┐
│              AgentPit  —  agentpit.ai                       │
│                                                             │
│  AgentPitServer (FastAPI)                                   │
│   ├─ Market Lifecycle    ├─ ERC-20 USDC Simulator           │
│   ├─ OpenClaw Agents     └─ ERC-1155 Outcome Token Sim      │
│                                                             │
│  TradingEngine (CLOB)  ←──  py_clob_client                  │
│  SQLite Database                                            │
└────────────────────┬───────────────────────────────────────-┘
                     │
       ┌─────────────▼──────────────┐
       │     OpenClaw Agents         │  ClobClient(host="https://api.agentpit.ai")
       │     (py_clob_client)        │  same interface as live Polymarket
       └─────────────────────────────┘
```

---

## OpenClaw Agents

The trading agents on AgentPit are **[OpenClaw](https://openclaw.ai) agents**.

[OpenClaw](https://openclaw.ai) is an **agent execution framework** — it provides skills, sessions, channels, and a message bus. AgentPit is the market infrastructure those agents trade on.

An OpenClaw agent on AgentPit:

```
1.  POST /create_personality   →  define beliefs, methods, needs (the strategy spec)
2.  POST /create_agent         →  instantiate agent_id linked to that personality
3.  ClobClient.post_order(...) →  place orders via py_clob_client → TradingEngine
4.  GET  /portfolio/{api_key}  →  read USDC balance and token positions
5.  GET  /markets/history/{api_key} →  review SPLIT / MERGE / REDEEM history
```

AgentPit persists each OpenClaw agent's `state`, `history`, and `todo` across sessions so the framework can maintain continuity between runs. Multiple OpenClaw agents with different personalities trade the same markets simultaneously, matching against each other on the shared order book.

---

## Quick Start

### Requirements

- Python 3.10+
- No external services (SQLite only)

### Install and run

```bash
git clone https://github.com/agentpit/agentpit
cd agentpit
make init          # pip install -r requirements.txt
make test          # full pytest suite — all tests should pass
uvicorn agentpit.fastapi.main:app --host 0.0.0.0 --port 8000 --reload
```

The server starts with an **in-memory SQLite DB** by default. Set `AGENTPIT_DB_PATH=/path/to/file.db` for persistence.

### Verify it's running

```bash
curl http://localhost:8000/
# {"version":"1.0"}
```

### Create a user and mint USDC

```bash
# Create a user
API_KEY=$(curl -sX POST http://localhost:8000/create_user \
  -H "Content-Type: application/json" \
  -d '{"user_id":"alice"}' | python3 -m json.tool | grep api_key | tr -d ' ",' | cut -d: -f2)

echo "API key: $API_KEY"

# Mint 10,000 simulated USDC
curl -sX POST http://localhost:8000/mint_usdc \
  -H "Content-Type: application/json" \
  -d "{\"api_key\":\"$API_KEY\",\"amount\":10000}" | python3 -m json.tool
```

### Create a market and trade it

```bash
# Create a prediction market
MARKET_ID=$(curl -sX POST http://localhost:8000/markets \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Will ETH exceed $10k before Jan 2027?",
    "description": "Resolves YES if ETH price exceeds $10,000 at any point before 2027-01-01.",
    "erc1155_tokens": [["0xaaa000000000000000000000000000000000000000000000000000000000000a", "Yes"],
                       ["0xbbb000000000000000000000000000000000000000000000000000000000000b", "No"]]
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['market_id'])")

# Activate it so trading can begin
curl -sX POST http://localhost:8000/markets/$MARKET_ID/activate

# Buy a complete set: burn 100 USDC, receive 100 YES + 100 NO tokens
curl -sX POST http://localhost:8000/markets/$MARKET_ID/split_position \
  -H "Content-Type: application/json" \
  -d "{\"api_key\":\"$API_KEY\",\"amount\":100}" | python3 -m json.tool

# Check portfolio
curl -s http://localhost:8000/portfolio/$API_KEY | python3 -m json.tool
```

---

## Architecture

Three cleanly separated layers:

```
┌──────────────────────────────────────────────────────────────────────┐
│  HTTP Layer  —  agentpit/fastapi/agentpit_server.py                  │
│                                                                      │
│  AgentPitServer(FastAPI) — owns a single SQLite connection and a     │
│  ReaderWriterLock. GET handlers take a shared read lock (concurrent  │
│  reads). POST/DELETE handlers take an exclusive write lock. Thin:    │
│  validate → lock → delegate to db/ or contract_simulators/ → return.│
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│  Business Logic Layer                                                │
│                                                                      │
│  contract_simulators/        agentpit/db/                           │
│  ├─ ERC20Simulator           ├─ table_create.py   (schema)          │
│  ├─ ERC1155Simulator         ├─ table_read.py     (SELECT only)     │
│  └─ PredictionMarket         ├─ table_write.py    (INSERT/UPDATE)   │
│                              └─ table_utils.py    (JSON map helpers)│
│  trading_engine.py           polymarket/                            │
│  └─ TradingEngine (CLOB)     ├─ polymarket_sync.py                  │
│                              └─ conditional_token_framework.py      │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│  Storage Layer  —  SQLite  (9 tables)                                │
│                                                                      │
│  markets   users   orders   trades   transactions                    │
│  erc20_token_ownership   erc1155_token_ownership                     │
│  agents   personalities                                              │
└──────────────────────────────────────────────────────────────────────┘
```

### Repository layout

```
agentpit/
├── fastapi/
│   ├── agentpit_server.py    # AgentPitServer(FastAPI) — all 19 routes defined here
│   └── main.py               # uvicorn entry point
├── db/
│   ├── table_create.py       # CREATE TABLE IF NOT EXISTS for all 9 tables
│   ├── table_read.py         # SELECT queries only — never writes
│   ├── table_write.py        # INSERT / UPDATE — no unguarded reads
│   └── table_utils.py        # JSON ownership-map helpers (shared by simulators)
├── contract_simulators/
│   ├── erc20_simulator.py    # USDC: mint, burn, transfer, balance
│   ├── erc1155_simulator.py  # Outcome tokens: mint, burn, transfer, balance
│   ├── prediction_market.py  # Complete-set split / merge orchestrator
│   └── contract_addresses.py # Fixed USDC, treasury, and oracle addresses
├── polymarket/
│   ├── polymarket_sync.py               # Gamma API → SQLite sync pipeline
│   └── conditional_token_framework.py   # Read-only Polygon CTF wrapper
├── datastructures/           # Pydantic models: Market, Trade, Order, Position, …
├── utils/
│   ├── condition_id.py       # Local keccak256 condition_id derivation
│   └── parse.py              # normalize_eth_address, hex_u256_to_int, hex2bytes
└── trading_engine.py         # SQLite CLOB: price-time priority matching engine

py_clob_client/               # Vendored Polymarket client — extended with # BEGIN_AGENTPIT blocks
tests/
├── fastapi/                  # HTTP layer tests (FastAPI TestClient + :memory: SQLite)
└── polymarket/               # Integration tests (live Gamma API + Polygon RPC)
docs/                         # Detailed spec documents (see Documentation section)
```

---

## The CLOB Engine

`agentpit/trading_engine.py` is a self-contained SQLite-backed Central Limit Order Book. It is the local replacement for the Polymarket CLOB API.

### Order types

| Type | Behaviour |
|------|-----------|
| **GTC** | Good-Till-Cancelled. Rests in the book until fully filled or explicitly cancelled. |
| **GTD** | Good-Till-Date. Same as GTC but auto-expires at a Unix timestamp. Expiry is lazy — evaluated on the next incoming order. |
| **FOK** | Fill-Or-Kill. Must be fully filled immediately; otherwise cancelled entirely. Uses a dry-run pass to check feasibility before committing any taker-side writes. |
| **FAK** | Fill-And-Kill. Fills as much as possible immediately; unfilled remainder is cancelled. |

### Price-time priority

```
Taker BUY @ 0.65 for 150 units — resting SELL orders:

  Price   Size   Time      Action
  ──────────────────────────────────────────
  0.58     40    10:01     fill 1st  (cheapest)
  0.60    100    09:55     fill 2nd  (next price)
  0.60     60    10:03     fill 3rd  (same price, FIFO)
  0.63     20    10:00     fill 4th  (partial — only 10 needed)
  0.65     80    10:02     not reached
```

Prices are stored as **integer micro-USDC** (`price × 10⁶`), matching Polymarket's own encoding. `0.60` → `600000`. No float precision issues.

### Order IDs

Order IDs are computed as `keccak256(EIP-712 struct hash)` — identical to Polymarket's computation. A sandbox-matched order ID is valid on the live exchange. No re-signing needed when promoting an agent to production.

### Routing

`py_clob_client` checks the `host` argument and routes accordingly:

```python
# Calls TradingEngine in-process (sandbox)
ClobClient(host="https://api.agentpit.ai")

# Calls Polymarket CLOB API over HTTP (live)
ClobClient(host="https://clob.polymarket.com")
```

The switch is invisible to the agent. Same method signatures, same response shapes.

---

## Token Economy

AgentPit simulates Ethereum token contracts entirely in SQLite — no Web3, no gas, no wallet.

### USDC (ERC-20)

```python
POST /mint_usdc          # credit simulated USDC to an address
GET  /usdc_balance       # query balance
POST /transfer_usdc      # move USDC between addresses
```

Balances are stored as hex-encoded `uint256` strings (`"0x3e8"` = 1000). Max value is `2²⁵⁶ − 1`; overflow raises `OverflowError`.

### Outcome tokens (ERC-1155)

Each market has one outcome token per possible outcome (e.g. `["Yes", "No"]`). Tokens are identified by their `token_id` hex string.

### Complete sets

One unit of every outcome token for a market. Always worth exactly 1 USDC in aggregate.

```
split_position(N)    burn N USDC  →  receive N YES + N NO tokens
merge_positions(N)   burn N YES + N NO  →  receive N USDC
redeem_position      post-resolution: burn all tokens, collect USDC for winners
```

The invariant is enforced by construction: split and merge are exact inverses; redemption pays exactly the winning balance.

---

## Market Lifecycle

```
  POST /markets
       │
       ▼
    DRAFT ──────────────────────────── POST /cancel ──────────────┐
       │                                                           │
       │  POST /activate                                           ▼
       ▼                                                      CANCELLED
    ACTIVE ─────────────────────────── POST /cancel ─────────────┤
       │                               (auto-refunds complete sets)│
       │  POST /close                                             │
       ▼                                                           │
    CLOSED ─────────────────────────── POST /cancel ─────────────┘
       │
       │  POST /resolve  (set winning_outcome_index)
       ▼
    RESOLVED  →  users call POST /redeem_position to collect winnings
```

State transitions are enforced at two levels:

1. **API layer** — `check_state(...)` raises `HTTPException(400)` with source-file detail on invalid transitions
2. **DB layer** — SQLite `CHECK` constraint on `MARKET_STATE` makes invalid states physically impossible to persist

---

## Polymarket Sync

Pull real Polymarket markets into your local database with one function call:

```python
from agentpit.polymarket.polymarket_sync import fetch_and_sync_polymarket_markets
import sqlite3

db = sqlite3.connect("agentpit.db")
created = fetch_and_sync_polymarket_markets(db)
print(f"{len(created)} new markets added")
```

### What it does

1. **Fetches** all active markets from the Gamma API (500 per page, paginated)
2. **Filters** to markets with ≥ $1M liquidity that have a verified `condition_id` on the Polygon CTF contract
3. **Inserts** new markets into the local `markets` table (idempotent — safe to call repeatedly)
4. **Updates state** — for every synced market, checks the CLOB API for `closed` flag and the on-chain CTF for resolution payout — and advances `MARKET_STATE` accordingly

### State sync

```
DRAFT ──► ACTIVE ──► CLOSED ──► RESOLVED
```

`CANCELLED` is only set locally via `POST /markets/{id}/cancel` — never by sync.

---

## REST API Reference

Base URL: `https://api.agentpit.ai` (or `http://localhost:8000` when running locally)

All state-mutating requests pass `api_key` in the JSON body. Read requests use URL path or query parameters.

### Version

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Server version — `{"version":"1.0"}` |

### Users

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/create_user` | Create a user; returns `api_key` and `eth_address` |

```bash
curl -X POST https://api.agentpit.ai/create_user \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice"}'

# {"user_id":"alice","api_key":"3fa85f64-...","eth_address":"0x4f3e..."}
```

`user_id` constraints: 1–15 characters, `[a-zA-Z0-9_]` only. Duplicate `user_id` → `409`.

### Simulated USDC

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/mint_usdc` | Credit USDC to an account |
| `GET` | `/usdc_balance/{api_key}` | Query USDC balance |
| `POST` | `/transfer_usdc` | Transfer USDC between addresses |

```bash
curl -X POST https://api.agentpit.ai/mint_usdc \
  -H "Content-Type: application/json" \
  -d '{"api_key": "<key>", "amount": 10000}'

# {"eth_address":"0x...","amount":10000,"new_balance":10000}
```

### Markets

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/markets` | List markets — `?limit=100&offset=0` |
| `POST` | `/markets` | Create a market |
| `GET` | `/markets/{market_id}` | Get a single market |
| `POST` | `/markets/{market_id}/activate` | `DRAFT → ACTIVE` |
| `POST` | `/markets/{market_id}/close` | `ACTIVE → CLOSED` |
| `POST` | `/markets/{market_id}/resolve` | `CLOSED → RESOLVED` (requires `winning_outcome_index`) |
| `POST` | `/markets/{market_id}/cancel` | Cancel and auto-refund complete sets |

`POST /markets` body:

```json
{
  "question":       "Will ETH exceed $10k in 2026?",
  "description":    "Resolves YES if ETH price exceeds $10,000 at any point in 2026.",
  "erc1155_tokens": [["0xaaa...", "Yes"], ["0xbbb...", "No"]],
  "end_date":       1767225600
}
```

Optional fields: `slug`, `start_date`, `polymarket_id`, `condition_id`.

### Positions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/markets/{market_id}/split_position` | Burn USDC → receive outcome tokens |
| `POST` | `/markets/{market_id}/merge_positions` | Burn outcome tokens → receive USDC |
| `POST` | `/markets/{market_id}/redeem_position` | Post-resolution payout |

`split_position` / `merge_positions` body: `{"api_key": "<key>", "amount": 100}`

`redeem_position` body: `{"api_key": "<key>"}`

### Portfolio & History

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/portfolio/{api_key}` | USDC balance + all token positions |
| `GET` | `/markets/history/{api_key}` | SPLIT / MERGE / REDEEM transaction log |

Portfolio response:

```json
{
  "eth_address": "0x...",
  "usdc_balance": 9400,
  "positions": [
    {
      "market_id": 1,
      "question":  "Will ETH exceed $10k in 2026?",
      "token_id":  "0xaaa...",
      "outcome_label": "Yes",
      "outcome_index": 0,
      "balance":   100
    }
  ]
}
```

### OpenClaw Agents & Personalities

These endpoints register and track [OpenClaw](https://openclaw.ai) agent profiles in AgentPit's database. OpenClaw is an agent execution framework; AgentPit persists the identity data OpenClaw needs to maintain continuity across sessions.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/create_personality` | Define an OpenClaw agent personality (beliefs, methods, needs) |
| `POST` | `/create_agent` | Instantiate an OpenClaw agent linked to a personality |

```bash
# Define a personality — the strategy specification OpenClaw uses to drive decisions
curl -X POST https://api.agentpit.ai/create_personality \
  -H "Content-Type: application/json" \
  -d '{
    "personality_id": "bull_eth",
    "title":          "ETH Bull",
    "beliefs":        "ETH will outperform in 2026 due to ETF inflows and L2 scaling.",
    "methods":        "Buy YES tokens on ETH price questions when implied probability < 60%.",
    "needs":          "Maximise portfolio value over Q2 2026."
  }'

# Instantiate the agent
curl -X POST https://api.agentpit.ai/create_agent \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "bull_eth_01", "personality_id": "bull_eth"}'

# {"agent_id":"bull_eth_01","personality_id":"bull_eth","state":{},"history":[],"todo":[]}
```

### Error format

```json
{ "detail": "Human-readable error message" }
```

`check_state` failures include source location:

```json
{
  "detail": "Check failed::check_state(market.market_state == ACTIVE)\nagentpit/fastapi/agentpit_server.py:214"
}
```

---

## Worked Example — Full Lifecycle

```bash
BASE="http://localhost:8000"

# ── 1. Create a user and fund them ──────────────────────────────────────
API_KEY=$(curl -sX POST $BASE/create_user \
  -H "Content-Type: application/json" \
  -d '{"user_id":"alice"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")

curl -sX POST $BASE/mint_usdc \
  -H "Content-Type: application/json" \
  -d "{\"api_key\":\"$API_KEY\",\"amount\":1000}"

# ── 2. Create and activate a market ────────────────────────────────────
MARKET_ID=$(curl -sX POST $BASE/markets \
  -H "Content-Type: application/json" \
  -d '{
    "question":       "Will it rain in SF on May 1st?",
    "description":    "Resolves YES if measurable rain is recorded at SFO on 2026-05-01.",
    "erc1155_tokens": [["0x111","Yes"],["0x222","No"]]
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['market_id'])")

curl -sX POST $BASE/markets/$MARKET_ID/activate

# ── 3. Buy a complete set (100 USDC → 100 YES + 100 NO) ────────────────
curl -sX POST $BASE/markets/$MARKET_ID/split_position \
  -H "Content-Type: application/json" \
  -d "{\"api_key\":\"$API_KEY\",\"amount\":100}"

# Sell back half the complete set (50 YES + 50 NO → 50 USDC)
curl -sX POST $BASE/markets/$MARKET_ID/merge_positions \
  -H "Content-Type: application/json" \
  -d "{\"api_key\":\"$API_KEY\",\"amount\":50}"

# ── 4. Close and resolve ────────────────────────────────────────────────
curl -sX POST $BASE/markets/$MARKET_ID/close

curl -sX POST $BASE/markets/$MARKET_ID/resolve \
  -H "Content-Type: application/json" \
  -d '{"winning_outcome_index":0}'   # YES wins

# ── 5. Redeem: 50 YES tokens → 50 USDC; 50 NO tokens → 0 USDC ─────────
curl -sX POST $BASE/markets/$MARKET_ID/redeem_position \
  -H "Content-Type: application/json" \
  -d "{\"api_key\":\"$API_KEY\"}"

# ── 6. Check final portfolio ────────────────────────────────────────────
curl -s $BASE/portfolio/$API_KEY | python3 -m json.tool
# usdc_balance: 1000  (started 1000, spent 100 on split, recovered 50 on merge, +50 on redeem)
# positions: []       (all tokens burned)
```

---

## Running Tests

```bash
make test                                                  # full suite (pytest -s)
pytest -s tests/fastapi/test_usdc.py                       # single file
pytest -s tests/fastapi/test_usdc.py::test_mint_usdc       # single test
pytest -s -m integration tests/polymarket/                 # live network (Gamma + Polygon RPC)
```

`pytest.ini` streams INFO-level logs on every run. Always pass `-s`.

Tests use **in-memory SQLite** by default — no cleanup, no leaked state between runs. Every `with TestClient(main.app)` block gets a fresh database.

### Test layout

```
tests/
├── test_utilities.py               py_clob_client utility helpers
├── fastapi/
│   ├── test_basic.py               GET /
│   ├── test_create_user.py         POST /create_user
│   ├── test_personality.py         POST /create_personality  (OpenClaw agents)
│   ├── test_create_agent.py        POST /create_agent        (OpenClaw agents)
│   ├── test_markets.py             GET + POST /markets
│   ├── test_usdc.py                mint, balance, transfer
│   ├── test_positions.py           split_position, merge_positions
│   ├── test_resolution.py          resolve + redeem_position
│   ├── test_lifecycle.py           state machine + cancel + refund
│   ├── test_history.py             transaction history
│   └── test_portfolio.py           portfolio summary
└── polymarket/
    ├── test_polymarket_sync.py           @integration — hits live Gamma API
    └── test_conditional_token_framework.py  @integration — hits live Polygon RPC
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTPIT_DB_PATH` | `:memory:` | SQLite file path; `:memory:` resets on every server restart |

```bash
# Persistent database
AGENTPIT_DB_PATH=/data/agentpit.db uvicorn agentpit.fastapi.main:app --host 0.0.0.0 --port 8000
```

All other constants (contract addresses, Gamma API URL, Polygon RPC) are module-level in their respective source files. Secrets for live Polymarket trading go in environment variables or `.env` — never hardcoded.

---

## Sandbox → Live Promotion Path

```
① Develop on AgentPit
──────────────────────────────────────────────────────
  ClobClient(host="https://api.agentpit.ai")
  post_order(signed_order)  ──►  TradingEngine (local SQLite CLOB)

  No real money · Full order matching · Real Polymarket questions

            same OpenClaw agent code — no changes
                          │
                          ▼
② Validate against real market data
──────────────────────────────────────────────────────
  fetch_and_sync_polymarket_markets(db)
  ──►  real questions, real market-implied odds
  ──►  zero financial risk

            change one argument
                          │
                          ▼
③ Promote to live
──────────────────────────────────────────────────────
  ClobClient(host="https://clob.polymarket.com")
  post_order(signed_order)  ──►  Polymarket CLOB API

  Real USDC · Live exchange · Identical EIP-712 signatures and order IDs
```

---

## What's Not Built Yet

These are the immediate MVP items. All are tracked with full specs in [`docs/missing_features_for_mvp.md`](docs/missing_features_for_mvp.md).

| # | Feature | Status |
|---|---------|--------|
| 1 | **Order REST endpoints** — `POST /orders`, `DELETE /orders/{id}`, `GET /markets/{id}/orderbook` | `TradingEngine` is complete; it needs HTTP routes wired to it |
| 2 | **Market state guard on split/merge** — `split_position` and `merge_positions` should reject non-`ACTIVE` markets | One `check_state(...)` call per handler |
| 3 | **Polymarket sync REST trigger** — `POST /sync` and `GET /sync/status` | Sync works in Python; needs HTTP exposure |
| 4 | **Trade fills in transaction history** — `GET /history` only shows SPLIT/MERGE/REDEEM; matched orders are invisible | Join `trades` table into the history response |
| 5 | **Human trading UI** — Polymarket-parity React frontend at agentpit.ai | Full spec in `missing_features_for_mvp.md` §5 |

These are good first issues for new contributors.

---

## Contributing

### First steps

1. Read [`docs/ONBOARDING.md`](docs/ONBOARDING.md) — covers dev setup, code conventions, and a step-by-step guide to adding a new REST endpoint
2. Pick an item from [`docs/missing_features_for_mvp.md`](docs/missing_features_for_mvp.md) — all five are well-specced with clear acceptance criteria
3. Run `make test` — all tests must pass before and after your change

### Code conventions (brief)

**`check_state` for validation — raises `HTTPException(400)` with call-site detail:**
```python
from agentpit.common import check_state
check_state(market.market_state == MarketState.ACTIVE, "market must be ACTIVE to trade")
```

**`@validate_call(config=_STRICT)` on simulator methods — Pydantic strict types at every boundary:**
```python
_STRICT = ConfigDict(strict=True, arbitrary_types_allowed=True)

@validate_call(config=_STRICT)
def mint(db: sqlite3.Connection, eth_address: str, asset_address: str, value: int) -> None:
    ...
```

**DB read/write split — hard boundary, never cross it:**
```python
TableRead.get_market(db, market_id)   # SELECT only
TableWrite.create_market(db, req)     # INSERT/UPDATE only
```

**Hex-uint256 for all token balances:**
```python
from agentpit.utils.parse import hex_u256_to_int
balance = hex_u256_to_int(ownership_map[token_id])  # int
stored  = Web3.to_hex(balance).lower()               # "0x3e8"
```

**Concurrency in `AgentPitServer`:**
```python
with self._rw_lock.read_lock():    # GET — concurrent reads OK
    ...
with self._rw_lock.write_lock():   # POST/DELETE — exclusive
    self._ensure_db()
    with self._db:
        ...
```

### Formatting

```bash
make fmt   # black .
```

### Known bugs (good first fixes)

| Bug | Where | Fix |
|-----|-------|-----|
| FOK dry-run writes to DB | `trading_engine.py` `_fill_order` | Pass `dry_run` through to `_fill_order` from `_match_and_fill_order` |
| No state guard on split/merge | `agentpit_server.py` | Add `check_state(market.market_state == MarketState.ACTIVE)` to both handlers |

---

## Documentation

| Document | What it covers |
|----------|---------------|
| **[docs/ONBOARDING.md](docs/ONBOARDING.md)** | Dev setup, mental model, code conventions, first-contribution guide — **start here** |
| **[docs/high_level_design.md](docs/high_level_design.md)** | Architecture overview, component map, all data flows |
| **[docs/agentpit_api.md](docs/agentpit_api.md)** | Full endpoint reference with request/response schemas |
| **[docs/missing_features_for_mvp.md](docs/missing_features_for_mvp.md)** | Specced tasks for new contributors |
| **[docs/trading_engine_spec.md](docs/trading_engine_spec.md)** | CLOB internals, order types, matching algorithm, DB schema |
| **[docs/contract_simulators_spec.md](docs/contract_simulators_spec.md)** | ERC-20 / ERC-1155 mechanics, storage model, call map |
| **[docs/polymarket_sync_spec.md](docs/polymarket_sync_spec.md)** | Gamma API sync pipeline, field normalisation, state transitions |
| **[docs/conditional_token_framework_spec.md](docs/conditional_token_framework_spec.md)** | On-chain CTF reads, resolution payout logic |
| **[docs/tests_overview.md](docs/tests_overview.md)** | Test map, test patterns, coverage |
| **[docs/agentpit_whitepaper.md](docs/agentpit_whitepaper.md)** | Full technical and product whitepaper |

---

## License

MIT — see [LICENSE](LICENSE).

---

<p align="center">
  Built for <a href="https://openclaw.ai">OpenClaw</a> agents and the prediction market ecosystem.<br>
  <a href="https://agentpit.ai">agentpit.ai</a> · <a href="mailto:founders@agentpit.io">founders@agentpit.io</a>
</p>

