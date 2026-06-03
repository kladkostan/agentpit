# 02 — Query filters on `GET /markets`

**Status**: required for `agentpit-trader` v1 (workaround exists, but feature is a clear quality-of-life win)
**Effort**: ~10 min
**Breaking**: No (additive query parameters; existing callers unaffected)
**Driver**: [agentpit-trader design spec](../../../TradingAgents/docs/superpowers/specs/2026-05-27-agentpit-trader-design.md) §6 (identifier bridging)

## Why this is needed

The `agentpit-trader` bot identifies markets using **Polymarket's `condition_id`** (bytes32 hex) — that's what Polymarket Gamma + CLOB return as the canonical market identifier. To place an order on AgentPit, the bot needs AgentPit's **integer `market_id`** (the SQLite primary key). It needs a fast lookup from one to the other.

Currently `GET /markets` exposes only `limit` and `offset`. To find the AgentPit market for `condition_id=0xabc...`, the bot must either:

1. Page through every market on every cycle (wasteful, fragile)
2. Cache a `{polymarket_condition_id → market_id}` map locally and refresh periodically (works but adds startup latency and drift risk)

The Pydantic `Market` schema **already stores** the Polymarket identifiers — `polymarket_condition_id`, `polymarket_id`, `polymarket_yes_token_id`, `polymarket_no_token_id`. We just need query filters that expose them through the existing endpoint.

## Current state

```python
@router.get("/markets", response_model=ListMarketsResponse)
def list_markets(limit: int = 100, offset: int = 0):
    ...
```

Returns paginated markets, no filtering.

## What needs to be implemented (MVP)

**Add three optional query parameters to the existing `GET /markets` endpoint.** None of them is required; all return all markets if omitted (preserving current behavior).

### New parameters

| Parameter | Type | Effect |
|---|---|---|
| `polymarket_condition_id` | string \| null | Exact-match filter against `Market.polymarket_condition_id` |
| `polymarket_id` | integer \| null | Exact-match filter against `Market.polymarket_id` |
| `market_state` | `MarketState` enum \| null | Filter to a single state (`DRAFT` / `ACTIVE` / `CLOSED` / `RESOLVED` / `CANCELLED`) |

### Suggested FastAPI implementation

```python
@router.get("/markets", response_model=ListMarketsResponse)
def list_markets(
    limit: int = 100,
    offset: int = 0,
    polymarket_condition_id: str | None = None,
    polymarket_id: int | None = None,
    market_state: MarketState | None = None,
):
    query = db.session.query(MarketModel)
    if polymarket_condition_id is not None:
        query = query.filter(MarketModel.polymarket_condition_id == polymarket_condition_id)
    if polymarket_id is not None:
        query = query.filter(MarketModel.polymarket_id == polymarket_id)
    if market_state is not None:
        query = query.filter(MarketModel.market_state == market_state)
    total = query.count()
    markets = query.offset(offset).limit(limit).all()
    return ListMarketsResponse(markets=markets, total=total, limit=limit, offset=offset)
```

(Exact ORM idiom depends on agentpit's current data-access pattern.)

### Behavioral notes

- All three filters are **AND-combined** when multiple are provided.
- `polymarket_condition_id` lookups are expected to return at most one row (unique upstream identifier), but the response shape remains `ListMarketsResponse` for consistency. Callers handle `markets: []` and `markets: [single]` uniformly.
- Filters apply to the `total` count, not just the returned page (total = matching markets, not total markets in DB).
- Invalid `market_state` values return a `422 Validation Error` from FastAPI's automatic enum parsing.

## Acceptance criteria

1. `GET /markets?polymarket_condition_id=0xabc...` returns a `ListMarketsResponse` containing only the market(s) with that exact `polymarket_condition_id`, or `markets: []` and `total: 0` if no match.
2. `GET /markets?polymarket_id=12345` returns markets with that `polymarket_id`.
3. `GET /markets?market_state=ACTIVE` returns only `ACTIVE` markets; `total` reflects only `ACTIVE` count.
4. `GET /markets?market_state=ACTIVE&polymarket_condition_id=0xabc...` AND-combines both filters.
5. `GET /markets` with no filters behaves exactly as today (no regression).
6. OpenAPI spec at `/openapi.json` reflects the new query parameters.
7. Pagination (`limit`, `offset`) continues to work with filters; the page is over the filtered set.

## Out of scope (for this feature)

- Search/fuzzy matching (only exact matches needed)
- Multi-value filters (e.g. `market_state=ACTIVE,CLOSED`) — single value per filter for MVP
- Filtering by event, tag, category, date range — none of these are needed by `agentpit-trader` v1
- Keyset pagination — offset pagination is fine at expected scale (~1k markets)
- A separate `/markets/by-condition-id/{condition_id}` endpoint — the query filter approach reuses existing infrastructure

## References

- Parent spec §6 (sandbox adapter), §8 (cycle flow Phase 0)
- Existing endpoint: `agentpit/api/markets.py` (or wherever `GET /markets` is currently defined)
- `Market` schema fields available for filtering: `polymarket_id`, `polymarket_condition_id`, `polymarket_yes_token_id`, `polymarket_no_token_id`, `market_state`
- Polymarket Gamma uses `conditionId` (camelCase) as the canonical market identifier — `polymarket_condition_id` (snake_case) is the corresponding field in agentpit's `Market`
