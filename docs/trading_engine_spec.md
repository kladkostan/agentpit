# Trading Engine — Design Specification
## Purpose
`agentpit/trading_engine.py` is an in-process, [SQLite](https://www.sqlite.org)-backed **Central Limit Order Book (CLOB)** engine. It accepts signed [Polymarket](https://polymarket.com)-compatible orders, matches them against resting liquidity using price-time priority, records confirmed trades, and manages order lifecycle (expiry, cancellation).
The engine is used in two modes:
| Mode | How activated | Who calls it |
|------|--------------|--------------|
| **AgentPit sandbox** | `ClobClient(host="https://api.agentpit.ai")` | [`py_clob_client`](https://github.com/Polymarket/py-clob-client) routes calls to `TradingEngine` directly |
| **Live Polymarket** | `ClobClient(host="https://clob.polymarket.com")` | Standard HTTP calls to the [Polymarket CLOB API](https://docs.polymarket.com); `TradingEngine` is not involved |
The local mode is detected in `py_clob_client/client.py` by the `# BEGIN_AGENTPIT` guards:
```python
if self.host == "":
    return self.agentpit_client.process_new_order(order, orderType, post_only)
```
---
## Key Concepts
### Order Sides
| `order.side` int | String | Meaning |
|-----------------|--------|---------|
| `0` | `BUY` | Maker gives USDC collateral, receives outcome tokens |
| `1` | `SELL` | Maker gives outcome tokens, receives USDC collateral |
### Price Representation
Prices are stored as **integer micro-USDC** (6 decimal places):
```
price_int = round(collateral / asset_tokens x 10^6)
```
For a **BUY** order: `price = makerAmount / takerAmount x 10^6`
For a **SELL** order: `price = takerAmount / makerAmount x 10^6`
Rounding uses `ROUND_HALF_UP` via Python `Decimal`.
Examples: `0.75` -> `750000`, `0.01` -> `10000`
### Order Types
| Type | Behaviour |
|------|-----------|
| `GTC` | Good-Till-Cancelled. Rests in the book until filled or cancelled. |
| `GTD` | Good-Till-Date. Same as GTC but auto-expires at `expiration` Unix timestamp. |
| `FOK` | Fill-Or-Kill. Must be fully filled immediately; otherwise cancelled entirely. |
| `FAK` | Fill-And-Kill. Fills as much as possible immediately; unfilled remainder is cancelled. |
### Order Status
| Value | Meaning |
|-------|---------|
| `live` | Resting in the book, eligible for matching |
| `matched` | Fully filled (`REMAINING_AMOUNT == 0`) |
| `expired` | GTD order past its `EXPIRATION` timestamp |
| `cancelled` | Explicitly cancelled, FOK dry-run failed, or FAK leftover |
### Order ID
Order IDs are Polymarket-compatible [EIP-712](https://eips.ethereum.org/EIPS/eip-712) struct hashes:
```python
domain = get_clob_auth_domain(chain_id)
signable = order.signable_bytes(domain)
order_id = "0x" + keccak256(signable).hex()
```
The same signed order always produces the same ID regardless of which node processes it.
---
## Class: `TradingEngine`
```python
engine = TradingEngine(
    api_key="my-api-key",
    chain_id=137,            # Polygon mainnet
    full_path=Path("agentpit.db"),
)
```
Owns its own `sqlite3.Connection` (`self.db`) with `row_factory = sqlite3.Row` and a `threading.Lock` (`self._lock`). All table creation happens in `__init__` via `TableCreate.create_all_tables`.
---
## Public Methods
### `process_new_order(signed_order, order_type, post_only) -> str (JSON)`
Main entry point. Called for every incoming order.
**Full flow:**
```
process_new_order(signed_order, order_type, post_only)
        │
        ▼
_process_expired_orders()
  UPDATE orders SET STATUS='expired'
  WHERE ORDER_TYPE='GTD' AND STATUS='live' AND EXPIRATION <= now
        │
        ▼
add_order_to_db()
  compute order_id  (EIP-712 keccak)
  compute price_int (scaled micro-USDC)
  INSERT → STATUS='live', REMAINING_AMOUNT=makerAmount
        │
        ▼
   order_type == FOK?
   ┌────┴─────┐
  yes         no
   │           │
   ▼           │
dry-run        │
_match_and_fill_order(dry_run=True)
   │                         │
remainder > 0          remainder == 0
   │                         │
cancel order           proceed to real match
   │                         │
   └──────────┬──────────────┘
              │
              ▼  (skip if post_only or FOK-cancelled)
_match_and_fill_order(dry_run=False)
  price-time priority fill loop
        │
        ▼
compute avgPrice = total_spent / filled × 10^6
        │
        ▼
return OrderResponse (JSON)
```
       total_spent, remaining, status = _match_and_fill_order(order_id)
   else:
       remaining = makerAmount   (order rests; no matching)
5. filled = makerAmount - remaining
   avgPrice = total_spent / filled x 10^6   (None if filled == 0)
6. Return JSON-serialised OrderResponse
```
**Returns:** JSON string — see [OrderResponse](#orderresponse).
---
### `process_new_orders(args: list[PostOrdersArgs]) -> str (JSON)`
Iterates `args` and calls `process_new_order` for each. Returns a JSON array of `OrderResponse` dicts.
---
### `add_order_to_db(signed_order, order_type, post_only) -> str`
Inserts a new row into the `orders` table and returns the `order_id`.
Key computed fields:
| Field | How computed |
|-------|-------------|
| `ORDER_ID` | `keccak256(order.signable_bytes(domain))` |
| `PRICE` | `_get_price_int(order)` |
| `SIDE` | `"BUY"` if `order.side == 0` else `"SELL"` |
| `ORDER_TYPE` | `"GTC"` / `"GTD"` / `"FOK"` / `"FAK"` |
| `SIGNATURE_TYPE` | `0` -> `"EIP712"`, `1` -> `"ETHSIGN"`, `2` -> `"EOA"` |
| `REMAINING_AMOUNT` | `= MAKER_AMOUNT` (starts fully unfilled) |
| `STATUS` | `"live"` |
| `CREATED_AT` | `utcnow()` Unix timestamp |
| `ORDER_JSON` | Full serialised body via `order_to_json()` |
---
### `cancel_order(order_id) -> bool`
Sets `STATUS = 'cancelled'` only if the order is currently `'live'`. Returns `True` if a row was updated, `False` otherwise (already matched, expired, cancelled, or not found).
```sql
UPDATE orders SET STATUS = 'cancelled'
WHERE ORDER_ID = ? AND STATUS = 'live'
```
---
### `cancel_orders(order_ids: list[str]) -> list[bool]`
Calls `cancel_order` for each ID in order. Returns a parallel list of booleans.
---
## Matching Engine Internals
### `_match_and_fill_order(order_id, dry_run=False) -> (total_spent, remaining, status)`
Core matching loop:
```
1. _get_existing_order(order_id)
       SELECT * FROM orders WHERE ORDER_ID = ? AND STATUS = 'live'
       raises RuntimeError if not found / not live
2. candidates = _get_sorted_candidates(taker_side, taker_price, token_id)
3. for maker in candidates:
       if taker_remaining == 0: break
       match = _fill_order(maker, taker, taker_remaining, dry_run)
       taker_remaining -= match.trade_size
4. total_spent = sum(match.price x match.trade_size for each match)
5. if not dry_run:
       _update_taker_remaining_in_db(order_id, taker_remaining)
       set_order_type_to_cancelled_if_order_is_fak_and_order_status_is_live(order_id)
6. return (total_spent, taker_remaining, get_order_status(order_id))
```
`dry_run=True` skips only the **taker**-side writes (`_update_taker_remaining_in_db` and the FAK cancel). Importantly, `_fill_order` is always called **without** a `dry_run` flag, so maker-order DB updates and trade-row insertions still occur even during the FOK dry run. If the FOK then cancels (remainder > 0), those maker updates remain in the DB. This is a known implementation detail — see `missing_features_for_mvp.md` for planned corrections.
---
### `_get_sorted_candidates(taker_side, taker_price, token_id) -> list[Row]`
Returns eligible resting maker orders, price-time sorted.

**Price-time priority — example (taker BUY @ 0.65, needs 150 units):**
```
Resting SELL orders after SQL filter (PRICE <= 650000):

  Price   Size   Time      Priority
  ──────────────────────────────────
  0.58     40    10:01     ← fill 1st  (cheapest)
  0.60    100    09:55     ← fill 2nd  (next price)
  0.60     60    10:03     ← fill 3rd  (same price, later time)
  0.63     20    10:00     ← fill 4th
  0.65     80    10:02     ← fill 5th

Fill sequence for 150 units:
  40  × 0.58  →  order fully consumed
  100 × 0.60  →  order fully consumed
  10  × 0.60  →  partial (60 available, only 10 needed) → taker done
```

**SQL price filter:**
| Taker | SQL condition |
|-------|--------------|
| `BUY` | `SIDE='SELL' AND PRICE <= taker_price AND TOKEN_ID = ? AND STATUS='live'` |
| `SELL` | `SIDE='BUY' AND PRICE >= taker_price AND TOKEN_ID = ? AND STATUS='live'` |
**Sort (`_sort_candidates`):**
| Taker | Sort key |
|-------|---------|
| `BUY` | `(PRICE ASC, CREATED_AT ASC)` — cheapest seller first, then oldest |
| `SELL` | `(PRICE DESC, CREATED_AT ASC)` — highest bidder first, then oldest |
This is standard price-time priority (FIFO within a price level).
---
### `_fill_order(maker, maker_remaining, taker, taker_remaining, dry_run=False) -> Match`
```
trade_size = min(taker_remaining, maker_remaining)
if not dry_run:
    _update_maker_remaining_in_db(maker.ORDER_ID, maker_remaining - trade_size)
    _insert_trade_row(taker_row, maker_row, trade_size, taker_remaining - trade_size)
return Match(taker_order_id, maker_order_id, price=maker.PRICE, trade_size)
```
Trade price is always the **maker's price** (passive side sets the price, taker accepts it).
---
### `_update_taker_remaining_in_db` / `_update_maker_remaining_in_db`
Identical pattern for both sides:
```sql
UPDATE orders
SET REMAINING_AMOUNT = ?,
    STATUS = CASE WHEN ? = 0 THEN 'matched' ELSE 'live' END
WHERE ORDER_ID = ?
```
When `REMAINING_AMOUNT` hits 0 the status is atomically flipped to `'matched'`.
---
### `_insert_trade_row(taker_row, maker_row, trade_size, remaining_taker)`
Inserts one row into the `trades` table:
| Column | Value |
|--------|-------|
| `TRADE_ID` | `"{taker_id}-{maker_id}-{uuid4()}"` |
| `TAKER_ORDER_ID` | taker order ID |
| `MAKER_ORDERS` | JSON: `[{"order_id":..., "owner":..., "matched_amount":...}]` |
| `MARKET` / `ASSET_ID` | `taker.TOKEN_ID` |
| `PRICE` | `maker.PRICE` (micro-USDC) |
| `TRADE_SIZE` | units matched |
| `REMAINING_SIZE` | taker remaining after this fill |
| `SIDE` | taker's side |
| `STATUS` | always `"CONFIRMED"` |
| `MATCH_TIME` | `utcnow()` Unix timestamp |
| `TRANSACTION_HASH` | `""` (no on-chain tx in simulation) |
| `FEE_RATE_BPS` | from taker order |
---
## Order Expiry
### `_process_expired_orders() -> int`
Runs at the start of every `process_new_order` call:
```sql
UPDATE orders SET STATUS = 'expired'
WHERE ORDER_TYPE = 'GTD'
  AND STATUS = 'live'
  AND EXPIRATION <= <now_unix>
```
Returns row count. There is no background timer — expiry is driven lazily by incoming order activity.
---
## FOK and FAK Details
### FOK (Fill-Or-Kill)
```
INSERT order (live)
        │
        ▼
dry-run match (no DB writes)
        │
  remainder > 0?
  ┌─────┴──────┐
 yes           no
  │             │
cancel        run real match
0% fill       100% fill guaranteed
```
Atomicity: the order either fills completely or not at all.

### FAK (Fill-And-Kill)
```
INSERT order (live)
        │
        ▼
real match (fills as much as possible)
        │
  still live after match?
  ┌─────┴──────┐
 yes           no
  │             │
cancel        done (fully matched)
remainder
```
The conditional cancel SQL:
```sql
UPDATE orders SET STATUS = 'cancelled'
WHERE ORDER_ID = ? AND ORDER_TYPE = 'FAK' AND STATUS = 'live'
```
### Post-Only
Matching is skipped entirely. The order rests in the book as a maker-only resting order. No immediate-fill error is raised if it would have crossed — the current implementation simply stores it live.
---
## Price Calculation Detail (`_get_price_int`)
```python
USDC_SCALE = Decimal(10 ** 6)
# BUY: maker gives collateral, receives tokens
#   price = collateral / tokens
price = Decimal(makerAmount) / Decimal(takerAmount)
# SELL: maker gives tokens, receives collateral
#   price = collateral / tokens
price = Decimal(takerAmount) / Decimal(makerAmount)
price_int = int((price * USDC_SCALE).to_integral_value(ROUND_HALF_UP))
```
Both sides express price as `USDC per token`, scaled to 6 decimals.
---
## Database Schemas
### `orders` table
| Column | Type | Description |
|--------|------|-------------|
| `ORDER_ID` | TEXT PK | EIP-712 keccak hash |
| `API_KEY` | TEXT | Owner API key |
| `PRICE` | INTEGER | Integer micro-USDC price |
| `POST_ONLY` | INTEGER | 1 = post-only |
| `ORDER_TYPE` | TEXT | `GTC`, `GTD`, `FOK`, `FAK` |
| `SALT` | INTEGER | Order salt |
| `MAKER` | TEXT | Maker address |
| `TAKER` | TEXT | Taker address |
| `SIGNER` | TEXT | Signer address |
| `TOKEN_ID` | TEXT | Outcome token ID |
| `MAKER_AMOUNT` | INTEGER | Original maker amount |
| `TAKER_AMOUNT` | INTEGER | Original taker amount |
| `EXPIRATION` | INTEGER | GTD expiry Unix timestamp |
| `NONCE` | INTEGER | Order nonce |
| `FEE_RATE_BPS` | INTEGER | Fee rate in basis points |
| `SIDE` | TEXT | `"BUY"` or `"SELL"` |
| `SIGNATURE_TYPE` | TEXT | `"EIP712"`, `"ETHSIGN"`, `"EOA"` |
| `ORDER_JSON` | TEXT | Full serialised order body |
| `STATUS` | TEXT | `live`, `matched`, `expired`, `cancelled` |
| `REMAINING_AMOUNT` | INTEGER | Decremented on each fill |
| `CREATED_AT` | INTEGER | Insertion Unix timestamp |
Indexes:
- `idx_orders_price_side` on `(PRICE, SIDE)` — candidate query
- `idx_orders_order_type_status_expiration` on `(ORDER_TYPE, STATUS, EXPIRATION)` — expiry sweep
- `idx_orders_status_expiration` on `(STATUS, EXPIRATION)`
- `idx_orders_api_key` on `(API_KEY)`
### `trades` table
| Column | Type | Description |
|--------|------|-------------|
| `TRADE_ID` | TEXT PK | Composite UUID |
| `TAKER_ORDER_ID` | TEXT | Taker order ID |
| `MAKER_ORDERS` | TEXT | JSON array of maker contributions |
| `MARKET` | TEXT | Token ID |
| `ASSET_ID` | TEXT | Same as MARKET |
| `PRICE` | INTEGER | Fill price (micro-USDC) |
| `TRADE_SIZE` | INTEGER | Units traded |
| `REMAINING_SIZE` | INTEGER | Taker remaining after fill |
| `SIDE` | TEXT | Taker's side |
| `STATUS` | TEXT | Always `"CONFIRMED"` |
| `MATCH_TIME` | INTEGER | Unix timestamp |
| `TRANSACTION_HASH` | TEXT | `""` (no on-chain tx) |
| `BUCKET_INDEX` | INTEGER | `0` |
| `FEE_RATE_BPS` | INTEGER | From taker order |
---
## Supporting Dataclasses
### `Match`
Internal only — not persisted. Passed from `_fill_order` back to `_match_and_fill_order`.
```python
class Match(BaseModel):
    taker_order_id: str
    maker_order_id: str
    price: int        # integer micro-USDC; must be > 0
    trade_size: int   # must be > 0
```
### `Trade`
Persisted to `trades`. Validated: `len(maker_orders) > 0`.
### `OrderResponse`
Returned as JSON from `process_new_order`:
| Field | Type | Notes |
|-------|------|-------|
| `success` | bool | Always `True` |
| `orderID` | str | EIP-712 order hash |
| `status` | str | Final order status |
| `filledSize` | str | Units filled (makerAmount basis) |
| `remainingSize` | str | Units remaining |
| `avgPrice` | str | None | Volume-weighted fill price; `None` if unfilled |
| `errorMsg` | str | None | Always `None` on success |
---
## Integration with `py_clob_client`
`TradingEngine` is a drop-in local replacement for the Polymarket CLOB. `ClobClient` checks `host == ""` and routes directly:
| `ClobClient` method | `TradingEngine` method |
|---------------------|----------------------|
| `post_order(order, orderType, post_only)` | `process_new_order(...)` |
| `post_orders(args)` | `process_new_orders(args)` |
| `cancel(order_id)` | `cancel_order(order_id)` |
| `cancel_orders(order_ids)` | `cancel_orders(order_ids)` |
Agents built against `ClobClient` work identically whether pointed at the local engine or live Polymarket — no code changes needed to switch modes.
---
## Worked Example: GTC Limit Order Match
```
Token: 0xaaa (Yes outcome)
Step 1 — Alice posts SELL at 0.60:
  makerAmount=100 tokens, takerAmount=60 USDC, GTC
  -> PRICE=600000, SIDE='SELL', STATUS='live', REMAINING=100
Step 2 — Bob posts BUY at 0.65:
  makerAmount=65 USDC, takerAmount=100 tokens, GTC
  -> PRICE=650000, SIDE='BUY'
  -> candidates: [Alice @ 600000] (SELL, PRICE <= 650000)
  -> _fill_order: trade_size = min(100, 100) = 100
  -> Alice: REMAINING=0, STATUS='matched'
  -> Bob:   REMAINING=0, STATUS='matched'
  -> trade: PRICE=600000, SIZE=100
OrderResponse (Bob):
  filledSize="65", remainingSize="0"
  avgPrice="600000", status="matched"
```
---
## Worked Example: FOK — Not Filled
```
No resting SELL orders for token 0xaaa.
Bob posts FOK BUY at 0.50 for 100 tokens:
  -> dry-run: candidates = [] (no SELLs at PRICE <= 500000)
  -> dry_run_remaining = 100 > 0
  -> set_order_status(CANCELLED)
OrderResponse (Bob):
  filledSize="0", remainingSize="100"
  avgPrice=None, status="cancelled"
```
---
## Instantiating for Tests
The engine accepts an in-memory SQLite path:
```python
from pathlib import Path
from agentpit.trading_engine import TradingEngine
engine = TradingEngine(
    api_key="test-key",
    chain_id=137,
    full_path=Path(":memory:"),
)
```
All tables are created automatically. No server startup needed.

---

## See Also

- [`ONBOARDING.md`](ONBOARDING.md) — dev environment setup, first-contribution guide
- [`high_level_design.md`](high_level_design.md) — how `TradingEngine` fits into the overall architecture
- [`agentpit_api.md`](agentpit_api.md) — REST endpoints that eventually wrap this engine (`POST /orders` — MVP roadmap)
- [`missing_features_for_mvp.md`](missing_features_for_mvp.md) — §1 (orders REST endpoints), §4 (trade fills in history)
- [`tests_overview.md`](tests_overview.md) — test coverage map; `TradingEngine` has no dedicated tests yet

