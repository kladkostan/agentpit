# 03 — Typed Pydantic response models for opaque endpoints

**Status**: required for `agentpit-trader` v1
**Effort**: ~30 min (depending on how response shapes have evolved internally)
**Breaking**: No (declarative-only — response *content* doesn't change, only the OpenAPI schema reflects what's actually returned)
**Driver**: [agentpit-trader design spec](../../../TradingAgents/docs/superpowers/specs/2026-05-27-agentpit-trader-design.md) §6 (compatibility verification), §10 (failure modes)

## Why this is needed

The `agentpit-trader` MCP server runs a **startup compatibility probe**: on boot it fetches AgentPit's `/openapi.json` and verifies that every endpoint the trader needs exists with the expected response schema. If a schema is missing or differs, the server refuses to start with a clear error — preventing autonomous trading from running against an incompatible AgentPit version.

This probe relies on AgentPit's OpenAPI being **authoritative**. Currently four critical endpoints declare opaque response schemas (`additionalProperties: true` rather than typed Pydantic models). The probe can't verify shape against an opaque schema, and any client (including `openapi-typescript` codegen) must reverse-engineer the response by inspection. That's fragile and error-prone.

The endpoints are critical: they're the orderbook, the user's open orders, sparkline data, and order-cancel response. The trader bot calls all of them.

## Current state

The four endpoints currently declared with opaque schemas:

```yaml
GET /orders/mine:
  responses:
    200:
      content:
        application/json:
          schema:
            type: object
            additionalProperties: true   # ← no shape

DELETE /orders/{order_id}:
  responses:
    200:
      content:
        application/json:
          schema:
            type: object
            additionalProperties: true   # ← no shape

GET /orderbook/{market_id}/{outcome}:
  responses:
    200:
      content:
        application/json:
          schema:
            type: object
            additionalProperties: true   # ← no shape

GET /sparkline/{market_id}/{outcome}:
  responses:
    200:
      content:
        application/json:
          schema:
            type: object
            additionalProperties: true   # ← no shape
```

The handlers presumably already return consistently-shaped dicts. They just don't declare those shapes to FastAPI.

## What needs to be implemented (MVP)

**Declare Pydantic response models** for each of the four endpoints and wire them via FastAPI's `response_model=` parameter. The handlers themselves don't change.

### 1. `GET /orders/mine` → `MyOrdersResponse`

```python
class MyOrder(BaseModel):
    order_id: str
    market_id: int
    outcome: str                        # label, e.g. "Yes"
    outcome_index: int                  # 0-based
    token_id: str
    side: Literal["BUY", "SELL"]
    price: str                          # decimal as string for precision
    size: int                           # original size
    filled_size: int
    remaining_size: int
    order_type: Literal["GTC", "FOK", "FAK", "GTD"]
    status: Literal["open", "filled", "partially_filled", "cancelled", "rejected"]
    placed_at: str                      # ISO8601
    expiration: int                     # 0 if no expiration

class MyOrdersResponse(BaseModel):
    eth_address: str
    orders: list[MyOrder]
```

Handler change:
```python
@router.get("/orders/mine", response_model=MyOrdersResponse)
def list_my_orders(...): ...
```

### 2. `DELETE /orders/{order_id}` → `CancelOrderResponse`

```python
class CancelOrderResponse(BaseModel):
    success: bool
    order_id: str
    status: Literal["cancelled", "already_filled", "already_cancelled", "not_found"]
    cancelled_size: int                 # 0 if status != "cancelled"
    message: str | None = None          # optional human-readable detail
```

### 3. `GET /orderbook/{market_id}/{outcome}` → `OrderbookResponse`

```python
class OrderbookLevel(BaseModel):
    price: str                          # decimal as string
    size: int

class OrderbookResponse(BaseModel):
    market_id: int
    outcome: str
    outcome_index: int
    token_id: str
    bids: list[OrderbookLevel]          # sorted highest-price first
    asks: list[OrderbookLevel]          # sorted lowest-price first
    mid_price: str | None               # null if book is empty on one side
    spread: str | None                  # null if book is empty on one side
    as_of: str                          # ISO8601
```

### 4. `GET /sparkline/{market_id}/{outcome}` → `SparklineResponse`

```python
class SparklinePoint(BaseModel):
    timestamp: str                      # ISO8601
    price: str                          # decimal as string
    volume: int                         # USDC volume in the bucket

class SparklineResponse(BaseModel):
    market_id: int
    outcome: str
    outcome_index: int
    token_id: str
    window_hours: int
    samples: list[SparklinePoint]
    summary: dict[str, str | None]      # { "open", "high", "low", "close", "vwap" } — each decimal-as-string or null
```

### Implementation guidance

For each endpoint:

1. **Read the handler** to confirm the current actual response shape.
2. **Adjust the proposed model above** if the handler differs (or adjust the handler to match — your call which side adapts).
3. **Wire `response_model=`** on the route decorator.
4. **Verify `/openapi.json`** now exposes a `$ref` to the new schema instead of `additionalProperties: true`.

If the handler currently returns slightly different fields (e.g. different naming conventions, extra fields), pick one of:

- **Adapt the handler** to match the schema above (cleanest)
- **Adapt the schema above** to match the handler (fastest)

The exact field set matters less than having a consistent typed contract. The `agentpit-trader` MCP server will adapt to whatever AgentPit declares — as long as it's declared.

## Acceptance criteria

1. `/openapi.json` declares typed Pydantic models for all four endpoints (no `additionalProperties: true`).
2. Each endpoint's response at runtime matches the declared schema (FastAPI validates outgoing responses when `response_model=` is set; mismatches raise 500 in dev).
3. Generated TypeScript types from `npx openapi-typescript http://localhost:8000/openapi.json` produce strongly-typed interfaces for all four endpoints.
4. No existing client of these endpoints is broken (field renames are avoided unless the rename clearly improves clarity — and we don't *have* to rename anything).

## Out of scope (for this feature)

- Adding new fields to the responses — only declaring what's already returned
- Changing endpoint paths or methods
- Pagination on `/orders/mine` or `/sparkline` — not needed at v1 scale
- Filtering query params (e.g. `?status=open` on `/orders/mine`) — client-side filter is fine

## References

- Parent spec §6 (compatibility verification subsection)
- FastAPI `response_model` docs: <https://fastapi.tiangolo.com/tutorial/response-model/>
- Endpoint handlers (current locations):
  - `agentpit/api/orders.py` (likely) for `/orders/mine` and `DELETE /orders/{id}`
  - `agentpit/api/orderbook.py` or `agentpit/api/orders.py` for `/orderbook/{market_id}/{outcome}`
  - `agentpit/api/sparkline.py` or similar for `/sparkline/{market_id}/{outcome}`
- See [01-trade-fill-transactions.md](01-trade-fill-transactions.md) for related changes affecting `/orders/mine`'s `filled_size` / `remaining_size` semantics (they must be consistent with the sum of `TRADE_FILL` rows for the order)
