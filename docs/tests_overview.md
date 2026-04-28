# Tests Overview
## Running Tests
```bash
make test              # full suite (pytest -s)
pytest -s              # same, verbose live logs
pytest -s tests/fastapi/test_usdc.py          # single file
pytest -s tests/fastapi/test_usdc.py::test_mint_usdc  # single test
pytest -s -m integration                      # integration tests only (live network)
```
`pytest.ini` enables live log streaming at INFO level on every run — no `-v` flag needed.
---
## Test Layout
```
tests/
├── test_utilities.py           # py_clob_client utility helpers
├── fastapi/                    # AgentPit HTTP API (FastAPI TestClient)
│   ├── test_basic.py           # GET /
│   ├── test_create_user.py     # POST /create_user
│   ├── test_personality.py     # POST /create_personality
│   ├── test_create_agent.py    # POST /create_agent
│   ├── test_markets.py         # GET+POST /markets, GET /markets/{id}
│   ├── test_usdc.py            # mint, balance, transfer
│   ├── test_positions.py       # split_position, merge_positions
│   ├── test_resolution.py      # resolve + redeem_position
│   ├── test_lifecycle.py       # state machine transitions + cancel
│   ├── test_history.py         # transaction history
│   ├── test_portfolio.py       # portfolio summary
│   └── test_main.py            # re-exports test_portfolio (backward compat)
├── order_builder/
│   ├── test_builder.py         # OrderBuilder (limit/market orders, FOK/GTC/GTD/FAK)
│   └── test_helpers.py         # decimal_places, round_normal helpers
├── signing/
│   ├── test_eip712.py          # EIP-712 clob-auth message signing
│   └── test_hmac.py            # HMAC-SHA256 Level-1 auth header
├── headers/
│   └── test_headers.py         # Level-1 / Level-2 request header builders
├── http_helpers/
│   └── test_helpers.py         # HTTP request helper functions
├── rfq/
│   ├── test_rfq_payload.py     # RFQ quote payload construction
│   └── test_rfq_query_params.py # RFQ query param serialisation
└── polymarket/
    ├── test_polymarket_sync.py       # Gamma API sync (live network)
    └── test_conditional_token_framework.py  # On-chain CTF reads (live Polygon RPC)
```
---
## Test Infrastructure
### FastAPI tests — `TestClient` + in-memory SQLite
Most FastAPI tests use `fastapi.testclient.TestClient` with the shared `main.app` instance:
```python
from fastapi.testclient import TestClient
from agentpit.fastapi import main
def test_something():
    with TestClient(main.app) as client:
        resp = client.post("/mint_usdc", json={"api_key": "k", "amount": 100})
        assert resp.status_code == 200
```
Each `with TestClient(...)` block starts with a fresh in-memory SQLite database (the default when no `AGENTPIT_DB_PATH` is set).
The `test_portfolio.py` suite uses an explicit `pytest.fixture` pattern for finer isolation:
```python
@pytest.fixture
def client():
    server = AgentPitServer(db_path=":memory:")
    with TestClient(server) as tc:
        yield tc
    server.shutdown()
```
### `py_clob_client` tests — `unittest.TestCase`
Order builder, signing, headers, and HTTP helper tests use the standard `unittest.TestCase` class with a publicly known private key on Amoy testnet (`chain_id = AMOY`):
```python
private_key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
chain_id = AMOY
signer = Signer(private_key=private_key, chain_id=chain_id)
```
No network calls are made; all assertions use pre-computed expected values.
### Integration tests — live network required
Two test files hit real external services and are gated with `@pytest.mark.integration`:
| File | Calls |
|------|-------|
| `tests/polymarket/test_polymarket_sync.py` | `https://gamma-api.polymarket.com` |
| `tests/polymarket/test_conditional_token_framework.py` | Polygon RPC via `https://tenderly.rpc.polygon.community` |
Run them explicitly:
```bash
pytest -s -m integration tests/polymarket/
```
---
## FastAPI Tests
### `tests/fastapi/test_basic.py`
| Test | What it checks |
|------|---------------|
| `test_read_root_returns_version` | `GET /` returns `{"version": "1.0"}` |
---
### `tests/fastapi/test_create_user.py`
| Test | What it checks |
|------|---------------|
| `test_create_user` | Returns `user_id`, UUID `api_key`, `0x`-prefixed `eth_address` |
| `test_create_user_duplicate` | Second call with same `user_id` → `409` with "already exists" |
| `test_create_user_invalid_handle` | >15 chars, empty string, spaces/special chars → `400` |
| `test_create_user_missing_field` | Missing `user_id` → `422` (Pydantic validation) |
| `test_create_multiple_users_unique_keys` | 3 users → all `api_key` and `eth_address` values are unique |
---
### `tests/fastapi/test_personality.py`
| Test | What it checks |
|------|---------------|
| `test_create_personality` | Returns all fields; `spec` contains `beliefs`, `methods`, `needs` |
| `test_create_personality_missing_field` | Missing `needs` → `422` |
| `test_create_personality_empty_title` | Empty `title` string → `400` via `check_state` |
---
### `tests/fastapi/test_create_agent.py`
| Test | What it checks |
|------|---------------|
| `test_create_agent` | Returns `agent_id`, `personality_id`, empty `state`/`history`/`todo` |
| `test_create_agent_duplicate` | Second call with same `agent_id` → `409` |
| `test_create_agent_missing_personality` | Non-existent `personality_id` → `404` with "not found" |
---
### `tests/fastapi/test_markets.py`
| Test | What it checks |
|------|---------------|
| `test_create_and_get_market` | Create market, `GET /markets/{id}` returns all fields; `GET /markets/9999` → `404` |
| `test_list_markets` | Empty list returns `total=0`; 5 markets created → `total=5`; `limit=2` → 2 results; `limit=2&offset=2` → correct page |
---
### `tests/fastapi/test_usdc.py`
| Test | What it checks |
|------|---------------|
| `test_mint_usdc` | First mint returns correct balance; second mint to same key accumulates |
| `test_get_usdc_balance` | Balance is 0 before mint; correct after mint; same `eth_address` on both calls |
| `test_transfer_usdc` | Sender balance decreases, receiver balance increases; response fields correct |
| `test_transfer_usdc_insufficient_balance` | Transfer > balance → `400` with "Insufficient balance" |
---
### `tests/fastapi/test_positions.py`
| Test | What it checks |
|------|---------------|
| `test_split_and_merge_positions` | Split 100 sets: USDC −100, Yes/No tokens +100 each. Merge 50: USDC +50, tokens −50 each |
| `test_split_position_insufficient_usdc` | Split with zero USDC → `400` "Insufficient USDC balance" |
| `test_merge_positions_insufficient_tokens` | Merge more than held → `400` "Insufficient balance of token" |
---
### `tests/fastapi/test_resolution.py`
| Test | What it checks |
|------|---------------|
| `test_resolve_market_and_redeem` | Full flow: two users split positions → resolve (Yes wins) → winner redeems 100 USDC, loser redeems 0 USDC; all tokens burned |
---
### `tests/fastapi/test_lifecycle.py`
| Test | What it checks |
|------|---------------|
| `test_cancel_market` | Cancel from DRAFT → state = CANCELLED, `refunds_processed = 0` |
| `test_market_lifecycle_happy_path` | Full state machine: DRAFT → ACTIVE → CLOSED → RESOLVED; each transition verified with a `GET` |
| `test_cancel_market_with_positions` | User splits 50 sets (50 USDC), market cancelled → refund 50 USDC back; `refunds_processed = 1` |
| `test_invalid_state_transitions` | Every illegal transition (DRAFT→close, ACTIVE→activate, CLOSED→activate/close, RESOLVED→any) returns `400` with descriptive message |
---
### `tests/fastapi/test_history.py`
| Test | What it checks |
|------|---------------|
| `test_get_transaction_history` | Empty history on first call; after split + merge → 2 transactions with correct `type`, `market_id`, and `details` fields; after resolve + redeem → 3rd REDEEM transaction with `payout_usdc > 0` |
---
### `tests/fastapi/test_portfolio.py`
Uses `pytest.fixture` with an isolated `AgentPitServer(db_path=":memory:")` per test.
| Test | What it checks |
|------|---------------|
| `test_get_portfolio_new_user` | New user: `usdc_balance = 0`, `positions = []` |
| `test_get_portfolio_with_usdc` | After minting 500 USDC: `usdc_balance = 500`, no positions |
| `test_get_portfolio_after_split` | After splitting: USDC decreases, positions list populated with correct `outcome_label`, `balance`, `market_id` |
| *(additional tests)* | Multi-market positions, zero-balance tokens excluded, post-merge balance update |
---
## `py_clob_client` Tests
### `tests/test_utilities.py`
Tests utility functions in `py_clob_client.utilities`:
| Area | What is tested |
|------|---------------|
| `parse_raw_orderbook_summary` | Parses raw bid/ask dicts into typed `OrderbookSummary` |
| `generate_orderbook_summary_hash` | Hash is deterministic and matches expected value |
| `order_to_json` | Serialises signed orders to the Polymarket API JSON format |
| `is_tick_size_smaller` | Compares tick size decimals correctly |
| `price_valid` | Validates price against tick size boundaries |
---
### `tests/order_builder/test_builder.py` (3445 lines)
Large test suite for `OrderBuilder`. Uses a well-known Hardhat private key on Amoy testnet. Tests cover:
| Area | What is tested |
|------|---------------|
| Market order price calculation | `calculate_buy_market_price` / `calculate_sell_market_price` for FOK/GTC with various orderbook depths |
| Limit order creation | `create_order` for BUY/SELL with EOA, POLY_GNOSIS_SAFE signature types |
| Market order creation | `create_market_order` for FOK fill-or-kill buys/sells |
| GTD orders | `expiration` field set correctly |
| Neg-risk markets | `neg_risk=True` changes token ID selection |
| Rounding | Various tick sizes (`0.1`, `0.01`, `0.001`) produce correctly rounded prices |
| Signature determinism | Same inputs → same EIP-712 signature |
### `tests/order_builder/test_helpers.py`
| Test area | What is tested |
|-----------|---------------|
| `decimal_places` | Counts decimal digits in float/string prices |
| `round_normal` | Rounds to N decimal places with HALF_UP |
---
### `tests/signing/test_eip712.py`
| Test | What it checks |
|------|---------------|
| `test_sign_clob_auth_message` | EIP-712 CLOB auth signature matches a known-good hex value for fixed timestamp/nonce |
---
### `tests/signing/test_hmac.py`
| Test area | What is tested |
|-----------|---------------|
| `test_build_hmac_signature_matches_expected` | HMAC-SHA256 output matches expected base64url string |
| `test_dict_body_same_as_equivalent_string_body` | Dict body serialised to match JSON string produces same signature |
| Variation tests | Changing any single input (secret, timestamp, method, path, body) changes the signature |
---
### `tests/headers/test_headers.py`
Tests `create_level_1_headers` and `create_level_2_headers`:
| Area | What is tested |
|------|---------------|
| Level-1 headers | `POLY_ADDRESS`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`, `POLY_NONCE` present and correctly formatted |
| Level-2 headers | Adds `POLY_API-KEY`, `POLY_PASSPHRASE`; HMAC signature over method+path+body |
---
### `tests/http_helpers/test_helpers.py`
Tests the low-level HTTP functions (`get`, `post`, `delete`) used by `ClobClient`. Covers request construction and basic response parsing.
---
### `tests/rfq/test_rfq_payload.py`
Tests `RfqClient._get_request_order_creation_payload` for both `COMPLEMENTARY` and `MIRROR` match types:
| Match type | What is verified |
|------------|-----------------|
| `COMPLEMENTARY` | Side flipped (BUY→SELL), size = `sizeIn`, price as float |
| `MIRROR` | Side preserved, size = `sizeOut`, price as float |
### `tests/rfq/test_rfq_query_params.py`
Tests query parameter serialisation for RFQ API calls (get-requests, get-quotes).
---
## Polymarket Integration Tests
### `tests/polymarket/test_polymarket_sync.py`
Marked `@pytest.mark.integration` — hits the live Gamma API.
| Test | What it checks |
|------|---------------|
| `test_sync_polymarket_markets_syncs_real_markets_to_db` | Sync inserts >5 markets; DB contents match returned objects; re-run returns empty list (idempotent) |
### `tests/polymarket/test_conditional_token_framework.py`
Marked `@pytest.mark.integration` — hits live Polygon RPC.
| Test | What it checks |
|------|---------------|
| `test_get_onchain_resolution_status_real_resolved_market` | Known resolved condition (`0xe3b423…`) has `slot_count = 2`, `resolved = True`, `winner_index = 1` |
---
## Coverage Map
| Component | Test files |
|-----------|-----------|
| `AgentPitServer` (API layer) | `tests/fastapi/test_*.py` |
| `ERC20Simulator` / `ERC1155Simulator` | `test_usdc.py`, `test_positions.py`, `test_resolution.py`, `test_lifecycle.py` |
| Market state machine | `test_lifecycle.py`, `test_markets.py` |
| Transaction history | `test_history.py` |
| Portfolio | `test_portfolio.py` |
| User / Agent / Personality CRUD | `test_create_user.py`, `test_personality.py`, `test_create_agent.py` |
| `OrderBuilder` | `tests/order_builder/test_builder.py` |
| EIP-712 signing | `tests/signing/test_eip712.py` |
| HMAC signing | `tests/signing/test_hmac.py` |
| Auth headers | `tests/headers/test_headers.py` |
| HTTP helpers | `tests/http_helpers/test_helpers.py` |
| `py_clob_client` utilities | `tests/test_utilities.py` |
| RFQ | `tests/rfq/test_rfq_payload.py`, `tests/rfq/test_rfq_query_params.py` |
| Polymarket sync | `tests/polymarket/test_polymarket_sync.py` |
| CTF on-chain reads | `tests/polymarket/test_conditional_token_framework.py` |
**Not covered by automated tests:**
- `TradingEngine` (no dedicated test file; exercised indirectly via `py_clob_client` integration)
- `PredictionMarket.splitInDbUSDCIntoEIP155Tokens` / `mergeInDbEIP1155TokensIntoUSDC` (the API server uses ERC20/ERC1155 simulators directly, not `PredictionMarket`)
- `nanobot/` agent framework (tests live in `tests/morph/` — nanobot's own suite)
