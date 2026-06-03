# Missing features for `agentpit-trader` v1

This directory enumerates the **minimum AgentPit additions** required before the [`agentpit-trader`](../../../TradingAgents/docs/superpowers/specs/2026-05-27-agentpit-trader-design.md) OpenClaw plugin can run in sandbox mode.

The trader bundle uses Polymarket Gamma + CLOB as its **analytical data source** in both sandbox and live modes. AgentPit's role in sandbox is purely as the **execution venue** — place orders, cancel orders, read your own portfolio + fills. This dramatically reduces what AgentPit must expose.

## What's needed

| # | Feature | Driver | Estimated effort | Breaking? |
|---|---|---|---|---|
| [01](01-trade-fill-transactions.md) | `TRADE_FILL` transaction type for executed order fills | Bot can't reconcile partial fills without a history of executed trades | ~30 min | No (additive) |
| [02](02-market-query-filters.md) | Query filters on `GET /markets` (`polymarket_condition_id`, `polymarket_id`, `market_state`) | Bot needs O(1) lookup from Polymarket condition_id → agentpit market_id | ~10 min | No (additive) |
| [03](03-typed-response-models.md) | Pydantic response models for currently-opaque endpoints | MCP server's startup probe needs typed schemas to validate compatibility | ~30 min | No (declarative only) |
| [04](04-place-order-outcome-format.md) | Document and validate `PlaceOrderRequest.outcome` format | Bot needs a reliable contract for whether outcome is a label or token_id | ~5 min | No (documentation + light validation) |

**Total estimated effort: ~1.5 hours.** All four are non-breaking additive changes.

## What's explicitly out of scope (deferred / parallel work)

- **Full Polymarket CLOB protocol compatibility** — making `ClobClient(host="https://api.agentpit.ai")` transparently work with `@polymarket/clob-client-v2` is a separate multi-week project. See parent design spec §13 for context. The features here only cover what `agentpit-trader` needs *now* via its own thin sandbox adapter.
- **Bulk cancel endpoints** (cancel-multiple, cancel-all, cancel-for-market). Trader places orders one at a time in v1.
- **WebSocket streams** for orderbook / fills. 30-minute cadence doesn't require sub-minute data.
- **`GET /orders/{id}` single-order lookup**. `GET /orders/mine` covers this. Add only if reconciliation becomes painful.

## How these were identified

These gaps came from an OpenAPI gap audit of the agentpit `/openapi.json` (as of 2026-05-27) against the `agentpit-trader` MCP server tool surface. Documented in the parent spec §12.

## Sequencing recommendation

Do them in numeric order. Each is independent, but #01 (TRADE_FILL) is the largest and most behavior-critical; the rest are quick once #01 is in.
