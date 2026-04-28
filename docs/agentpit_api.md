# AgentPit API — Developer Guide
## Overview
AgentPit exposes a local **FastAPI** server (`AgentPitServer`) that simulates a prediction-market platform. It manages markets, simulated USDC balances, ERC-1155 outcome tokens, and AI agent profiles — all backed by a local SQLite database.
> **Not connected to real money.** USDC and tokens are simulated in SQLite. The server is designed for agent development and backtesting against Polymarket-synced data.
---
## Quick Start
```bash
# 1. Install dependencies
make init
# 2. Start the server
uvicorn agentpit.fastapi.main:app --host 0.0.0.0 --port 8000 --reload
# 3. Verify it's running
curl http://localhost:8000/
# {"version":"1.0"}
```
---
## Base URL
```
http://localhost:8000
```
---
## Authentication
There is no bearer-token auth layer. API calls that modify state pass an `api_key` field in the request body or as a path parameter. An `api_key` is returned when you call `POST /create_user`.
Each `api_key` maps to a unique Ethereum address generated at user creation time. This address is used as the wallet for USDC and ERC-1155 token balances.
---
## Core Concepts
### Condition ID
A `condition_id` is a `bytes32` hex string that uniquely identifies a market. For locally-created markets it is computed as:
```
condition_id = keccak256(
    oracle_address (20 bytes)
  + keccak256(question_text) (32 bytes, the "questionId")
  + outcome_slot_count (uint256, 32 bytes)
)
```
The oracle address is fixed at `0xCB1822859cEF82Cd2Eb4E6276C7916e692995130` (EasyNet). For markets synced from Polymarket, the condition ID comes directly from the Gamma API.
### ERC-1155 Outcome Tokens
Each market has one outcome token per possible outcome (e.g. `["Yes", "No"]`). Tokens are stored as a JSON array of `[token_id, label]` pairs in the `markets` table. Balances are tracked in the `erc1155_token_ownership` table as JSON maps keyed by token ID.
### Complete Sets
A **complete set** is 1 unit of every outcome token for a given market. They always trade at a combined value of 1 USDC.
- **Split** = burn 1 USDC → receive 1 of each outcome token
- **Merge** = burn 1 of each outcome token → receive 1 USDC
- **Redeem** (after resolution) = burn all tokens → receive 1 USDC per winning token held
### Market State Machine
```
  POST /markets
       │
       ▼
    DRAFT ──────────────────────────────────► CANCELLED
       │                                         ▲
       │ POST /activate                          │
       ▼                                         │
    ACTIVE ─────────────────────────────────────┤
       │                                         │
       │ POST /close                             │
       ▼                                         │
    CLOSED ─────────────────────────────────────┘
       │
       │ POST /resolve
       ▼
    RESOLVED
```
| State | Can split/merge | Can redeem | Can cancel |
|-------|----------------|------------|------------|
| DRAFT | No | No | Yes |
| ACTIVE | Yes | No | Yes |
| CLOSED | No | No | Yes |
| RESOLVED | No | Yes | No |
| CANCELLED | No | No | No |
---
## Database Schema (SQLite)
All tables are created by `TableCreate.create_all_tables()` on server startup.
### `markets`
| Column | Type | Description |
|--------|------|-------------|
| `MARKET_ID` | INTEGER PK | Auto-incrementing local ID |
| `CONDITION_ID` | TEXT UNIQUE | hex-256 condition identifier |
| `POLYMARKET_ID` | INTEGER | Optional source ID from Polymarket |
| `QUESTION` | TEXT | Question string (used to derive `condition_id`) |
| `SLUG` | TEXT | URL-safe identifier |
| `DESCRIPTION` | TEXT | Human-readable description |
| `ERC1155_TOKENS` | TEXT | JSON array of `[token_id, label]` pairs |
| `START_DATE` | INTEGER | Unix timestamp |
| `END_DATE` | INTEGER | Unix timestamp (nullable) |
| `RESOLVED_OUTCOME` | INTEGER | Index of winning outcome (nullable) |
| `MARKET_STATE` | TEXT | One of `DRAFT/ACTIVE/CLOSED/RESOLVED/CANCELLED` |
### `users`
| Column | Type | Description |
|--------|------|-------------|
| `USER_ID` | TEXT PK | Human-readable handle |
| `API_KEY` | TEXT UNIQUE | UUID issued at creation |
| `ETH_PRIVATE_KEY` | TEXT UNIQUE | Hex-encoded private key (generated locally) |
### `erc20_token_ownership`
| Column | Type | Description |
|--------|------|-------------|
| `ETH_ADDRESS` | TEXT PK | Normalised checksummed address |
| `OWNERSHIP` | TEXT | JSON map: `{ asset_address: hex_uint256_balance }` |
### `erc1155_token_ownership`
| Column | Type | Description |
|--------|------|-------------|
| `ETH_ADDRESS` | TEXT PK | Normalised checksummed address |
| `OWNERSHIP` | TEXT | JSON map: `{ token_id: hex_uint256_balance }` |
### `transactions`
| Column | Type | Description |
|--------|------|-------------|
| `TRANSACTION_ID` | INTEGER PK | Auto-increment |
| `TIMESTAMP` | DATETIME | UTC timestamp of the operation |
| `API_KEY` | TEXT | Which user performed the action |
| `TRANSACTION_TYPE` | TEXT | `SPLIT`, `MERGE`, or `REDEEM` |
| `MARKET_ID` | INTEGER | Related market |
| `DETAILS` | TEXT | JSON details (amounts, tokens) |
### `agents` / `personalities`
See [Agents & Personalities](#agents--personalities) section.
---
## Error Format
All errors return standard FastAPI/HTTP status codes with a JSON body:
```json
{ "detail": "Human-readable error message" }
```
Validation failures from `check_state()` include the source file, line number, and expression for debugging:
```json
{
  "detail": "Check failed::check_state(len(self.api_key) > 0) \n agentpit/datastructures/...:12 model_post_init(): api_key must not be empty"
}
```
---
## Endpoints
---
### GET `/`
Returns the server version.
```bash
curl http://localhost:8000/
```
**Response**
```json
{ "version": "1.0" }
```
---
## Users
### POST `/create_user`
Create a new named user. AgentPit generates a UUID `api_key` and a fresh Ethereum keypair for the user.
```bash
curl -X POST http://localhost:8000/create_user \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice"}'
```
**Request Body**
| Field | Type | Constraints |
|-------|------|-------------|
| `user_id` | string | 1–15 chars, `[a-zA-Z0-9_]` only |
**Response**
```json
{
  "user_id": "alice",
  "api_key": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "eth_address": "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113"
}
```
**Errors**
- `409` — `user_id` already exists
---
## USDC
### POST `/mint_usdc`
Credit simulated USDC to a user's wallet. There is no supply cap — this is for testing.
```bash
curl -X POST http://localhost:8000/mint_usdc \
  -H "Content-Type: application/json" \
  -d '{"api_key": "<key>", "amount": 10000}'
```
**Request Body**
| Field | Type | Constraints |
|-------|------|-------------|
| `api_key` | string | Non-empty |
| `amount` | int | > 0 |
**Response**
```json
{ "eth_address": "0x...", "amount": 10000, "new_balance": 10000 }
```
---
### GET `/usdc_balance/{api_key}`
```bash
curl http://localhost:8000/usdc_balance/\<key\>
```
**Response**
```json
{ "eth_address": "0x...", "balance": 10000 }
```
---
### POST `/transfer_usdc`
Transfer USDC from a user's wallet to any Ethereum address.
```bash
curl -X POST http://localhost:8000/transfer_usdc \
  -H "Content-Type: application/json" \
  -d '{"api_key": "<key>", "destination_address": "0xABC...", "amount": 500}'
```
**Request Body**
| Field | Type | Constraints |
|-------|------|-------------|
| `api_key` | string | Non-empty |
| `destination_address` | string | Valid Ethereum address |
| `amount` | int | > 0 |
**Response**
```json
{ "from_address": "0x...", "to_address": "0x...", "amount": 500, "new_balance": 9500 }
```
**Errors**
- `400` — insufficient balance
---
## Markets
### GET `/markets`
```bash
curl "http://localhost:8000/markets?limit=10&offset=0"
```
**Query Parameters**
| Param | Type | Default | Max |
|-------|------|---------|-----|
| `limit` | int | 100 | 1000 |
| `offset` | int | 0 | — |
**Response**
```json
{
  "markets": [ { ...Market } ],
  "total": 42,
  "limit": 10,
  "offset": 0
}
```
---
### POST `/markets`
Create a new market. The `condition_id` is computed from the question text and outcome count using `keccak256`. If you pass a `condition_id` explicitly it is used as-is.
```bash
curl -X POST http://localhost:8000/markets \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Will ETH exceed $10k in 2026?",
    "description": "Resolves YES if Ethereum price exceeds $10,000 USD at any point during 2026.",
    "erc1155_tokens": [["0xaaa...", "Yes"], ["0xbbb...", "No"]],
    "end_date": 1767225600
  }'
```
**Request Body**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `question` | string | ✓ | Market question |
| `description` | string | ✓ | Detailed description |
| `erc1155_tokens` | list[tuple[str,str]] | ✓ | `[token_id, label]` per outcome |
| `slug` | string | — | Auto-generated from question if omitted |
| `start_date` | int | — | Unix timestamp (defaults to `now()`) |
| `end_date` | int | — | Unix timestamp; must be ≥ `start_date` |
| `polymarket_id` | int | — | Reference ID if mirroring a Polymarket market |
| `condition_id` | string | — | Explicit hex-256 condition ID |
| `state` | string | — | Initial state; default `DRAFT` |
**Response** — `Market` object (see [Market Schema](#market-schema))
---
### GET `/markets/{market_id}`
```bash
curl http://localhost:8000/markets/1
```
**Errors** — `404` if not found
---
### POST `/markets/{market_id}/activate`
Transition `DRAFT → ACTIVE`. Once active, users can split and merge positions.
```bash
curl -X POST http://localhost:8000/markets/1/activate
```
**Errors** — `400` if not in `DRAFT` state
---
### POST `/markets/{market_id}/close`
Transition `ACTIVE → CLOSED`. Prevents further splits/merges. Market awaits resolution.
```bash
curl -X POST http://localhost:8000/markets/1/close
```
**Errors** — `400` if not in `ACTIVE` state
---
### POST `/markets/{market_id}/resolve`
Declare the winning outcome. The `winning_outcome_index` is the zero-based index into the `erc1155_tokens` array.
```bash
curl -X POST http://localhost:8000/markets/1/resolve \
  -H "Content-Type: application/json" \
  -d '{"winning_outcome_index": 0}'
```
**Request Body**
| Field | Type | Description |
|-------|------|-------------|
| `winning_outcome_index` | int | 0-based index of the winning outcome |
**Response** — `Market` object with `market_state: "RESOLVED"` and `resolved_outcome` set
**Errors** — `400` invalid index or state, `404` not found
---
### POST `/markets/{market_id}/cancel`
Cancel a market from any non-terminal state. All users holding **complete sets** (equal amounts of every outcome token) are automatically refunded 1 USDC per set.
> Partial holdings (e.g. only "Yes" tokens) are **not** refunded on cancel.
```bash
curl -X POST http://localhost:8000/markets/1/cancel
```
**Response**
```json
{
  "market_id": 1,
  "message": "Market cancelled successfully",
  "refunds_processed": 3,
  "market": { ...Market }
}
```
**Errors** — `400` if already `RESOLVED` or `CANCELLED`
---
## Positions
### POST `/markets/{market_id}/split_position`
Buy a complete set: burn `amount` USDC, receive `amount` of each outcome token.
**Example:** `amount=100` on a Yes/No market burns 100 USDC, mints 100 Yes tokens + 100 No tokens.
```bash
curl -X POST http://localhost:8000/markets/1/split_position \
  -H "Content-Type: application/json" \
  -d '{"api_key": "<key>", "amount": 100}'
```
**Request Body**
| Field | Type | Constraints |
|-------|------|-------------|
| `api_key` | string | Non-empty |
| `amount` | int | > 0 |
**Response**
```json
{
  "market_id": 1,
  "amount": 100,
  "collateral_amount": 100,
  "token_balances": { "0xaaa...": 100, "0xbbb...": 100 }
}
```
**Errors** — `400` insufficient USDC / `404` market not found
---
### POST `/markets/{market_id}/merge_positions`
Sell a complete set: burn `amount` of each outcome token, receive `amount` USDC.
You must hold at least `amount` of **every** outcome token, otherwise the call fails.
```bash
curl -X POST http://localhost:8000/markets/1/merge_positions \
  -H "Content-Type: application/json" \
  -d '{"api_key": "<key>", "amount": 50}'
```
**Request/Response** — same schema as `split_position`
**Errors** — `400` with message `"Insufficient balance of token <id>: have X, need Y"`
---
### POST `/markets/{market_id}/redeem_position`
After a market resolves, burn all held outcome tokens and collect USDC for winning tokens.
- **Winning tokens** → 1 USDC each
- **Losing tokens** → 0 USDC (burned anyway)
```bash
curl -X POST http://localhost:8000/markets/1/redeem_position \
  -H "Content-Type: application/json" \
  -d '{"api_key": "<key>"}'
```
**Request Body**
| Field | Type | Description |
|-------|------|-------------|
| `api_key` | string | Non-empty |
**Response**
```json
{
  "market_id": 1,
  "payout_usdc": 100,
  "tokens_redeemed": { "0xaaa...": 100, "0xbbb...": 50 }
}
```
**Errors** — `400` market not resolved, `404` market not found
---
## Portfolio & History
### GET `/portfolio/{api_key}`
Full snapshot of a user's USDC balance and all non-zero outcome token positions across every market.
```bash
curl http://localhost:8000/portfolio/\<key\>
```
**Response**
```json
{
  "eth_address": "0x...",
  "usdc_balance": 9400,
  "positions": [
    {
      "market_id": 1,
      "question": "Will ETH exceed $10k in 2026?",
      "token_id": "0xaaa...",
      "outcome_label": "Yes",
      "outcome_index": 0,
      "balance": 100
    }
  ]
}
```
> **Note:** The portfolio scan iterates all markets to find token matches. In large DBs this may be slow; a production deployment would use a proper index.
---
### GET `/markets/history/{api_key}`
Full transaction log for a user, ordered by time.
```bash
curl http://localhost:8000/markets/history/\<key\>
```
**Response**
```json
{
  "eth_address": "0x...",
  "transactions": [
    {
      "transaction_id": 1,
      "timestamp": "2026-04-28 10:00:00",
      "transaction_type": "SPLIT",
      "market_id": 1,
      "details": { "amount": 100, "collateral_burned": 100 }
    }
  ]
}
```
**Transaction types and `details` fields:**
| Type | Details keys |
|------|-------------|
| `SPLIT` | `amount`, `collateral_burned` |
| `MERGE` | `amount`, `collateral_minted` |
| `REDEEM` | `payout_usdc`, `tokens_redeemed` |
---
## Agents & Personalities
Agents and personalities are used by the `nanobot/` framework for AI agent simulation.
### POST `/create_personality`
Define a personality profile that drives agent behaviour.
```bash
curl -X POST http://localhost:8000/create_personality \
  -H "Content-Type: application/json" \
  -d '{
    "personality_id": "bull_trader",
    "title": "Bull Trader",
    "beliefs": "Markets always recover long-term.",
    "methods": "Buy dips, hold through volatility.",
    "needs": "Maximize portfolio value over 12 months."
  }'
```
**Request Body**
| Field | Type | Description |
|-------|------|-------------|
| `personality_id` | string | Unique identifier |
| `title` | string | Human-readable name |
| `beliefs` | string | Worldview / priors |
| `methods` | string | Decision-making strategy |
| `needs` | string | Goals and constraints |
**Response**
```json
{
  "personality_id": "bull_trader",
  "title": "Bull Trader",
  "spec": {
    "beliefs": "Markets always recover long-term.",
    "methods": "Buy dips, hold through volatility.",
    "needs": "Maximize portfolio value over 12 months."
  }
}
```
**DB storage:** `spec` is stored as a compact JSON string in `PERSONALITY_SPEC`.
---
### POST `/create_agent`
Instantiate an agent linked to an existing personality.
```bash
curl -X POST http://localhost:8000/create_agent \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "agent_01", "personality_id": "bull_trader"}'
```
**Request Body**
| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | string | Unique agent identifier |
| `personality_id` | string | Must reference an existing personality |
**Response**
```json
{
  "agent_id": "agent_01",
  "personality_id": "bull_trader",
  "state": {},
  "history": [],
  "todo": []
}
```
**Errors** — `404` personality not found / `409` agent already exists
---
## Market Schema
```json
{
  "market_id": 1,
  "question": "Will ETH exceed $10k in 2026?",
  "slug": "will-eth-exceed-10k-in-2026",
  "description": "Resolves YES if Ethereum price exceeds $10,000 USD...",
  "erc1155_tokens": [
    ["0xaaa...", "Yes"],
    ["0xbbb...", "No"]
  ],
  "start_date": 1745000000,
  "end_date": 1767225600,
  "market_state": "ACTIVE",
  "resolved_outcome": null,
  "polymarket_id": null,
  "condition_id": "0xe3b423..."
}
```
---
## Worked Example: Full Market Lifecycle
```bash
# 1. Create a user and get funded
curl -X POST http://localhost:8000/create_user -d '{"user_id":"alice"}' | jq .api_key
# → "abc-123"
curl -X POST http://localhost:8000/mint_usdc \
  -d '{"api_key":"abc-123","amount":1000}'
# 2. Create and activate a market
MARKET_ID=$(curl -sX POST http://localhost:8000/markets \
  -H "Content-Type: application/json" \
  -d '{"question":"Will it rain?","description":"Weather market","erc1155_tokens":[["0x1","Yes"],["0x2","No"]]}' \
  | jq .market_id)
curl -X POST http://localhost:8000/markets/$MARKET_ID/activate
# 3. Buy a complete set (100 USDC → 100 Yes + 100 No)
curl -X POST http://localhost:8000/markets/$MARKET_ID/split_position \
  -d '{"api_key":"abc-123","amount":100}'
# 4. Close and resolve (Yes wins)
curl -X POST http://localhost:8000/markets/$MARKET_ID/close
curl -X POST http://localhost:8000/markets/$MARKET_ID/resolve \
  -d '{"winning_outcome_index":0}'
# 5. Redeem: get 100 USDC back (100 Yes tokens win, 100 No tokens burned)
curl -X POST http://localhost:8000/markets/$MARKET_ID/redeem_position \
  -d '{"api_key":"abc-123"}'
```
---
## Concurrency Model
`AgentPitServer` uses a `ReaderWriterLock` (`fasteners.ReaderWriterLock`) around all database operations:
- **Read endpoints** (`GET`) acquire a shared read lock.
- **Write endpoints** (`POST`) acquire an exclusive write lock.
All DB methods are called inside `with self._db:` (SQLite transaction context manager). Errors propagate — there is no silent exception swallowing.
