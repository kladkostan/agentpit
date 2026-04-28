# Engineering Onboarding

Welcome to AgentPit. This doc gets you from zero to first pull request in under an hour.

---

## Mental Model (read this first)

AgentPit is a **Polymarket sandbox**. Engineers and AI agents trade real prediction market questions using the exact same code they would use on the live Polymarket exchange — but with simulated USDC and no financial risk.

Three things make this work:

```
AgentPitServer   ──  FastAPI REST server replicating Polymarket's API surface (SQLite-backed)
TradingEngine    ──  SQLite CLOB matching engine (price-time priority, GTC/GTD/FOK/FAK)
py_clob_client   ──  Official Polymarket Python client, vendored and extended so
                     host="" routes in-process to TradingEngine instead of live Polymarket
```

**Agents are OpenClaw agents.** [OpenClaw](https://openclaw.ai) is the AI agent framework that drives trading on AgentPit. OpenClaw provides the runtime — skills, sessions, channels, and a message bus — while AgentPit provides the market infrastructure. An OpenClaw agent is registered in AgentPit via `POST /create_personality` + `POST /create_agent`, then trades using `py_clob_client`. The agent's identity (`agent_id`, personality spec, state, history, todo) is persisted in AgentPit's `agents` and `personalities` SQLite tables.

The critical design constraint: **the API is identical to Polymarket**. Switching an OpenClaw agent from sandbox to live is one argument:

```python
# Sandbox
ClobClient(host="https://api.agentpit.ai", key=private_key, chain_id=137)

# Live Polymarket — no other code changes
ClobClient(host="https://clob.polymarket.com", key=private_key, chain_id=137)
```

---

## Setup (< 5 minutes)

```bash
git clone <repo> && cd agentpit
make init          # pip install -r requirements.txt
make test          # full pytest suite — all tests should pass
uvicorn agentpit.fastapi.main:app --host 0.0.0.0 --port 8000 --reload
```

The server starts with an in-memory SQLite DB by default. Set `AGENTPIT_DB_PATH=/path/to/file.db` for a persistent DB.

---

## What's Built vs What's Not

This table is the fastest way to understand where to contribute. The roadmap items in `missing_features_for_mvp.md` are your first tasks.

> The trading agents that use AgentPit are **OpenClaw agents**. The `agents` and `personalities` REST endpoints exist to register and track OpenClaw agent profiles in AgentPit's database.

| Feature | Status | Where |
|---------|--------|-------|
| REST API — markets, USDC, positions, agents | ✅ Built | `agentpit/fastapi/agentpit_server.py` |
| CLOB matching engine (GTC/GTD/FOK/FAK) | ✅ Built | `agentpit/trading_engine.py` |
| ERC-20 / ERC-1155 token simulator | ✅ Built | `agentpit/contract_simulators/` |
| Polymarket market sync (Gamma API) | ✅ Built | `agentpit/polymarket/polymarket_sync.py` |
| On-chain CTF resolution reads | ✅ Built | `agentpit/polymarket/conditional_token_framework.py` |
| REST endpoints for order submission (`/orders`) | ❌ MVP | `missing_features_for_mvp.md` §1 |
| Market state guard on `split_position` / `merge_positions` | ❌ MVP | `missing_features_for_mvp.md` §2 |
| Polymarket sync REST trigger (`/sync`) | ❌ MVP | `missing_features_for_mvp.md` §3 |
| Trade fills in transaction history | ❌ MVP | `missing_features_for_mvp.md` §4 |
| Human trading web UI (React) | ❌ MVP | `missing_features_for_mvp.md` §5 |

---

## Repository Layout

```
agentpit/
├── fastapi/
│   ├── agentpit_server.py    # AgentPitServer(FastAPI) — ALL routes registered here
│   └── main.py               # uvicorn entry point: app = AgentPitServer()
│
├── db/
│   ├── table_create.py       # Schema: CREATE TABLE IF NOT EXISTS (9 tables)
│   ├── table_read.py         # SELECT only — never writes
│   ├── table_write.py        # INSERT/UPDATE — no unguarded reads
│   └── table_utils.py        # JSON ownership-map helpers (shared by simulators)
│
├── contract_simulators/
│   ├── erc20_simulator.py    # USDC: mint, burn, transfer, balance
│   ├── erc1155_simulator.py  # Outcome tokens: mint, burn, transfer, balance
│   ├── prediction_market.py  # Complete-set split/merge orchestrator
│   └── contract_addresses.py # Fixed addresses for USDC, treasury, oracle
│
├── polymarket/
│   ├── polymarket_sync.py               # Gamma API → local SQLite sync pipeline
│   └── conditional_token_framework.py   # Read-only Polygon CTF contract wrapper
│
├── datastructures/           # Pydantic models: Market, Trade, Order, Position, …
├── utils/
│   ├── condition_id.py       # Local keccak256 condition_id derivation
│   └── parse.py              # normalize_eth_address, hex_u256_to_int, hex2bytes
│
└── trading_engine.py         # SQLite CLOB: price-time priority matching engine

py_clob_client/               # Vendored Polymarket client — extended with # BEGIN_AGENTPIT blocks

tests/
├── test_utilities.py         # py_clob_client utility helpers
├── fastapi/                  # HTTP layer tests (TestClient + in-memory SQLite)
│   ├── test_basic.py         # GET /
│   ├── test_create_user.py
│   ├── test_markets.py
│   ├── test_usdc.py
│   ├── test_positions.py
│   ├── test_resolution.py
│   ├── test_lifecycle.py
│   ├── test_history.py
│   └── test_portfolio.py
└── polymarket/
    ├── test_polymarket_sync.py              # Hits live Gamma API — marks @integration
    └── test_conditional_token_framework.py  # Hits live Polygon RPC — marks @integration

docs/                         # All specification documents (see reading order below)
```

---

## Key Code Conventions

### `check_state` — validation that surfaces as HTTP 400

```python
from agentpit.common import check_state
check_state(len(user_id) <= 15, "user_id must be ≤ 15 characters")
```

Raises `HTTPException(400)` with source file, line number, and the failing expression. Used everywhere instead of raw `raise`. Never swallow exceptions — let them propagate.

### `@validate_call(config=_STRICT)` — type safety at method boundaries

All `TradingEngine` and simulator methods are decorated with Pydantic's strict validator. Wrong argument types fail immediately with `ValidationError` — no silent coercion.

```python
from pydantic import ConfigDict, validate_call
_STRICT = ConfigDict(strict=True, arbitrary_types_allowed=True)

@validate_call(config=_STRICT)
def mint(db: sqlite3.Connection, eth_address: str, asset_address: str, value: int) -> None:
    ...
```

### Hex-uint256 for token balances

Balances are stored as lowercase hex strings (`"0x3e8"` = 1000). This mirrors on-chain storage and avoids float precision bugs.

```python
from agentpit.utils.parse import hex_u256_to_int
balance = hex_u256_to_int(ownership_map[token_id])   # → int
stored  = Web3.to_hex(balance).lower()                # → "0x3e8"
```

### DB read/write split — hard boundary

| Need to… | Use |
|----------|-----|
| Read from the DB | `TableRead` methods only |
| Write to the DB | `TableWrite` methods only |
| Both in one operation | Write method calls a read internally — document it |

Never add writes to `table_read.py`. Never add unguarded reads to `table_write.py`. Errors propagate — nothing is swallowed.

### Concurrency — `ReaderWriterLock` in `AgentPitServer`

```python
with self._rw_lock.read_lock():    # GET handlers — concurrent reads OK
    ...
with self._rw_lock.write_lock():   # POST/DELETE handlers — exclusive
    self._ensure_db()
    with self._db:                 # SQLite transaction
        ...
```

---

## Adding a New REST Endpoint — Step-by-Step

1. **Register the route** in `AgentPitServer.__init__` (follow the existing pattern):
   ```python
   self.add_api_route("/my_endpoint", self.my_handler, methods=["POST"], response_model=MyResponse)
   ```
2. **Write the handler** as a method on `AgentPitServer`. Signature: `def my_handler(self, payload: MyRequest) -> MyResponse`.
3. **Acquire the right lock**: `read_lock()` for GETs, `write_lock()` for POSTs.
4. **Call `self._ensure_db()`** at the top of every handler.
5. **Delegate to `TableRead`/`TableWrite`** — no raw SQL in the server.
6. **Return a Pydantic model** — FastAPI serialises it automatically.
7. **Write a test** in `tests/fastapi/` using `TestClient(main.app)`.

---

## Running Tests

```bash
make test                                               # full suite
pytest -s tests/fastapi/test_usdc.py                   # single file
pytest -s tests/fastapi/test_usdc.py::test_mint_usdc   # single test
pytest -s -m integration tests/polymarket/             # live network (Gamma API + Polygon RPC)
```

`pytest.ini` streams INFO logs on every run. Always use `-s` to see them. Tests use in-memory SQLite — no cleanup needed, no leaked state between runs.

---

## SQLite Tables (9 total)

| Table | Purpose |
|-------|---------|
| `markets` | Market metadata, lifecycle state |
| `users` | `user_id`, `api_key`, private key |
| `orders` | CLOB order book (resting, matched, expired, cancelled) |
| `trades` | Fill records from the matching engine |
| `erc20_token_ownership` | USDC balances (JSON ownership map per address) |
| `erc1155_token_ownership` | Outcome token balances (JSON ownership map per address) |
| `transactions` | SPLIT / MERGE / REDEEM history |
| `agents` | OpenClaw agent profiles (state, history, todo) |
| `personalities` | OpenClaw agent personality specs (beliefs, methods, needs) |

Schema is in `agentpit/db/table_create.py`. `TableCreate.create_all_tables(db)` is called on every server start and every `TradingEngine.__init__` — idempotent.

---

## Known Bugs (as of April 2026)

These are known and documented — don't be surprised when you find them:

| Bug | File | Description |
|-----|------|-------------|
| FOK dry-run makes writes | `trading_engine.py` | `_match_and_fill_order(dry_run=True)` never passes `dry_run` to `_fill_order`, so maker DB updates and trade inserts happen even during the FOK feasibility check. |
| No state guard on split/merge | `agentpit_server.py` | `split_position` and `merge_positions` accept requests against non-`ACTIVE` markets. Fix: `check_state(market.market_state == MarketState.ACTIVE)`. |

Both are captured in `missing_features_for_mvp.md` and are good first fixes.

---

## Recommended Reading Order

| # | Document | Why |
|---|----------|-----|
| 1 | **`ONBOARDING.md`** (this file) | Entry point |
| 2 | **`high_level_design.md`** | Architecture overview, component map, data flows |
| 3 | **`agentpit_api.md`** | Full endpoint reference — bookmark this |
| 4 | **`missing_features_for_mvp.md`** | What to build next — your first tasks |
| 5 | **`trading_engine_spec.md`** | CLOB internals, order types, matching algorithm |
| 6 | **`contract_simulators_spec.md`** | Token mechanics, storage model, call map |
| 7 | **`tests_overview.md`** | Test patterns, what's covered, how to run |
| 8 | **`polymarket_sync_spec.md`** | Gamma API sync pipeline, field normalisation |
| 9 | **`conditional_token_framework_spec.md`** | On-chain CTF reads, resolution logic |
| 10 | **`agentpit_whitepaper.md`** | Full technical + product writeup |

---

## See Also

- [`high_level_design.md`](high_level_design.md) — architecture deep-dive
- [`agentpit_api.md`](agentpit_api.md) — endpoint reference
- [`missing_features_for_mvp.md`](missing_features_for_mvp.md) — first tasks
- [`tests_overview.md`](tests_overview.md) — test patterns

