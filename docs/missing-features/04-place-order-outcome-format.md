# 04 — Document and validate `PlaceOrderRequest.outcome` format

**Status**: required for `agentpit-trader` v1
**Effort**: ~5 min (mostly documentation + a small validator)
**Breaking**: No (clarification + tightening — invalid inputs that succeed today by accident may start returning 422, but that's a bug fix)
**Driver**: [agentpit-trader design spec](../../../TradingAgents/docs/superpowers/specs/2026-05-27-agentpit-trader-design.md) §6 (sandbox adapter)

## Why this is needed

`PlaceOrderRequest` declares `outcome: str, minLength: 1`. The schema doesn't specify whether the bot should pass:

- The outcome **label** (e.g. `"Yes"` or `"No"`), or
- The outcome **token_id** (e.g. `"0xaaa..."`), or
- The outcome **index** (e.g. `"0"`), or
- Some other identifier

The `Market` schema has `erc1155_tokens: [[token_id, label], ...]` with both — so either interpretation is plausible. The `agentpit-trader` MCP server needs a reliable contract; it can't guess per call.

Without an explicit contract, the bot will either:

- Guess label (most user-friendly), and break if the handler expects token_id
- Guess token_id, and break if the handler expects label
- Have to hardcode behavior per agentpit version

This is the **smallest** of the four missing features but a real reliability issue.

## Current state

```python
class PlaceOrderRequest(BaseModel):
    market_id: int
    outcome: str = Field(..., min_length=1)
    side: Literal["BUY", "SELL"]
    price: float | str
    size: int
    order_type: Literal["GTC", "FOK", "FAK", "GTD"] = "GTC"
    expiration: int = 0
```

The handler accepts `outcome` and presumably matches against `Market.erc1155_tokens`, but neither the schema nor `docs/agentpit_api.md` documents the format expected.

## What needs to be implemented (MVP)

Pick **one** canonical interpretation, document it, and validate it.

### Recommended: outcome = **label** (matches `Market.erc1155_tokens[i][1]`)

Rationale:

- Labels are human-readable (`"Yes"` / `"No"`), making API calls inspectable and debuggable in logs.
- Token IDs are also reachable for callers who need them (via `Market.erc1155_tokens`), so requiring label doesn't lose information.
- Polymarket's own UX exposes outcomes by name in many places.
- Existing handler behavior is most likely label-based (worth verifying).

### Schema + handler changes

```python
class PlaceOrderRequest(BaseModel):
    market_id: int = Field(..., ge=0)
    outcome: str = Field(
        ...,
        min_length=1,
        description=(
            "Outcome label as it appears in the market's erc1155_tokens entry "
            "(e.g. 'Yes' or 'No'). Must exactly match Market.erc1155_tokens[i][1]. "
            "Case-sensitive."
        ),
    )
    side: Literal["BUY", "SELL"]
    price: float | str
    size: int = Field(..., gt=0)
    order_type: Literal["GTC", "FOK", "FAK", "GTD"] = "GTC"
    expiration: int = 0
```

### Handler validation

In `agentpit/api/orders.py` (or wherever `POST /orders` is handled), after loading the `Market`:

```python
labels = [label for _token_id, label in market.erc1155_tokens]
if request.outcome not in labels:
    raise HTTPException(
        status_code=422,
        detail=(
            f"outcome '{request.outcome}' is not a valid outcome for market "
            f"{request.market_id}. Valid outcomes: {labels}"
        ),
    )
```

### Documentation update

In [`docs/agentpit_api.md`](../agentpit_api.md), under the orders section, add:

> **`outcome` field**: Pass the outcome label as it appears in
> `Market.erc1155_tokens[i][1]` (e.g. `"Yes"` or `"No"`). Case-sensitive.
> Exact match required.

## Acceptance criteria

1. The OpenAPI schema for `PlaceOrderRequest.outcome` includes a `description` field clearly stating: outcome label, must match `Market.erc1155_tokens[i][1]`, case-sensitive.
2. `POST /orders` with `outcome: "Yes"` (matching) → succeeds (or fails for other reasons — insufficient balance, etc., but not for outcome format).
3. `POST /orders` with `outcome: "yes"` (case mismatch) → returns `422` with a clear error message listing valid labels.
4. `POST /orders` with `outcome: "0xaaa..."` (token_id mistakenly passed as label) → returns `422` with a clear error.
5. `POST /orders` with `outcome: ""` → returns `422` (already enforced by `min_length=1`).
6. The existing happy-path behavior is unchanged for callers who were already passing the correct label.
7. `docs/agentpit_api.md` documents the `outcome` field format in the orders section.

## Out of scope (for this feature)

- Accepting **both** label and token_id as `outcome` and disambiguating — clearer to pick one
- Case-insensitive matching — explicit case-sensitivity is safer; "Yes" and "yes" being different is fine
- Auto-translating `outcome` to `outcome_index` for storage — internal storage representation is not the contract's concern
- Token-id-only API path (e.g. `/orders` with `outcome_token_id` field) — wait until a real need surfaces

## References

- Parent spec §6 (sandbox adapter — depends on this contract being clear)
- Current `PlaceOrderRequest` schema (in agentpit's OpenAPI dump)
- `Market.erc1155_tokens` schema: `[[token_id_string, label_string], ...]`
- Handler location: `agentpit/api/orders.py` (look for `POST /orders` route)
- Related: [03-typed-response-models.md](03-typed-response-models.md) — the `MyOrder` response model in that doc also uses `outcome: str` as the label, consistent with this decision
