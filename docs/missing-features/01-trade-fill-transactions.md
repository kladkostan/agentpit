# 01 — `TRADE_FILL` transaction type for executed order fills

**Status**: required for `agentpit-trader` v1
**Effort**: ~30 min
**Breaking**: No (additive — new value added to existing `transaction_type` enum-like field, new event type emitted by OrderService)
**Driver**: [agentpit-trader design spec](../../../TradingAgents/docs/superpowers/specs/2026-05-27-agentpit-trader-design.md) §6 (sandbox adapter), §10 (reconciliation)

## Why this is needed

The `agentpit-trader` bot places orders autonomously and must reconcile execution state against its own audit log every cycle. Reconciliation requires the bot to know:

- **Did my order fill?**
- **At what price did it fill?**
- **What size filled, and what's still resting?**
- **When did the fill happen?**

Currently `GET /transactions` returns `Transaction` rows whose `transaction_type` covers `SPLIT`, `MERGE`, and `REDEEM` — the conditional-token-framework position primitives. **It does not include order fills.** Without a fill history, the bot only sees current order state (`open`, `filled`, `cancelled`) from `GET /orders/mine` but not the *price and size of each fill event* — which is what P&L tracking, slippage analysis, and audit trails depend on.

Polymarket's equivalent (`getTrades({maker_address})` in `@polymarket/clob-client-v2`) returns this per-fill history. We need a parallel concept on AgentPit.

## Current state

- `GET /transactions` returns `TransactionHistoryResponse` with rows shaped:
  ```json
  {
    "transaction_id": 42,
    "timestamp": "2026-05-27 10:00:00",
    "transaction_type": "SPLIT" | "MERGE" | "REDEEM",
    "market_id": 1,
    "details": { ... type-specific ... }
  }
  ```
- When an order placed via `POST /orders` fills (fully or partially), no transaction row is written for the fill event.
- The OrderService updates the order's `filled_size` / `remaining_size` internally, but there's no per-fill event log.

## What needs to be implemented (MVP)

**Emit a `TRADE_FILL` transaction row each time an order match results in a fill.**

### Schema additions

Add `"TRADE_FILL"` as a valid value of the existing `transaction_type` field. The `details` payload for a TRADE_FILL row:

```json
{
  "transaction_id": 1042,
  "timestamp": "2026-05-27T11:34:18Z",
  "transaction_type": "TRADE_FILL",
  "market_id": 1,
  "details": {
    "order_id": "ord-abc123",
    "counterparty_order_id": "ord-xyz789",
    "outcome": "Yes",
    "outcome_index": 0,
    "token_id": "0xaaa...",
    "side": "BUY",
    "price": "0.36",
    "size": 30,
    "fee": 0,
    "is_taker": true,
    "tx_hash": "0x..."
  }
}
```

Field semantics:

| Field | Type | Meaning |
|---|---|---|
| `order_id` | string | The user's own order ID that this fill belongs to |
| `counterparty_order_id` | string | Optional — the matched-against order; useful for forensics |
| `outcome` | string | Outcome label (matches `Market.erc1155_tokens[i][1]`) |
| `outcome_index` | integer | 0-based index into `Market.erc1155_tokens` |
| `token_id` | string | ERC-1155 token ID of the outcome |
| `side` | `"BUY"` \| `"SELL"` | Direction from the user's perspective |
| `price` | string (decimal) | Execution price in USDC per share |
| `size` | integer | Fill quantity in outcome tokens |
| `fee` | integer | USDC fee charged (0 in v1 if no fees) |
| `is_taker` | boolean | True if this fill consumed liquidity; false if provided |
| `tx_hash` | string (optional) | On-chain settlement transaction hash if available |

### Where to emit

In `agentpit/services/order_service.py`, wherever `OrderService` records a successful match between two orders (the matching loop). Each match produces **two** `TRADE_FILL` rows — one for each side of the trade — written via the same transaction-writing path used by SPLIT/MERGE/REDEEM.

### API change

No new endpoints. `GET /transactions` returns the new rows alongside existing ones.

If desired (nice-to-have, not MVP), `GET /transactions` could gain optional query filters to avoid clients re-filtering client-side:

```
GET /transactions?type=TRADE_FILL&market_id=1&since=2026-05-27T00:00:00Z&limit=100
```

The MVP doesn't strictly require these filters — the bot can page and filter client-side at small volumes — but they'd be a free improvement if you're already touching the endpoint.

## Acceptance criteria

1. After a successful `POST /orders` that crosses an existing order, **two** new `TRADE_FILL` rows appear in `GET /transactions` (one per side), each with the full `details` payload shape above.
2. Partial fills emit one `TRADE_FILL` row per partial match, with `size` reflecting the *partial* quantity matched in that match (not cumulative).
3. The `transaction_type` field in the response is the literal string `"TRADE_FILL"`.
4. `OrderResponse` returned by `POST /orders` already includes `filledSize`, `remainingSize`, `avgPrice` — these continue to work and remain consistent with the sum of `TRADE_FILL` rows for that `order_id`.
5. The OpenAPI schema for `Transaction.transaction_type` is updated (if it's enum-typed) to include `"TRADE_FILL"`.
6. Existing `SPLIT`/`MERGE`/`REDEEM` rows continue to work unchanged.
7. Idempotency: re-running tests that produce the same fills doesn't double-emit. Each on-chain match generates exactly one pair of `TRADE_FILL` rows.

## Out of scope (for this feature)

- Bulk fill reporting endpoints (`GET /fills?since=...`) — covered by transactions endpoint
- WebSocket fill push — sub-second event delivery isn't needed at 30-min trader cadence
- Slippage / VWAP analytics — derivable client-side from the per-fill log
- Fees field for non-zero fees — set to 0 in v1; structurally present for future use

## References

- Existing transaction emit path: `agentpit/services/order_service.py` (look at where SPLIT/MERGE/REDEEM rows are inserted)
- Existing `Transaction` schema: [`docs/agentpit_api.md`](../agentpit_api.md#portfolio--history) — update to include `TRADE_FILL`
- Parent spec §6 (sandbox adapter), §10 (reconciliation flow)
- Polymarket equivalent: `getTrades({maker_address})` from `@polymarket/clob-client-v2`
