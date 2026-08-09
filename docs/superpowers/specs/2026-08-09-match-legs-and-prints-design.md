# Match legs and price prints — design

**Status:** approved 2026-08-09
**Follow-up to:** `docs/superpowers/plans/2026-08-07-mint-merge-position-accounting.md` (shipped, verified on production)

## Problem

`trades.PRICE` is **always the maker's price**, and `trades.ASSET_ID` is **always
the taker's token**. For the two special match kinds those are not the whole
truth:

- **MINT** (taker BUY vs maker BUY) — a complementary pair is minted for $1. The
  taker acquires `ASSET_ID` at `1 − p`; the maker acquires the market's *other*
  outcome at `p`.
- **MERGE** (taker SELL vs maker SELL) — a pair is burned for $1. Both sides
  dispose, of different tokens, at complementary prices.

The position layer was fixed and deployed: `AccountService._token_flow` now
attributes each leg to the token that party actually moved, `trades.MAKER_ASSET_ID`
and `trades.MATCH_KIND` exist, and all 401,848 production rows are labelled
(401,535 NORMAL, 285 MINT, 28 MERGE).

Seven read paths were left untouched. They still assume one row means one token
at one price, so the money is now right while the *narration* of it is wrong.

### Measured on production, 2026-08-09

| account | MINT | MERGE | rows where they are the maker |
| --- | --- | --- | --- |
| RichChilliPine | 278 | 28 | 233 |
| FreshTulip | 5 | 0 | 2 |
| FairRobin | 2 | 0 | 1 |
| FineOrchid | 0 | 0 | 0 |

313 rows of 458k, across 10 markets. Three tokens have a MINT/MERGE as their
latest trade; exactly one of those has no live book, so `_cur_price` currently
misprices one token — the mirror's book midpoint rescues the rest. The damage is
concentrated in the Activity feed (236 maker rows) and in the price tape, where
no midpoint intervenes.

## The core distinction

Everything here follows from separating two concepts that the current code
conflates.

### A. A price print — "this token traded at this price"

Consumed by the chart, `last_trade_price`, and every market card.

| kind | print on `ASSET_ID` | print on `MAKER_ASSET_ID` |
| --- | --- | --- |
| NORMAL | price `p`, side `SIDE` | *same token — exactly one print* |
| MINT | price `MICRO − p`, side BUY | price `p`, side BUY |
| MERGE | price `MICRO − p`, side SELL | price `p`, side SELL |

**A NORMAL match must yield exactly one print.** The maker trades the same token
at the same price; emitting both legs would double every chart point and every
volume figure derived from the tape. This is the single easiest way to break
this change, and it fails silently.

A MINT/MERGE yields two prints, on different tokens, whose prices sum to `MICRO`
(1,000,000). The complement token currently gets no print at all — that gap is
why its chart and its `last_trade_price` are misleading.

### B. A user leg — "what did *this* account do"

Consumed by the Activity feed and `/data/trades`.

| kind | the taker's leg | the maker's leg |
| --- | --- | --- |
| NORMAL | `ASSET_ID`, side `SIDE`, price `p` | `ASSET_ID`, opposite of `SIDE`, price `p` |
| MINT | `ASSET_ID`, BUY, price `MICRO − p` | `MAKER_ASSET_ID`, BUY, price `p` |
| MERGE | `ASSET_ID`, SELL, price `MICRO − p` | `MAKER_ASSET_ID`, SELL, price `p` |

Here a NORMAL match yields **two** entries — the buyer sees a buy, the seller
sees a sell. Same event, two perspectives. This is the exact inverse of A's
collapsing rule, which is why one shared helper for both would be a mistake.

One account can hold both legs of a row: the matcher has no same-account guard,
and on production 373,221 of 458,000 rows are self-matched (the liquidity
mirror). A per-user view must handle a row where the caller is both parties.

**Table B is already implemented** — it is the truth table inside `_token_flow`.
This design does not rewrite it; it extracts it so positions, Activity and the
trades API read one definition. `trade_service.py:46-56` already has half of it
(a TAKER/MAKER "perspective" that correctly flips `side` and `outcome`) and then
emits the taker's `asset_id` regardless — the file contradicts itself today.

## Components

**`agentpit/datastructures/match_leg.py`** (new) — table B as pure functions over
a trade row plus an api_key. No DB access, no I/O. Returns the token, the side
and the price for a given leg. `_token_flow`, `list_activity` and `TradeService`
all consume it.

**A prints SQL fragment in `agentpit/db/table_read.py`** — table A. The tape
readers are batched and use `DISTINCT ON`, so this has to be SQL, not Python.
A single module-level constant, embedded by every tape reader, so the rule
appears once.

The two representations encode the same domain in two languages, which is a
drift hazard. It is closed by a test, not by discipline — see Testing.

## Call sites

**Tape (A) — five:**

| site | user-visible effect |
| --- | --- |
| `order_service.py:547-552` | `/prices-history` — the chart |
| `order_service.py:470` | `last_trade_price` inside the book |
| `order_service.py:596-604` | `get_last_trade_price` |
| `table_read.py:984-996` → `polymarket/pricing.py:101` | the price on every market card |
| `account_service.py:517-522` | `_cur_price`, the no-book fallback |

**User leg (B) — two:**

`account_service.py:433-459` (`list_activity`) — token, side and price come from
`match_leg`; `outcome` and `outcomeIndex` follow the corrected token. `usdcSize`
is `price × size` and therefore also changes for these rows: it is wrong today.

`table_read.py:1139-1150` + `services/trade_service.py:46-77` — the `asset_id`
filter must match **either** leg, so `/data/trades?asset_id=` stops silently
dropping the caller's own MINT/MERGE maker fills. In the response, `asset_id`
follows the perspective and the taker's price flips on MINT/MERGE. `price` for
the maker perspective is already correct (`PRICE` *is* the maker's price) and
must not be flipped twice.

**Plus:** `_token_flow` starts reading `match_leg` instead of carrying its own
copy of the rule.

## Indexes

`trades` has no index on `ASSET_ID`. Measured on production today:

```
EXPLAIN ANALYZE SELECT MATCH_TIME, PRICE FROM trades
WHERE ASSET_ID = ... AND STATUS <> 'FAILED' ORDER BY MATCH_TIME ASC

Parallel Seq Scan on trades   (rows=21, Rows Removed by Filter: 153166)
Buffers: shared read=36859    Execution Time: 132 ms
```

132 ms and a full scan of 458k rows to return 21 chart points, on every chart
load. This change adds a second lookup by `MAKER_ASSET_ID`, which without
indexes doubles it. Two indexes are therefore part of the change, not polish:
`trades(ASSET_ID)` and `trades(MAKER_ASSET_ID)`.

Both must be created as idempotent DDL in `create_trades_table`, alongside the
existing `idx_trades_unlabelled`. Note the constraint established by the
previous branch: DDL at startup is fine, **data migrations are not** — see
`scripts/backfill_trade_match_kind.py`. This change needs no data migration at
all; both tables are derived at read time from columns that are already
populated on production.

## Testing

Three invariants, which catch the ways this actually breaks. They matter more
than per-site assertions.

1. **The two representations agree.** For the same trade row, the SQL prints
   fragment and the Python truth table produce the same token, side and price.
   Without this they drift, and they drift silently.
2. **NORMAL yields exactly one print.** Guards the double-counting trap in §A.
3. **A MINT's two prints sum to `MICRO`.** The economic invariant: a minted pair
   costs exactly $1.

Alongside these, per-site tests: a maker's MINT renders in Activity as a BUY of
the complement at the maker's price; `/data/trades?asset_id=<complement>`
returns the caller's maker fill; the complement token's `/prices-history` gains
the print it never had.

Backend suite: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
(never source `.env` — `tests/conftest.py` relies on `os.environ.setdefault`).
The local chain must be up, since `conftest` imports the app.

## Out of scope

- Any change to the matcher, to how MINT/MERGE are decided, or to what is
  written at match time. This is a read-path change only.
- The leaderboard, positions and cost basis — fixed and verified in the previous
  branch.
- A new Activity event type. Decided: a maker's MINT renders as an ordinary
  TRADE with the correct token, direction and price. No UI change, no new
  variant in `ActivityWire`, no divergence from the Polymarket API shape.
- The mirror's re-quoting behaviour after a user walks the book. It restores the
  upstream price on the next reconcile, which is correct for a mirror; whether
  an infinitely regenerating top-of-book is the right product is a separate
  question.
