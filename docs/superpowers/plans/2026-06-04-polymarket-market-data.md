# Phase 3 — Market Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate agentpit's market-data reads to Polymarket's exact CLOB interface — `GET /book` (+`POST /books`), `GET /prices-history` (was `/sparkline`), `GET /midpoint`, `GET /price`, `GET /last-trade-price` — all keyed by `token_id` and emitting Polymarket's decimal-string/float shapes, then rework the order-book + chart UI in lockstep.

**Architecture:** New read-only endpoints live in a dedicated `agentpit/api/routes/market_data.py` router (they're CLOB reads, distinct from order CRUD in `orders.py`), backed by new methods on `OrderService` (which already owns the `orders`/`trades` tables). The book is aggregated server-side (`GROUP BY PRICE`, sum `REMAINING_AMOUNT`) and resolved from `token_id` via `resolve_by_token_id`. The old `GET /orderbook/{market_id}/{outcome}` and `GET /sparkline/{market_id}/{outcome}` (+ their service methods) are removed. The UI's order-book pipeline — which today threads micro-int `PRICE`/`REMAINING_AMOUNT` through `orderMath.ts` → `useYesMid` → `Orderbook`/cards — is reworked to consume decimal-string price levels keyed by `token_id`.

**Tech Stack:** FastAPI, Pydantic v2, raw `sqlite3`, pytest + `TestClient` (+ live-chain `tests/onchain/`), React + TS + React Query + vitest UI.

**Spec:** `docs/superpowers/specs/2026-06-03-agentpit-polymarket-api-migration-design.md` §8.5–8.7, §9.

**Representation (§4):** CLOB book prices/sizes are **decimal strings** (`"0.45"`, `"120"`). prices-history uses **JSON floats** + **int-seconds** `t`. Internally agentpit scales by 10⁶. Converters in `agentpit.polymarket.format`: `price_to_decimal_str`, `size_to_decimal_str`, `price_to_float`. `_PRICE_ONE = 10**6`.

**Exception→HTTP:** `NotFoundError`→404, `BusinessRuleError`→400. For "no book/last-trade", raise `NotFoundError` (→404), matching Polymarket's `/midpoint` 404-on-no-book.

**Current code being replaced** (`agentpit/services/order_service.py`): `get_orderbook(market_id, outcome)` returns `{market_id, outcome, bids, asks}` with raw order-row dicts; `get_sparkline(market_id, outcome, window_hours)` returns `{..., points:[{t, p:int}], volume_micro_usd, volume_total_micro_usd}`. Both call `_resolve_market_lookup` (which stays — still used internally). Routes in `agentpit/api/routes/orders.py`.

---

## File Structure

**Create:**
- `agentpit/datastructures/orderbook_summary.py` — `OrderBookLevel`, `OrderBookSummary`.
- `agentpit/datastructures/book_params.py` — `BookParams` (`POST /books` request element).
- `agentpit/api/routes/market_data.py` — the 6 read endpoints.
- `tests/onchain/test_book.py`, `tests/onchain/test_market_data.py` — live-chain (need resting orders/trades).
- `tests/api/test_prices_history.py` — empty/no-trade path (no chain needed).

**Modify:**
- `agentpit/services/order_service.py` — add `get_book`/`get_books`/`get_prices_history`/`get_midpoint`/`get_price`/`get_last_trade_price`; remove `get_orderbook`/`get_sparkline`.
- `agentpit/api/routes/orders.py` — remove `GET /orderbook/...` + `GET /sparkline/...`.
- `agentpit/api/app.py` — register the `market_data` router.
- UI: `ui/src/types/order.ts` (`OrderbookEntry`→levels), `ui/src/types/market.ts` (`SparklinePoint`/`SparklineResponse`), `ui/src/api/orders.ts` (`getBook`), `ui/src/api/markets.ts` (`getPricesHistory`), `ui/src/components/orders/orderMath.ts`, `ui/src/lib/useYesMid.ts`, `ui/src/lib/useYesMidMap.test.ts`, `ui/src/components/orders/Orderbook.tsx`, `ui/src/components/{MarketCard,MultiMarketEventCard,EventLeaderboardRow,EventChart}.tsx`, `ui/src/components/orders/OrderTicket.tsx`.

**Delete:** `agentpit/datastructures/orderbook_response.py` (already dead — unused).

**Do NOT touch:** `agentpit_bots/`, `tests/bots/`, `scripts/seed_market_orders.py` (Phase 5).

---

## Task 1: Market-data datastructures

**Files:**
- Create: `agentpit/datastructures/orderbook_summary.py`, `agentpit/datastructures/book_params.py`
- Delete: `agentpit/datastructures/orderbook_response.py`
- Test: `tests/test_orderbook_summary.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_orderbook_summary.py`:
```python
from agentpit.datastructures.book_params import BookParams
from agentpit.datastructures.orderbook_summary import OrderBookLevel, OrderBookSummary


def test_level_fields():
    lvl = OrderBookLevel(price="0.45", size="120")
    assert lvl.model_dump() == {"price": "0.45", "size": "120"}


def test_summary_defaults_and_shape():
    s = OrderBookSummary(
        market="0xcond",
        asset_id="123",
        timestamp="1740000000000",
        hash="abc",
        bids=[OrderBookLevel(price="0.45", size="120")],
        asks=[OrderBookLevel(price="0.55", size="90")],
        last_trade_price="0.46",
    )
    d = s.model_dump()
    assert d["market"] == "0xcond" and d["asset_id"] == "123"
    assert d["tick_size"] == "0.001"
    assert d["neg_risk"] is False
    assert d["min_order_size"] == "0"
    assert d["bids"][0] == {"price": "0.45", "size": "120"}


def test_book_params():
    assert BookParams(token_id="123").token_id == "123"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_orderbook_summary.py -v` → FAIL (modules absent).

- [ ] **Step 3: Create the models**

`agentpit/datastructures/orderbook_summary.py`:
```python
from pydantic import BaseModel, Field


class OrderBookLevel(BaseModel):
    """One aggregated price level (decimal strings, §8.5)."""

    price: str
    size: str


class OrderBookSummary(BaseModel):
    """CLOB `OrderBookSummary` (§8.5). Prices/sizes are decimal strings;
    `market` is the condition_id, `asset_id` the token_id."""

    market: str
    asset_id: str
    timestamp: str                      # ms epoch string
    hash: str
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)
    min_order_size: str = "0"
    tick_size: str = "0.001"
    neg_risk: bool = False
    last_trade_price: str = "0"
```

`agentpit/datastructures/book_params.py`:
```python
from pydantic import BaseModel, Field


class BookParams(BaseModel):
    """One element of the `POST /books` batch request."""

    token_id: str = Field(min_length=1)
```

- [ ] **Step 4: Delete the dead model**

Run: `git rm agentpit/datastructures/orderbook_response.py`
(Confirm first it is unused: `grep -rn "orderbook_response\|OrderbookResponse" agentpit/` returns only that file.)

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_orderbook_summary.py -v` → PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add agentpit/datastructures/orderbook_summary.py agentpit/datastructures/book_params.py tests/test_orderbook_summary.py
git commit -m "feat(book): OrderBookSummary + BookParams models; drop dead orderbook_response"
```

---

## Task 2: `GET /book` + `POST /books`

**Files:**
- Modify: `agentpit/services/order_service.py`, `agentpit/api/routes/orders.py`, `agentpit/api/app.py`
- Create: `agentpit/api/routes/market_data.py`, `tests/onchain/test_book.py`

**Contract (§8.5):** `GET /book?token_id=` → `OrderBookSummary`. Aggregate per price level (`GROUP BY PRICE`, sum `REMAINING_AMOUNT`); `bids` price-descending, `asks` price-ascending; decimal strings; `timestamp` = ms epoch string; `tick_size`="0.001"; `last_trade_price` from the trades ledger. `POST /books` body `[{token_id}, …]` → `OrderBookSummary[]`.

- [ ] **Step 1: Add the service methods**

In `order_service.py`, add `import hashlib` at the top (alongside the stdlib imports). Add to `OrderService`:
```python
    def get_book(self, token_id: str) -> OrderBookSummary:
        """Aggregated order book for one outcome token (§8.5)."""
        with self._db.read() as conn:
            resolved = resolve_by_token_id(conn, token_id)
            if resolved is None:
                raise MarketNotFoundError(0)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT SIDE, PRICE, SUM(REMAINING_AMOUNT) AS SZ FROM orders "
                "WHERE TOKEN_ID = ? AND STATUS = 'live' GROUP BY SIDE, PRICE",
                (token_id,),
            ).fetchall()
            last = conn.execute(
                "SELECT PRICE FROM trades WHERE ASSET_ID = ? AND STATUS != 'FAILED' "
                "ORDER BY MATCH_TIME DESC LIMIT 1",
                (token_id,),
            ).fetchone()
        bids = sorted(
            (r for r in rows if r["SIDE"] == "BUY"),
            key=lambda r: -int(r["PRICE"]),
        )
        asks = sorted(
            (r for r in rows if r["SIDE"] == "SELL"),
            key=lambda r: int(r["PRICE"]),
        )

        def level(r: sqlite3.Row) -> OrderBookLevel:
            return OrderBookLevel(
                price=price_to_decimal_str(int(r["PRICE"])),
                size=size_to_decimal_str(int(r["SZ"])),
            )

        bid_levels = [level(r) for r in bids]
        ask_levels = [level(r) for r in asks]
        last_trade_price = (
            price_to_decimal_str(int(last["PRICE"])) if last is not None else "0"
        )
        timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        digest_src = "".join(
            f"{l.price}:{l.size}|" for l in (*bid_levels, *ask_levels)
        )
        book_hash = hashlib.sha1(digest_src.encode()).hexdigest()  # noqa: S324
        return OrderBookSummary(
            market=resolved.condition_id,
            asset_id=token_id,
            timestamp=timestamp,
            hash=book_hash,
            bids=bid_levels,
            asks=ask_levels,
            last_trade_price=last_trade_price,
        )

    def get_books(self, token_ids: list[str]) -> list[OrderBookSummary]:
        """Batch book read (§8.5). Skips unknown token ids."""
        out: list[OrderBookSummary] = []
        for token_id in token_ids:
            try:
                out.append(self.get_book(token_id))
            except MarketNotFoundError:
                continue
        return out
```
Add imports near the existing datastructure imports:
```python
from agentpit.datastructures.orderbook_summary import OrderBookLevel, OrderBookSummary
```
(`resolve_by_token_id`, `price_to_decimal_str`, `size_to_decimal_str`, `MarketNotFoundError`, `datetime`/`timezone`, `sqlite3` are already imported.)

- [ ] **Step 2: Remove `get_orderbook`**

Delete the `get_orderbook` method from `OrderService` (the new `get_book` replaces it). Keep `_resolve_market_lookup` (still used by `get_sparkline` until Task 3).

- [ ] **Step 3: Create the market-data router**

`agentpit/api/routes/market_data.py`:
```python
from fastapi import APIRouter

from agentpit.api.deps import OrderServiceDep
from agentpit.datastructures.book_params import BookParams
from agentpit.datastructures.orderbook_summary import OrderBookSummary

router = APIRouter(tags=["market-data"])


@router.get("/book", response_model=OrderBookSummary)
def get_book(token_id: str, service: OrderServiceDep) -> OrderBookSummary:
    return service.get_book(token_id)


@router.post("/books", response_model=list[OrderBookSummary])
def get_books(
    params: list[BookParams], service: OrderServiceDep
) -> list[OrderBookSummary]:
    return service.get_books([p.token_id for p in params])
```

- [ ] **Step 4: Register the router + remove the old route**

In `agentpit/api/app.py`: add `market_data` to the `from agentpit.api.routes import (...)` tuple and add `app.include_router(market_data.router)` next to the others.
In `agentpit/api/routes/orders.py`: remove the `@router.get("/orderbook/{market_id}/{outcome}")` handler.

- [ ] **Step 5: Write the failing test** (create before running)

Create `tests/onchain/test_book.py`:
```python
"""GET /book aggregates the live book into Polymarket OrderBookSummary
shape (§8.5). Live-chain (placing orders needs a prepared market)."""

from tests.onchain._helpers import create_market, fresh_client, register, hdr


def _yes(market) -> str:
    return market["erc1155_tokens"][0][0]


def test_book_aggregates_levels_as_decimal_strings():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes(market)
    cond = market["condition_id"]["value"]
    # Two BUYs at the same price aggregate into one bid level of size 8.
    for _ in range(2):
        client.post(
            "/order",
            headers=hdr(tok),
            json={"token_id": yes, "side": "BUY", "price": "0.40", "size": 4},
        )

    body = client.get(f"/book?token_id={yes}").json()
    assert body["market"] == cond
    assert body["asset_id"] == yes
    assert body["tick_size"] == "0.001"
    assert body["neg_risk"] is False
    assert body["bids"] == [{"price": "0.4", "size": "8"}]
    assert body["asks"] == []
    assert body["timestamp"].isdigit()


def test_books_batch():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes(market)
    client.post(
        "/order",
        headers=hdr(tok),
        json={"token_id": yes, "side": "BUY", "price": "0.40", "size": 5},
    )
    body = client.post("/books", json=[{"token_id": yes}]).json()
    assert isinstance(body, list) and len(body) == 1
    assert body[0]["asset_id"] == yes


def test_book_unknown_token_404():
    client = fresh_client()
    assert client.get("/book?token_id=999999").status_code == 404
```

- [ ] **Step 6: Run**

Run: `.venv/bin/python -m pytest tests/onchain/test_book.py -v` → PASS (3 passed). Also `.venv/bin/python -c "from agentpit.api.app import create_app; create_app()"` builds.

- [ ] **Step 7: Commit**

```bash
git add agentpit/services/order_service.py agentpit/api/routes/market_data.py agentpit/api/routes/orders.py agentpit/api/app.py tests/onchain/test_book.py
git commit -m "feat(book): GET /book + POST /books (aggregated OrderBookSummary)"
```

---

## Task 3: `GET /prices-history`

**Files:**
- Modify: `agentpit/services/order_service.py`, `agentpit/api/routes/market_data.py`, `agentpit/api/routes/orders.py`
- Create: `tests/api/test_prices_history.py`

**Contract (§8.6):** `GET /prices-history?market=<token_id>&startTs=&endTs=&interval=&fidelity=` → `{ "history": [ {"t": <int seconds>, "p": <float 0–1>} ] }`, ascending by `t`. (`market` is the **token_id**, mirroring Polymarket's confusing param name.) Drop volume fields.

- [ ] **Step 1: Add the service method (replace `get_sparkline`)**

In `order_service.py`, replace `get_sparkline` with:
```python
    _INTERVAL_HOURS = {
        "1h": 1, "6h": 6, "1d": 24, "1w": 168, "1m": 720, "max": 24 * 365 * 100,
    }

    def get_prices_history(
        self,
        token_id: str,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
        interval: str = "1d",
        fidelity: int = 0,
    ) -> dict:
        """Trade-price history for one outcome token (§8.6).

        Returns ``{"history": [{"t": int_seconds, "p": float_0_1}]}`` ascending.
        `interval` selects a trailing window unless explicit start/end are given;
        `fidelity` (minutes) thins the series.
        """
        now = int(datetime.now(timezone.utc).timestamp())
        end = end_ts if end_ts is not None else now
        if start_ts is not None:
            start = start_ts
        else:
            hours = self._INTERVAL_HOURS.get(interval, 24)
            start = end - hours * 3600
        with self._db.read() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT MATCH_TIME, PRICE FROM trades "
                "WHERE ASSET_ID = ? AND STATUS != 'FAILED' "
                "AND MATCH_TIME >= ? AND MATCH_TIME <= ? "
                "ORDER BY MATCH_TIME ASC",
                (token_id, start, end),
            ).fetchall()
        points = [
            {"t": int(r["MATCH_TIME"]), "p": price_to_float(int(r["PRICE"]))}
            for r in rows
        ]
        # Optional fidelity thinning (minutes between kept points).
        if fidelity > 0 and points:
            step = fidelity * 60
            thinned = [points[0]]
            for pt in points[1:]:
                if pt["t"] - thinned[-1]["t"] >= step:
                    thinned.append(pt)
            if thinned[-1] is not points[-1]:
                thinned.append(points[-1])
            points = thinned
        return {"history": points}
```
Add `price_to_float` to the existing `from agentpit.polymarket.format import (...)` line.

- [ ] **Step 2: Remove `_resolve_market_lookup` if now unused**

`get_book`/`get_prices_history` resolve by token_id, not `_resolve_market_lookup`. After `get_sparkline` is gone, check: `grep -n "_resolve_market_lookup" agentpit/services/order_service.py`. If no callers remain, delete `_resolve_market_lookup`. (If `get_midpoint`/`get_price` in Task 4 would use it, leave it — but they also resolve by token_id, so it should be removable.)

- [ ] **Step 3: Add the route + remove `/sparkline`**

In `agentpit/api/routes/market_data.py` add:
```python
@router.get("/prices-history")
def get_prices_history(
    market: str,
    service: OrderServiceDep,
    startTs: int | None = None,
    endTs: int | None = None,
    interval: str = "1d",
    fidelity: int = 0,
) -> dict:
    return service.get_prices_history(
        market, start_ts=startTs, end_ts=endTs, interval=interval, fidelity=fidelity
    )
```
In `agentpit/api/routes/orders.py`: remove the `@router.get("/sparkline/{market_id}/{outcome}")` handler. (`OrderServiceDep` import stays — still used by the place/cancel routes.)

- [ ] **Step 4: Write + run the test**

Create `tests/api/test_prices_history.py`:
```python
"""GET /prices-history returns {history:[{t,p}]} (§8.6). The no-trade path
needs no chain (empty history)."""

from fastapi.testclient import TestClient

from agentpit.api.main import app


def test_prices_history_empty_for_unknown_token():
    with TestClient(app) as client:
        body = client.get("/prices-history?market=999999").json()
        assert body == {"history": []}


def test_prices_history_shape_keys():
    with TestClient(app) as client:
        body = client.get("/prices-history?market=1&interval=1w").json()
        assert "history" in body and isinstance(body["history"], list)
```
Run: `.venv/bin/python -m pytest tests/api/test_prices_history.py -v` → PASS (2 passed). Also confirm the app builds.

- [ ] **Step 5: Commit**

```bash
git add agentpit/services/order_service.py agentpit/api/routes/market_data.py agentpit/api/routes/orders.py tests/api/test_prices_history.py
git commit -m "feat(book): GET /prices-history replaces /sparkline ({history:[{t,p}]})"
```

---

## Task 4: `GET /midpoint`, `/price`, `/last-trade-price`

**Files:**
- Modify: `agentpit/services/order_service.py`, `agentpit/api/routes/market_data.py`
- Create: `tests/onchain/test_market_data.py`

**Contracts (§8.7):**
- `GET /midpoint?token_id=` → `{ "mid": "0.50" }` — avg of best bid/ask; 404 if no book (needs both sides).
- `GET /price?token_id=&side=BUY|SELL` → `{ "price": "0.55" }` — BUY→best ask, SELL→best bid; 404 if that side empty.
- `GET /last-trade-price?token_id=` → `{ "price": "0.52", "side": "BUY" }` — most recent trade; 404 if none.

- [ ] **Step 1: Add the service methods**

In `order_service.py` add (a small private helper reads best bid/ask once):
```python
    def _best_bid_ask(self, token_id: str) -> tuple[int | None, int | None]:
        """(best_bid_price_int, best_ask_price_int) from the live book."""
        with self._db.read() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT SIDE, PRICE FROM orders "
                "WHERE TOKEN_ID = ? AND STATUS = 'live'",
                (token_id,),
            ).fetchall()
        bids = [int(r["PRICE"]) for r in rows if r["SIDE"] == "BUY"]
        asks = [int(r["PRICE"]) for r in rows if r["SIDE"] == "SELL"]
        return (max(bids) if bids else None, min(asks) if asks else None)

    def get_midpoint(self, token_id: str) -> dict:
        best_bid, best_ask = self._best_bid_ask(token_id)
        if best_bid is None or best_ask is None:
            raise NotFoundError("no book for token")
        return {"mid": price_to_decimal_str((best_bid + best_ask) // 2)}

    def get_price(self, token_id: str, side: str) -> dict:
        best_bid, best_ask = self._best_bid_ask(token_id)
        chosen = best_ask if side == "BUY" else best_bid
        if chosen is None:
            raise NotFoundError("no resting orders on that side")
        return {"price": price_to_decimal_str(chosen)}

    def get_last_trade_price(self, token_id: str) -> dict:
        with self._db.read() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT PRICE, SIDE FROM trades "
                "WHERE ASSET_ID = ? AND STATUS != 'FAILED' "
                "ORDER BY MATCH_TIME DESC LIMIT 1",
                (token_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError("no trades for token")
        return {"price": price_to_decimal_str(int(row["PRICE"])), "side": row["SIDE"]}
```
Add `NotFoundError` to the `from agentpit.domain.exceptions import (...)` line.

- [ ] **Step 2: Add the routes**

In `agentpit/api/routes/market_data.py` add:
```python
@router.get("/midpoint")
def get_midpoint(token_id: str, service: OrderServiceDep) -> dict:
    return service.get_midpoint(token_id)


@router.get("/price")
def get_price(token_id: str, side: str, service: OrderServiceDep) -> dict:
    return service.get_price(token_id, side)


@router.get("/last-trade-price")
def get_last_trade_price(token_id: str, service: OrderServiceDep) -> dict:
    return service.get_last_trade_price(token_id)
```

- [ ] **Step 3: Write + run the test**

Create `tests/onchain/test_market_data.py`:
```python
"""GET /midpoint, /price, /last-trade-price (§8.7). Live-chain: a crossing
pair produces a settled trade for last-trade-price; resting orders give a book."""

from tests.onchain._helpers import create_market, fresh_client, register, hdr


def _yes(market) -> str:
    return market["erc1155_tokens"][0][0]


def test_midpoint_and_price_from_book():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes(market)
    # Resting bid 0.40 and ask 0.60 (different users not needed for the book).
    client.post("/order", headers=hdr(tok), json={"token_id": yes, "side": "BUY", "price": "0.40", "size": 5})
    client.post("/order", headers=hdr(tok), json={"token_id": yes, "side": "SELL", "price": "0.60", "size": 5})

    assert client.get(f"/midpoint?token_id={yes}").json() == {"mid": "0.5"}
    assert client.get(f"/price?token_id={yes}&side=BUY").json() == {"price": "0.6"}
    assert client.get(f"/price?token_id={yes}&side=SELL").json() == {"price": "0.4"}


def test_midpoint_404_without_book():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes(market)
    client.post("/order", headers=hdr(tok), json={"token_id": yes, "side": "BUY", "price": "0.40", "size": 5})
    # Only a bid → no midpoint.
    assert client.get(f"/midpoint?token_id={yes}").status_code == 404
    # No trades yet → last-trade-price 404.
    assert client.get(f"/last-trade-price?token_id={yes}").status_code == 404


def test_resting_orders_feed_the_book():
    # A bid below the ask doesn't cross, so both rest — /midpoint and /price
    # are deterministic from the resting book, no settlement needed.
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes(market)
    client.post("/order", headers=hdr(tok), json={"token_id": yes, "side": "BUY", "price": "0.40", "size": 5})
    client.post("/order", headers=hdr(tok), json={"token_id": yes, "side": "SELL", "price": "0.60", "size": 5})
    body = client.get(f"/book?token_id={yes}").json()
    assert len(body["bids"]) == 1 and len(body["asks"]) == 1
```

Run: `.venv/bin/python -m pytest tests/onchain/test_market_data.py -v` → PASS (3 passed).

- [ ] **Step 4: Positive `/last-trade-price` on a real settled trade**

`/last-trade-price` reads the latest trade row, so a positive assertion needs a *settled* cross — which `tests/onchain/test_trade_flow.py::test_match_settles_on_chain` already produces (A BUY YES @0.6 maker, B SELL YES @0.6 taker → NORMAL match at 0.6). Add to the END of that test (the `client`/`market` are in scope):
```python
    # /last-trade-price reflects the settled match: maker price 0.6, taker side SELL.
    yes_token = market["erc1155_tokens"][0][0]
    ltp = client.get(f"/last-trade-price?token_id={yes_token}").json()
    assert ltp == {"price": "0.6", "side": "SELL"}
```
(The ledger records the maker's price and the taker's side; for this NORMAL match both parties traded at 0.6, so it's unambiguous. The MINT/MERGE maker-vs-taker-price wart from Phase 2 doesn't apply here.)

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/python -m pytest tests/onchain/test_market_data.py tests/onchain/test_trade_flow.py -v` → PASS.
```bash
git add agentpit/services/order_service.py agentpit/api/routes/market_data.py tests/onchain/test_market_data.py tests/onchain/test_trade_flow.py
git commit -m "feat(book): GET /midpoint, /price, /last-trade-price"
```

---

## Task 5: UI — order book (decimal levels, token_id-keyed)

**Files:**
- Modify: `ui/src/types/order.ts`, `ui/src/api/orders.ts`, `ui/src/components/orders/orderMath.ts`, `ui/src/lib/useYesMid.ts`, `ui/src/lib/useYesMidMap.test.ts`, `ui/src/components/orders/Orderbook.tsx`, `ui/src/components/{MarketCard,MultiMarketEventCard,EventLeaderboardRow}.tsx`, `ui/src/components/orders/OrderTicket.tsx`

This is the high-touch fan-out. Read each file fully first. The shape change: the book is now `OrderBookSummary` with **decimal-string** price levels, keyed by **token_id**. All micro-int math (`/ 1_000_000`, `PRICE`, `REMAINING_AMOUNT`) collapses to `parseFloat` on already-0–1 decimal strings.

- [ ] **Step 1: Types (`ui/src/types/order.ts`)**

Replace `OrderbookEntry`/`OrderbookResponse` with the summary shape (keep `OrderSide`/`OrderType`/`MarketOrderResult`/`PlaceOrderRequest`/`OrderResponse`):
```typescript
export interface OrderBookLevel {
  price: string; // decimal 0–1
  size: string;  // decimal shares
}

export interface OrderBookSummary {
  market: string;       // condition_id
  asset_id: string;     // token_id
  timestamp: string;
  hash: string;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  min_order_size: string;
  tick_size: string;
  neg_risk: boolean;
  last_trade_price: string;
}
```

- [ ] **Step 2: API (`ui/src/api/orders.ts`)**

Replace `getOrderbook`/`useOrderbook` with token_id-keyed `getBook`/`useBook`:
```typescript
export async function getBook(tokenId: string): Promise<OrderBookSummary> {
  return apiFetch<OrderBookSummary>(`/book?token_id=${encodeURIComponent(tokenId)}`);
}

export function useBook(tokenId: string | undefined) {
  return useQuery({
    queryKey: ["book", tokenId],
    queryFn: () => {
      if (!tokenId) throw new Error("tokenId is required");
      return getBook(tokenId);
    },
    enabled: Boolean(tokenId),
    refetchInterval: 3000,
    refetchIntervalInBackground: false,
  });
}
```
Update the `placeMarketOrder` book typing: `book: OrderBookSummary` instead of `OrderbookResponse`. Its `computeMarketBuy(args.book.asks, …)` calls now pass decimal-level arrays (see Step 3). Update the import of `OrderbookResponse` → `OrderBookSummary`.

- [ ] **Step 3: orderMath (`ui/src/components/orders/orderMath.ts`)**

The server now returns aggregated decimal levels, so `aggregateLevels` is no longer needed for re-bucketing — but `Orderbook.tsx` and the math still want an `OrderbookLevel { price:number; size:number }` working type in 0–1 dollars / display shares. Rework:
- `OrderbookLevel` stays `{ price: number; size: number }` but now means **dollars (0–1)** and **display shares** (NOT micro).
- Add `levelsFrom(levels: OrderBookLevel[]): OrderbookLevel[]` that maps the wire `{price,size}` strings → `{ price: parseFloat(price), size: parseFloat(size) }`. (Replaces `aggregateLevels`; the server already aggregated + snapped to tick.)
- `bestAskMicro`/`bestBidMicro` → `bestAsk(levels)`/`bestBid(levels)` returning **dollars** (`Math.min/max` of the parsed prices), or keep names but return dollars — update callers. Since these now operate on already-parsed levels, simplest: `bestAsk(book.asks)` = min price.
- `computeMarketBuy(asks: OrderBookLevel[], dollarAmount)` / `computeMarketSell(bids: OrderBookLevel[], shares)`: the wire `price` is already dollars (0–1) and `size` already display shares. Remove the `/ 1_000_000` scaling. `sizeWire` must still be **whole shares** for the new `POST /order` (Phase 2 made `size` share-denominated) — so `sizeWire` should now be the share count directly (e.g. `dollarAmount / priceCap`), NOT `* SHARES_SCALE`. Rename or keep `sizeWire` but make it whole shares; update `placeMarketOrder` which divides by `SHARES_SCALE` — that division must be REMOVED there too (it now already has shares). **Coordinate this with Step 2** so the size passed to `placeOrder` ends up in whole shares exactly once.
- `SHARES_SCALE`/`PRICE_TICK` constants: `SHARES_SCALE` may become unused once micro math is gone — remove it if no remaining consumer (check `Orderbook.tsx`, `OrderTicket.tsx`, portfolio). `PRICE_TICK` (micro) likewise.

> Implementer: this is the trickiest step. Keep ONE source of truth for units: wire = decimal dollars + decimal shares; UI math = numbers in dollars + shares; `POST /order` `size` = whole shares. Grep every reader of `.PRICE`, `.REMAINING_AMOUNT`, `/ 1_000_000`, `* SHARES_SCALE`, `/ SHARES_SCALE`, `SHARES_SCALE` across `ui/src` and reconcile them all. Run the vitest + build to prove it.

- [ ] **Step 4: `useYesMid.ts`**

- `computeMid(book: OrderBookSummary | undefined)`: `bid = book.bids.length ? Math.max(...book.bids.map(b => parseFloat(b.price))) : null` (NO `/1e6`); same for `ask` via `Math.min`. Mid logic unchanged.
- `useOutcomeMid` and `useYesMidMap`: switch from `getOrderbook(marketId, label)` to `getBook(tokenId)`. Change signatures to take a **token id**:
  - `useOutcomeMid(tokenId: string | undefined)` — callers resolve `market.erc1155_tokens[i][0]`.
  - `useYesMidMap(markets)`: use `m.erc1155_tokens[0]?.[0]` (the YES **token id**, not the label) as the query input; keep the returned `Map<market_id, mid>` keyed by `market_id`.
  - Query keys: `["book", tokenId]` to dedupe with `useBook`.

- [ ] **Step 5: `useYesMidMap.test.ts`**

Rewrite the `entry`/`book` helpers to the new shape:
```typescript
import type { OrderBookLevel, OrderBookSummary } from "@/types/order";

function lvl(price: number): OrderBookLevel {
  return { price: String(price), size: "1" };
}

function book(bids: number[], asks: number[]): OrderBookSummary {
  return {
    market: "0xc", asset_id: "1", timestamp: "0", hash: "",
    bids: bids.map(lvl), asks: asks.map(lvl),
    min_order_size: "0", tick_size: "0.001", neg_risk: false,
    last_trade_price: "0",
  };
}
```
Change the numeric inputs from micro (`400_000`) to dollars (`0.4`): `computeMid(book([0.4, 0.38], [0.46, 0.48]))` → `0.43`, etc. Keep the `deriveNoCents` tests unchanged.

- [ ] **Step 6: `Orderbook.tsx`**

- Take a `tokenId: string` prop (+ keep `outcome` for the label display); call `useBook(tokenId)`.
- Replace `aggregateLevels(data.asks)` with `levelsFrom(data.asks)` (already aggregated server-side; just parse).
- `formatCents`: now receives **dollars** → `(d * 100).toFixed(1)`. `formatSize`: receives **display shares** → drop the `/ SHARES_SCALE`. `bestAsk`/`bestBid`: parsed dollars (no `/1e6`). The `Row` `total = price * size` (both already display units).

- [ ] **Step 7: Consumers**

- `MarketCard.tsx`: `useOutcomeMid(market.erc1155_tokens[0]?.[0])` (YES token id); the sparkline part is Task 6.
- `MultiMarketEventCard.tsx`: `useYesMidMap(markets)` — signature unchanged (still takes markets), internals updated in Step 4.
- `EventLeaderboardRow.tsx`: `useOutcomeMid(yesTokenId)`/`useOutcomeMid(noTokenId)` from `market.erc1155_tokens[0]/[1]?.[0]`.
- `OrderTicket.tsx`: wherever it renders `<Orderbook marketId=… outcome=… />`, pass `tokenId={tokenId}` (it already computes `tokenId` from Phase 2) + `outcome`. If it uses `useOrderbook` directly, switch to `useBook(tokenId)`.

- [ ] **Step 8: Build + test**

Run from `ui/`: `npm run build` (typecheck) and `npx vitest run src/lib/useYesMidMap.test.ts` → both green. Fix every consumer the type change surfaces.

- [ ] **Step 9: Commit**

```bash
cd /Users/yavorsky/dev/agentpit
git add ui/src/types/order.ts ui/src/api/orders.ts ui/src/components/orders/orderMath.ts ui/src/lib/useYesMid.ts ui/src/lib/useYesMidMap.test.ts ui/src/components/orders/Orderbook.tsx ui/src/components/MarketCard.tsx ui/src/components/MultiMarketEventCard.tsx ui/src/components/EventLeaderboardRow.tsx ui/src/components/orders/OrderTicket.tsx
git commit -m "feat(ui): order book consumes decimal OrderBookSummary keyed by token_id"
```

---

## Task 6: UI — prices-history chart

**Files:**
- Modify: `ui/src/types/market.ts`, `ui/src/api/markets.ts`, `ui/src/components/EventChart.tsx`, `ui/src/components/MarketCard.tsx`

- [ ] **Step 1: Types (`ui/src/types/market.ts`)**

```typescript
export interface SparklinePoint {
  t: number;   // unix seconds
  p: number;   // probability 0–1 (was micro-USDC int)
}

export interface PricesHistoryResponse {
  history: SparklinePoint[];
}
```
Remove the old `SparklineResponse` (`points`/`window_hours`/`volume_*`).

- [ ] **Step 2: API (`ui/src/api/markets.ts`)**

Replace `getSparkline`/`useSparkline` with token_id-keyed prices-history:
```typescript
export async function getPricesHistory(
  tokenId: string,
  interval = "1d",
): Promise<PricesHistoryResponse> {
  return apiFetch<PricesHistoryResponse>(
    `/prices-history?market=${encodeURIComponent(tokenId)}&interval=${interval}`,
  );
}

export function usePricesHistory(tokenId: string | undefined, interval = "1d") {
  return useQuery({
    queryKey: ["prices-history", tokenId, interval],
    queryFn: () => {
      if (!tokenId) throw new Error("tokenId is required");
      return getPricesHistory(tokenId, interval);
    },
    enabled: Boolean(tokenId),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: false,
    refetchIntervalInBackground: false,
  });
}
```

- [ ] **Step 3: Consumers**

- `EventChart.tsx`: `getSparkline(s.market.market_id, outcome, …)` → `getPricesHistory(s.market.erc1155_tokens[0][0])` (YES token id). The series now reads `queryData[i]?.history ?? []`; `MultiSparklineSeries.points` maps from `.history`. `p` is now a float 0–1, so any `p > peak`/axis math that assumed micro (e.g. divide by 10_000) must switch to a 0–1 scale (`* 100` for cents).
- `MarketCard.tsx`: `useSparkline(market.market_id, yesLabel)` → `usePricesHistory(market.erc1155_tokens[0]?.[0])`; `spark?.points` → `spark?.history`; the change calc `(last.p - first.p) / 10_000` → `(last.p - first.p) * 100` (p is now 0–1, Δ in cents). Confirm the `Sparkline` component's expected point shape (`{t,p}`) still matches — `p` is now 0–1; if `Sparkline`/`MultiSparkline` scale internally by a fixed domain, adjust the domain from `[0, 1_000_000]` to `[0, 1]`.

- [ ] **Step 4: Build**

Run from `ui/`: `npm run build` → green. Inspect the chart-scaling code (`MultiSparkline`, `chartGeometry.ts`) for any hardcoded `1_000_000`/`10_000` domain and fix to the 0–1 `p` scale.

- [ ] **Step 5: Commit**

```bash
git add ui/src/types/market.ts ui/src/api/markets.ts ui/src/components/EventChart.tsx ui/src/components/MarketCard.tsx ui/src/components/MultiSparkline.tsx ui/src/lib/chartGeometry.ts
git commit -m "feat(ui): chart consumes /prices-history (float p, token_id-keyed)"
```
(Only add the chart-internal files if Step 4 required touching them.)

---

## Final verification

- [ ] **Full suite**: `.venv/bin/python -m pytest -q -p no:cacheprovider` → all pass.
- [ ] **UI**: `cd ui && npm run build && npx vitest run` → green.
- [ ] **No dangling refs**: `grep -rn "/orderbook\|/sparkline\|getOrderbook\|useOrderbook\|getSparkline\|useSparkline\|OrderbookEntry\|OrderbookResponse\|SparklineResponse\|volume_micro" agentpit/ ui/src/ | grep -v node_modules` → no hits in migrated code (`agentpit_bots/`/`scripts/` are Phase 5).
- [ ] **Final whole-phase review** (subagent-driven-development), then checkpoint with the user before Phase 4.

---

## Notes for the implementer

- **Run Python via `.venv/bin/python`.** On-chain tests need the forked anvil + deployed stack (already up).
- **Cross-check shapes** against the live Polymarket OpenAPI via the docs MCP (`docs.polymarket.com/mcp`) for `OrderBookSummary` and `prices-history` when a detail is ambiguous.
- **`/book` is keyed by `token_id`** (not market_id+outcome) — the bridge from a Polymarket conditionId is: `GET /markets?polymarket_condition_id=` → `clobTokenIds` → `/book?token_id=`.
- **Internal consumers out of scope** (Phase 5): do not edit `agentpit_bots/`, `tests/bots/`, `scripts/seed_market_orders.py`.
- After editing, report any new LSP/TS diagnostics in changed files and fix them.
