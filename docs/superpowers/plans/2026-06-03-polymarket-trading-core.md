# Phase 2 — Trading Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate agentpit's order-placement + cancel + open-orders endpoints to Polymarket's exact CLOB interface (`POST /order`, `DELETE /order` + siblings, `GET /data/orders`), with `token_id` as the canonical order identifier and share-denominated sizes, then rework the React order UI in lockstep.

**Architecture:** Reshape the existing `OrderResponse`/`PlaceOrderRequest` models in place (no parallel models). `POST /order` accepts logical args (`token_id`, `price`, `size`, `side`, `order_type`, `expiration`) — `size` is whole shares (×10⁶ internally via `agentpit.polymarket.format`). A transitional `market_id`+`outcome` fallback is accepted only when `token_id` is absent, and is removed at the end of the phase once the UI sends `token_id`. Cancels become uniform `{canceled, not_canceled}` responses (HTTP 200 always). `GET /data/orders` returns a bare `OpenOrder[]` filtered to the authenticated user, with the non-secret `USER_ID` as `owner`. The in-repo `agentpit_bots` simulation client is **out of scope** for this phase (deferred to Phase 5 per the 2026-06-03 checkpoint); its tests mock the server so they stay green.

**Tech Stack:** FastAPI, Pydantic v2, raw `sqlite3`, pytest + `TestClient`, on-chain settlement via anvil-forked CTFExchange (live-chain tests under `tests/onchain/`), React + TypeScript + React Query UI.

**Spec:** `docs/superpowers/specs/2026-06-03-agentpit-polymarket-api-migration-design.md` §8.1–8.3, §7, §9.

**Representation conventions (§4):** CLOB prices/sizes are **decimal strings** (`"0.36"`, `"30"`). Internally agentpit scales by 10⁶ (`_PRICE_ONE = 10**6` = $1.00; 1 share = 10⁶ base units). Use `agentpit.polymarket.format`:
- `price_to_decimal_str(360000) == "0.36"`, `size_to_decimal_str(30000000) == "30"`.
- `decimal_str_to_size_micro("30") == 30000000`, `decimal_str_to_price_int("0.36") == 360000`.

**Exception→HTTP mapping (existing):** `NotFoundError`→404, `BusinessRuleError`→400 (covers `MarketStateError`, `InsufficientBalanceError`), `AlreadyExistsError`→409, `InvalidCredentialsError`→401. Registered in `agentpit/api/exception_handlers.py`.

---

## File Structure

**Create:**
- `agentpit/datastructures/open_order.py` — `OpenOrder` (the `GET /data/orders` element).
- `agentpit/datastructures/cancel_orders_response.py` — `CancelOrdersResponse` `{canceled, not_canceled}`.
- `agentpit/datastructures/cancel_requests.py` — `CancelOrderRequest`, `CancelMarketOrdersRequest`.
- `tests/onchain/test_data_orders.py` — open-orders shape + filter tests (live-chain; placing orders runs settlement).
- `tests/onchain/test_order_cancel.py` — cancel-family semantics (live-chain).

**Modify:**
- `agentpit/datastructures/order_response.py` — drop `filledSize`/`remainingSize`/`avgPrice`/`txHash`; add `transactionsHashes`/`takingAmount`/`makingAmount`/`tradeIDs`.
- `agentpit/datastructures/place_order_request.py` — `token_id` canonical; `market_id`/`outcome` optional fallback; `size` becomes share-denominated `Decimal`.
- `agentpit/services/order_service.py` — resolve via `token_id`, share→micro size, new response fields, `_insert_trade` returns trade id, `_settle_on_chain` hashes → `0x`-prefixed array, cancel-family + `list_open_orders`.
- `agentpit/api/routes/orders.py` — `POST /order`, `DELETE /order` + siblings, `GET /data/orders`; remove `POST /orders`, `DELETE /orders/{id}`, `GET /orders/mine`. (`GET /orderbook/...` + `GET /sparkline/...` stay untouched — Phase 3.)
- `tests/test_place_order_request.py` — new request-model fields.
- `tests/onchain/test_trade_flow.py` — `/order`, share sizes, new response fields.
- `tests/api/test_orders_mine.py` → renamed concept: `GET /data/orders`.
- `ui/src/types/order.ts`, `ui/src/api/orders.ts`, `ui/src/components/orders/OrderTicket.tsx` — request/response reshape, `token_id`, share sizes.

**Do NOT touch this phase:** `agentpit_bots/` and `tests/bots/` (Phase 5). `GET /orderbook`, `GET /sparkline` and the `Orderbook`/book UI (Phase 3).

---

## Task 1: Reshape `OrderResponse`

**Files:**
- Modify: `agentpit/datastructures/order_response.py`
- Test: `tests/test_order_response.py` (create)

The exact `postOrder` shape (§8.1):
```json
{ "success": true, "errorMsg": "", "orderID": "0x…", "status": "live",
  "transactionsHashes": ["0x…"], "takingAmount": "", "makingAmount": "", "tradeIDs": [] }
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_order_response.py`:
```python
"""OrderResponse matches Polymarket's postOrder shape (§8.1)."""

import pytest
from pydantic import ValidationError

from agentpit.datastructures.order_response import OrderResponse


def test_minimal_unfilled_order_defaults():
    r = OrderResponse(success=True, orderID="0xabc", status="live")
    d = r.model_dump()
    assert d == {
        "success": True,
        "errorMsg": "",
        "orderID": "0xabc",
        "status": "live",
        "transactionsHashes": [],
        "takingAmount": "",
        "makingAmount": "",
        "tradeIDs": [],
    }


def test_matched_order_carries_hashes_and_amounts():
    r = OrderResponse(
        success=True,
        orderID="0xabc",
        status="matched",
        transactionsHashes=["0xdeadbeef"],
        takingAmount="100",
        makingAmount="36",
        tradeIDs=["t1", "t2"],
    )
    assert r.transactionsHashes == ["0xdeadbeef"]
    assert r.tradeIDs == ["t1", "t2"]


def test_dropped_fields_are_gone():
    # The old agentpit-flavored fields must no longer exist.
    assert "filledSize" not in OrderResponse.model_fields
    assert "remainingSize" not in OrderResponse.model_fields
    assert "avgPrice" not in OrderResponse.model_fields
    assert "txHash" not in OrderResponse.model_fields


def test_empty_order_id_rejected():
    with pytest.raises(ValidationError):
        OrderResponse(success=True, orderID="", status="live")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_order_response.py -v`
Expected: FAIL (old fields still present / new fields missing).

- [ ] **Step 3: Rewrite the model**

Replace the entire body of `agentpit/datastructures/order_response.py`:
```python
from pydantic import BaseModel, Field, field_validator


class OrderResponse(BaseModel):
    """Polymarket CLOB `postOrder` response shape (§8.1).

    `status` is the documented HTTP enum (lowercase): `live | matched |
    delayed`. agentpit emits only `live` and `matched`. A settlement
    failure is reported as `success=False` + `errorMsg` (not a status).
    """

    success: bool
    errorMsg: str = ""
    orderID: str
    status: str
    transactionsHashes: list[str] = Field(default_factory=list)
    takingAmount: str = ""
    makingAmount: str = ""
    tradeIDs: list[str] = Field(default_factory=list)

    @field_validator("orderID", "status")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("must not be empty")
        return v
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_order_response.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agentpit/datastructures/order_response.py tests/test_order_response.py
git commit -m "feat(order): reshape OrderResponse to Polymarket postOrder shape"
```

---

## Task 2: Reshape `PlaceOrderRequest` (token_id canonical, share sizes)

**Files:**
- Modify: `agentpit/datastructures/place_order_request.py`
- Test: `tests/test_place_order_request.py`

New request shape (§8.1): `token_id` canonical; `market_id`+`outcome` accepted only when `token_id` is absent; `size` is whole shares.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_place_order_request.py` (keep the existing price-tick tests; they pass unchanged since `size=100` is now 100 shares):
```python
from agentpit.datastructures.place_order_request import PlaceOrderRequest  # already imported


def test_token_id_only_is_valid():
    r = PlaceOrderRequest(token_id="123", side="BUY", price="0.5", size=100)
    assert r.token_id == "123"
    assert r.market_id is None and r.outcome is None


def test_market_outcome_fallback_is_valid():
    r = PlaceOrderRequest(market_id=1, outcome="Yes", side="BUY", price="0.5", size=100)
    assert r.token_id is None
    assert r.market_id == 1 and r.outcome == "Yes"


def test_requires_an_identifier():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PlaceOrderRequest(side="BUY", price="0.5", size=100)


def test_size_is_share_denominated_decimal():
    from decimal import Decimal
    r = PlaceOrderRequest(token_id="123", side="BUY", price="0.5", size="2.5")
    assert r.size == Decimal("2.5")


def test_size_must_be_positive():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PlaceOrderRequest(token_id="123", side="BUY", price="0.5", size=0)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_place_order_request.py -v`
Expected: FAIL (`token_id` unknown field / `market_id` required).

- [ ] **Step 3: Rewrite the model**

Replace `agentpit/datastructures/place_order_request.py`:
```python
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Minimum price increment: 0.1¢ = $0.001. Prices snap to this grid so the book
# can't accumulate sub-tick precision — the minimum meaningful step is 0.1¢.
_PRICE_TICK = Decimal("0.001")


class PlaceOrderRequest(BaseModel):
    """Logical inputs for `POST /order` (§8.1).

    `token_id` is the canonical outcome identifier. `market_id` + `outcome`
    are a transitional fallback accepted only when `token_id` is absent
    (removed at the end of Phase 2 once the UI sends `token_id`).
    `size` is whole shares (converted to 10⁶ base units in the service).
    """

    token_id: str | None = Field(default=None, min_length=1)
    market_id: int | None = Field(default=None, ge=0)
    outcome: str | None = Field(default=None, min_length=1)
    side: Literal["BUY", "SELL"]
    price: Decimal = Field(gt=0, lt=1)  # probability, 0 < p < 1
    size: Decimal = Field(gt=0)  # whole shares (× 10⁶ base units internally)
    order_type: Literal["GTC", "FOK", "FAK", "GTD"] = "GTC"
    expiration: int = 0  # unix seconds, required if GTD

    @field_validator("price")
    @classmethod
    def _snap_to_tick(cls, v: Decimal) -> Decimal:
        """Round the price onto the 0.1¢ tick. Reject only if snapping
        leaves the open interval (0, 1)."""
        snapped = v.quantize(_PRICE_TICK)
        if snapped <= 0 or snapped >= 1:
            raise ValueError("price must be within (0, 1) on the 0.1¢ tick")
        return snapped

    @model_validator(mode="after")
    def _require_identifier(self) -> "PlaceOrderRequest":
        if self.token_id is None and (self.market_id is None or self.outcome is None):
            raise ValueError(
                "either token_id, or both market_id and outcome, are required"
            )
        return self
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_place_order_request.py -v`
Expected: PASS (all, including the original 3 price-tick tests).

- [ ] **Step 5: Commit**

```bash
git add agentpit/datastructures/place_order_request.py tests/test_place_order_request.py
git commit -m "feat(order): token_id canonical + share-denominated size on PlaceOrderRequest"
```

---

## Task 3: `OrderService.place_order` rework

**Files:**
- Modify: `agentpit/services/order_service.py`
- Test: covered by the live-chain `tests/onchain/test_trade_flow.py` rewrite (Task 9). Add a focused converter sanity assert here only if cheap.

This task changes internal logic; its behavioral contract is verified by Task 9's on-chain round-trip. Implement carefully — no new unit test is required beyond what Task 9 covers (placing an order needs the live chain). To avoid a confused piecemeal edit, replace the **whole** `place_order` method body and add the two helpers in one pass.

- [ ] **Step 1: Add imports**

Add near the existing imports at the top of `agentpit/services/order_service.py`:
```python
from agentpit.polymarket.format import decimal_str_to_size_micro, size_to_decimal_str
from agentpit.polymarket.resolve import resolve_by_market_outcome, resolve_by_token_id
```
(`MarketStateError` is already imported; `_PRICE_ONE` is already defined in this module.)

- [ ] **Step 2: Replace the entire `place_order` method**

Replace the whole current `place_order` (everything from `def place_order` through its final `return OrderResponse(...)`) with:
```python
    def place_order(self, user: User, payload: PlaceOrderRequest) -> OrderResponse:
        token_id_int, _token_id_str = self._resolve_token(payload)
        size_micro = decimal_str_to_size_micro(str(payload.size))
        maker_amount, taker_amount = self._amounts_from_price_size(
            payload.side, payload.price, size_micro
        )

        # Pre-flight balance check — reject obvious losers before signing.
        self._check_balance(user.eth_address, payload.side, maker_amount, token_id_int)

        order = OrderData(
            salt=secrets.randbits(256),
            maker=user.eth_address,
            signer=user.eth_address,
            taker=_ZERO_ADDR,
            tokenId=token_id_int,
            makerAmount=maker_amount,
            takerAmount=taker_amount,
            expiration=int(payload.expiration),
            nonce=0,
            feeRateBps=0,
            side=0 if payload.side == "BUY" else 1,
            signatureType=0,
        )
        signature = sign_order(user.eth_key, self._onchain._client.deployment, order)

        order_id = self._compute_order_id(order)
        price_int = self._price_int(order)

        with self._db.write() as conn:
            self._insert_order(
                conn,
                api_key=user.api_key,
                order=order,
                order_id=order_id,
                signature=signature,
                price_int=price_int,
                order_type=payload.order_type,
            )
            taker_row = self._get_order_row(conn, order_id)
            matches = self._match(conn, taker_row, dry_run=False)

        tx_hashes: list[str] = []
        if matches:
            try:
                hashes = self._settle_on_chain(order, signature, matches)
                tx_hashes = ["0x" + h.hex() for h in hashes]
            except Exception as exc:
                log.exception("on-chain settlement failed for order %s", order_id)
                with self._db.write() as conn:
                    conn.execute(
                        "UPDATE trades SET STATUS = 'FAILED' "
                        "WHERE TAKER_ORDER_ID = ?",
                        (order_id,),
                    )
                failed_row = self._safe_row(order_id)
                return OrderResponse(
                    success=False,
                    orderID=order_id,
                    status=failed_row["STATUS"] if failed_row else "live",
                    errorMsg=f"settlement failed: {exc}",
                )

        with self._db.read() as conn:
            row = self._get_order_row(conn, order_id)
        # takingAmount/makingAmount come from the immediate match (taker's
        # perspective), in decimal strings (§4); "" when nothing filled.
        filled_micro = sum(int(m["trade_size"]) for m in matches)
        collateral_micro = sum(
            (int(m["price"]) * int(m["trade_size"])) // _PRICE_ONE for m in matches
        )
        if matches and payload.side == "BUY":
            making_amount = size_to_decimal_str(collateral_micro)  # USDC given
            taking_amount = size_to_decimal_str(filled_micro)      # shares received
        elif matches:  # SELL taker
            making_amount = size_to_decimal_str(filled_micro)      # shares given
            taking_amount = size_to_decimal_str(collateral_micro)  # USDC received
        else:
            making_amount = taking_amount = ""

        return OrderResponse(
            success=True,
            orderID=order_id,
            status=row["STATUS"],
            transactionsHashes=tx_hashes,
            takingAmount=taking_amount,
            makingAmount=making_amount,
            tradeIDs=[m["trade_id"] for m in matches],
        )
```

- [ ] **Step 3: Add the `_resolve_token` + `_safe_row` helpers**

Add these methods to `OrderService` (place near `_resolve_market_lookup`, which stays — it is still used by `get_orderbook`/`get_sparkline` in Phase 3):
```python
    def _resolve_token(self, payload: PlaceOrderRequest) -> tuple[int, str]:
        """Resolve the order's outcome to (token_id_int, token_id_str).

        `token_id` wins when present; `market_id`+`outcome` is the
        transitional fallback. If both are supplied and disagree, that's a
        conflicting request (400, via MarketStateError → BusinessRuleError).
        """
        with self._db.read() as conn:
            if payload.token_id is not None:
                resolved = resolve_by_token_id(conn, payload.token_id)
                if resolved is None:
                    raise MarketStateError(f"unknown token_id '{payload.token_id}'")
                if payload.market_id is not None and payload.outcome is not None:
                    alt = resolve_by_market_outcome(
                        conn, payload.market_id, payload.outcome
                    )
                    if alt.token_id != resolved.token_id:
                        raise MarketStateError(
                            "token_id conflicts with market_id/outcome"
                        )
                return int(resolved.token_id), resolved.token_id
            resolved = resolve_by_market_outcome(
                conn, payload.market_id, payload.outcome
            )
            return int(resolved.token_id), resolved.token_id

    def _safe_row(self, order_id: str):
        with self._db.read() as conn:
            try:
                return self._get_order_row(conn, order_id)
            except RuntimeError:
                return None
```

- [ ] **Step 4: `_insert_trade` returns the trade id; `_match` captures it**

In `_insert_trade`, change the signature return type to `-> str` and add `return trade_id` as the last line (after the `conn.execute(...)` insert).
In `_match`'s apply loop, replace `self._insert_trade(conn, taker_row, m)` with:
```python
            m["trade_id"] = self._insert_trade(conn, taker_row, m)
```
(`dry_run` matches get no `trade_id`; the only `dry_run=True` callers are Phase-3 book/midpoint reads, which never read `trade_id`.)

- [ ] **Step 5: Remove the now-unused `_avg_price` and `_resolve_market`**

Delete the `_avg_price` static method and the `_resolve_market` method (no longer called). Keep `_resolve_market_lookup`.

- [ ] **Step 6: Verify it imports and no dead references remain**

Run: `.venv/bin/python -c "import agentpit.services.order_service"`
Expected: imports cleanly (no NameError).
Run: `grep -n "_avg_price\|_resolve_market\b\|filledSize\|remainingSize\|avgPrice\|\.txHash" agentpit/services/order_service.py`
Expected: only the surviving `_resolve_market_lookup` matches `_resolve_market` (word-boundary `\b` excludes it); no `_avg_price`/`filledSize`/`remainingSize`/`avgPrice`/`.txHash`.

- [ ] **Step 7: Commit**

```bash
git add agentpit/services/order_service.py
git commit -m "feat(order): place_order resolves token_id, emits postOrder response fields"
```

---

## Task 4: Route `POST /orders` → `POST /order`

**Files:**
- Modify: `agentpit/api/routes/orders.py`

- [ ] **Step 1: Rename the route**

In `agentpit/api/routes/orders.py`, change the place-order decorator path from `/orders` to `/order` (handler + signature unchanged):
```python
@router.post("/order", response_model=OrderResponse)
def place_order(
    payload: PlaceOrderRequest,
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> OrderResponse:
    return service.place_order(user, payload)
```

- [ ] **Step 2: Verify the app builds and the route is registered**

Run:
```bash
.venv/bin/python -c "
from agentpit.api.app import create_app
paths = {(r.path, tuple(sorted(r.methods))) for r in create_app().routes if hasattr(r, 'methods')}
assert ('/order', ('POST',)) in paths, paths
assert not any(p == '/orders' and 'POST' in m for p, m in paths), 'old /orders still present'
print('ok')
"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add agentpit/api/routes/orders.py
git commit -m "feat(order): POST /order replaces POST /orders"
```

---

## Task 5: Cancel request/response datastructures

**Files:**
- Create: `agentpit/datastructures/cancel_orders_response.py`
- Create: `agentpit/datastructures/cancel_requests.py`
- Test: `tests/test_cancel_models.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_cancel_models.py`:
```python
from agentpit.datastructures.cancel_orders_response import CancelOrdersResponse
from agentpit.datastructures.cancel_requests import (
    CancelMarketOrdersRequest,
    CancelOrderRequest,
)


def test_cancel_response_defaults_empty():
    r = CancelOrdersResponse()
    assert r.model_dump() == {"canceled": [], "not_canceled": {}}


def test_cancel_response_records_reasons():
    r = CancelOrdersResponse(canceled=["a"], not_canceled={"b": "not found"})
    assert r.canceled == ["a"]
    assert r.not_canceled == {"b": "not found"}


def test_cancel_order_request():
    assert CancelOrderRequest(orderID="0x1").orderID == "0x1"


def test_cancel_market_orders_request_all_optional():
    r = CancelMarketOrdersRequest()
    assert r.market is None and r.asset_id is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_cancel_models.py -v`
Expected: FAIL (modules do not exist).

- [ ] **Step 3: Create the models**

`agentpit/datastructures/cancel_orders_response.py`:
```python
from pydantic import BaseModel, Field


class CancelOrdersResponse(BaseModel):
    """Uniform CLOB cancel result (§8.2). HTTP 200 always for valid auth.

    `canceled` (American spelling, single 'l') lists ids actually cancelled;
    `not_canceled` maps each un-cancelled id to a human reason string. Empty
    `{}` on full success. Reason strings are not a stable enum — a robust
    client checks presence in `not_canceled`, not the text.
    """

    canceled: list[str] = Field(default_factory=list)
    not_canceled: dict[str, str] = Field(default_factory=dict)
```

`agentpit/datastructures/cancel_requests.py`:
```python
from pydantic import BaseModel, Field


class CancelOrderRequest(BaseModel):
    """Body for `DELETE /order`."""

    orderID: str = Field(min_length=1)


class CancelMarketOrdersRequest(BaseModel):
    """Body for `DELETE /cancel-market-orders` (both filters optional)."""

    market: str | None = None      # condition_id
    asset_id: str | None = None    # token_id
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_cancel_models.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agentpit/datastructures/cancel_orders_response.py agentpit/datastructures/cancel_requests.py tests/test_cancel_models.py
git commit -m "feat(order): cancel request/response models"
```

---

## Task 6: Cancel service methods

**Files:**
- Modify: `agentpit/services/order_service.py`

All cancels filter to the caller's `API_KEY` and only affect `STATUS='live'` rows; un-cancellable ids land in `not_canceled`. Replace the existing `cancel_order` boolean method.

- [ ] **Step 1: Add the cancel-family methods**

Add imports near the top of `order_service.py`:
```python
from agentpit.datastructures.cancel_orders_response import CancelOrdersResponse
```

Replace the existing `cancel_order` method with:
```python
    def cancel_orders(self, user: User, order_ids: list[str]) -> CancelOrdersResponse:
        """Cancel a set of the caller's live orders by id (§8.2)."""
        result = CancelOrdersResponse()
        with self._db.write() as conn:
            for order_id in order_ids:
                cur = conn.execute(
                    "UPDATE orders SET STATUS = 'cancelled' "
                    "WHERE ORDER_ID = ? AND API_KEY = ? AND STATUS = 'live'",
                    (order_id, user.api_key),
                )
                if cur.rowcount > 0:
                    result.canceled.append(order_id)
                else:
                    result.not_canceled[order_id] = (
                        "order not found, not yours, or not live"
                    )
        return result

    def cancel_all(self, user: User) -> CancelOrdersResponse:
        """Cancel every live order owned by the caller."""
        with self._db.read() as conn:
            conn.row_factory = sqlite3.Row
            ids = [
                r["ORDER_ID"]
                for r in conn.execute(
                    "SELECT ORDER_ID FROM orders "
                    "WHERE API_KEY = ? AND STATUS = 'live'",
                    (user.api_key,),
                ).fetchall()
            ]
        return self.cancel_orders(user, ids)

    def cancel_market_orders(
        self, user: User, market: str | None, asset_id: str | None
    ) -> CancelOrdersResponse:
        """Cancel the caller's live orders filtered by condition_id (`market`)
        and/or token_id (`asset_id`). With neither filter, cancels all."""
        clauses = ["API_KEY = ?", "STATUS = 'live'"]
        params: list = [user.api_key]
        if asset_id is not None:
            clauses.append("TOKEN_ID = ?")
            params.append(asset_id)
        if market is not None:
            # `market` is a condition_id; resolve it to the market's token ids.
            with self._db.read() as conn:
                m = TableRead.read_market_by_condition_id(conn, ConditionId(market))
            token_ids = [t for t, _label in m.erc1155_tokens] if m else ["\x00"]
            placeholders = ",".join("?" for _ in token_ids)
            clauses.append(f"TOKEN_ID IN ({placeholders})")
            params.extend(token_ids)
        with self._db.read() as conn:
            conn.row_factory = sqlite3.Row
            ids = [
                r["ORDER_ID"]
                for r in conn.execute(
                    f"SELECT ORDER_ID FROM orders WHERE {' AND '.join(clauses)}",
                    params,
                ).fetchall()
            ]
        return self.cancel_orders(user, ids)
```

Add the imports these need (near the existing imports):
```python
from agentpit.datastructures.condition_id import ConditionId
```
(`TableRead` is already imported.)

- [ ] **Step 2: Verify it imports**

Run: `.venv/bin/python -c "import agentpit.services.order_service"`
Expected: clean import.

- [ ] **Step 3: Commit**

```bash
git add agentpit/services/order_service.py
git commit -m "feat(order): cancel_orders/cancel_all/cancel_market_orders services"
```

---

## Task 7: Cancel routes (`DELETE /order` + siblings)

**Files:**
- Modify: `agentpit/api/routes/orders.py`
- Test: `tests/onchain/test_order_cancel.py` (create)

| Route | Body |
|---|---|
| `DELETE /order` | `{ "orderID": "<id>" }` |
| `DELETE /orders` | `["<id>", …]` (bare array) |
| `DELETE /cancel-all` | *(none)* |
| `DELETE /cancel-market-orders` | `{ "market": "<condition_id>", "asset_id": "<token_id>" }` |

- [ ] **Step 1: Write the failing test**

Create `tests/onchain/test_order_cancel.py`:
```python
"""Cancel-family semantics (§8.2): HTTP 200 always; results in
{canceled, not_canceled}. Live-chain because placing an order signs +
inserts against a market created via prepareCondition."""

import secrets

from tests.onchain._helpers import create_market, fresh_client, register, hdr


def _place(client, token, *, token_id, side, price, size):
    return client.post(
        "/order",
        headers=hdr(token),
        json={"token_id": token_id, "side": side, "price": price, "size": size},
    ).json()


def _yes_token(market) -> str:
    return market["erc1155_tokens"][0][0]


def test_delete_order_cancels_and_is_idempotent():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes_token(market)
    placed = _place(client, tok, token_id=yes, side="BUY", price="0.40", size=10)
    oid = placed["orderID"]

    r1 = client.request("DELETE", "/order", headers=hdr(tok), json={"orderID": oid})
    assert r1.status_code == 200
    assert r1.json() == {"canceled": [oid], "not_canceled": {}}

    # Second cancel: 200 with the id recorded in not_canceled (no 404).
    r2 = client.request("DELETE", "/order", headers=hdr(tok), json={"orderID": oid})
    assert r2.status_code == 200
    body = r2.json()
    assert body["canceled"] == []
    assert oid in body["not_canceled"]


def test_cancel_all_clears_my_live_orders():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes_token(market)
    o1 = _place(client, tok, token_id=yes, side="BUY", price="0.30", size=5)["orderID"]
    o2 = _place(client, tok, token_id=yes, side="BUY", price="0.31", size=5)["orderID"]

    r = client.request("DELETE", "/cancel-all", headers=hdr(tok))
    assert r.status_code == 200
    assert set(r.json()["canceled"]) == {o1, o2}


def test_cancel_market_orders_filters_by_condition_id():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes_token(market)
    cond = market["condition_id"]["value"]
    oid = _place(client, tok, token_id=yes, side="BUY", price="0.30", size=5)["orderID"]

    r = client.request(
        "DELETE", "/cancel-market-orders", headers=hdr(tok), json={"market": cond}
    )
    assert r.status_code == 200
    assert r.json()["canceled"] == [oid]


def test_delete_orders_bulk():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes_token(market)
    o1 = _place(client, tok, token_id=yes, side="BUY", price="0.30", size=5)["orderID"]
    r = client.request("DELETE", "/orders", headers=hdr(tok), json=[o1, "0xmissing"])
    assert r.status_code == 200
    body = r.json()
    assert body["canceled"] == [o1]
    assert "0xmissing" in body["not_canceled"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/onchain/test_order_cancel.py -v`
Expected: FAIL (routes 404 / old `DELETE /orders/{id}` shape).

- [ ] **Step 3: Replace the cancel routes**

In `agentpit/api/routes/orders.py`, remove the old `@router.delete("/orders/{order_id}")` handler and add (update imports: drop `HTTPException`/`status` if now unused; add `Body`):
```python
from fastapi import APIRouter, Body

from agentpit.api.deps import CurrentUserDep, OrderServiceDep
from agentpit.datastructures.cancel_orders_response import CancelOrdersResponse
from agentpit.datastructures.cancel_requests import (
    CancelMarketOrdersRequest,
    CancelOrderRequest,
)
from agentpit.datastructures.order_response import OrderResponse
from agentpit.datastructures.place_order_request import PlaceOrderRequest


@router.delete("/order", response_model=CancelOrdersResponse)
def cancel_order(
    payload: CancelOrderRequest,
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> CancelOrdersResponse:
    return service.cancel_orders(user, [payload.orderID])


@router.delete("/orders", response_model=CancelOrdersResponse)
def cancel_orders(
    order_ids: list[str],
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> CancelOrdersResponse:
    return service.cancel_orders(user, order_ids)


@router.delete("/cancel-all", response_model=CancelOrdersResponse)
def cancel_all(
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> CancelOrdersResponse:
    return service.cancel_all(user)


@router.delete("/cancel-market-orders", response_model=CancelOrdersResponse)
def cancel_market_orders(
    payload: CancelMarketOrdersRequest,
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> CancelOrdersResponse:
    return service.cancel_market_orders(user, payload.market, payload.asset_id)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/onchain/test_order_cancel.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agentpit/api/routes/orders.py tests/onchain/test_order_cancel.py
git commit -m "feat(order): DELETE /order + siblings with {canceled,not_canceled}"
```

---

## Task 8: `GET /data/orders` (open orders) + `OpenOrder`

**Files:**
- Create: `agentpit/datastructures/open_order.py`
- Modify: `agentpit/services/order_service.py`, `agentpit/api/routes/orders.py`
- Test: `tests/onchain/test_data_orders.py` (create); migrate `tests/api/test_orders_mine.py`

`OpenOrder` shape (§8.3): `owner` is the non-secret `USER_ID`; `market` is the condition_id; sizes are human-decimal share strings; `status`/`outcome` unprefixed; `associate_trades` ships `[]`.

- [ ] **Step 1: Create the `OpenOrder` model**

`agentpit/datastructures/open_order.py`:
```python
from pydantic import BaseModel, Field


class OpenOrder(BaseModel):
    """One element of `GET /data/orders` (CLOB open order, §8.3).

    `owner` is the order owner's non-secret USER_ID (never the api_key).
    `original_size`/`size_matched` are human-decimal share strings.
    """

    id: str
    status: str = "LIVE"
    owner: str
    maker_address: str
    market: str          # condition_id
    asset_id: str        # token_id
    side: str
    original_size: str
    size_matched: str
    price: str
    associate_trades: list[str] = Field(default_factory=list)
    outcome: str
    created_at: int
    expiration: str
    order_type: str
```

- [ ] **Step 2: Write the failing test**

Create `tests/onchain/test_data_orders.py`:
```python
"""GET /data/orders returns the caller's open orders as a bare OpenOrder[]
(§8.3). Live-chain (placing orders needs a prepared market)."""

from tests.onchain._helpers import create_market, fresh_client, register, hdr


def _yes_token(market) -> str:
    return market["erc1155_tokens"][0][0]


def test_open_orders_shape_and_owner_is_user_id():
    client = fresh_client()
    reg = register(client)
    tok = reg["access_token"]
    user_id = reg["user"]["user_id"]
    # NB: the api_key is never serialized in any response (§13), so the test
    # asserts `owner` positively equals the non-secret user_id.
    market = create_market(client)
    yes = _yes_token(market)
    cond = market["condition_id"]["value"]

    placed = client.post(
        "/order",
        headers=hdr(tok),
        json={"token_id": yes, "side": "BUY", "price": "0.40", "size": 25},
    ).json()
    oid = placed["orderID"]

    body = client.get("/data/orders", headers=hdr(tok)).json()
    assert isinstance(body, list) and len(body) == 1
    o = body[0]
    assert o["id"] == oid
    assert o["status"] == "LIVE"
    assert o["owner"] == user_id          # non-secret USER_ID, never the api_key
    assert o["market"] == cond            # condition_id, not token_id
    assert o["asset_id"] == yes
    assert o["side"] == "BUY"
    assert o["original_size"] == "25"
    assert o["size_matched"] == "0"
    assert o["price"] == "0.4"
    assert o["associate_trades"] == []
    assert o["order_type"] == "GTC"


def test_open_orders_filtered_by_asset_id():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes_token(market)
    client.post(
        "/order",
        headers=hdr(tok),
        json={"token_id": yes, "side": "BUY", "price": "0.40", "size": 25},
    )
    hit = client.get(f"/data/orders?asset_id={yes}", headers=hdr(tok)).json()
    assert len(hit) == 1
    miss = client.get("/data/orders?asset_id=999999", headers=hdr(tok)).json()
    assert miss == []


def test_open_orders_requires_auth():
    client = fresh_client()
    assert client.get("/data/orders").status_code == 401
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/onchain/test_data_orders.py -v`
Expected: FAIL (route 404).

- [ ] **Step 4: Add the service method**

In `order_service.py`, replace `list_live_orders` with `list_open_orders`:
```python
    def list_open_orders(
        self,
        user: User,
        *,
        market: str | None = None,
        asset_id: str | None = None,
        order_id: str | None = None,
    ) -> list[OpenOrder]:
        """Return the caller's live orders as Polymarket OpenOrder[] (§8.3)."""
        clauses = ["API_KEY = ?", "STATUS = 'live'"]
        params: list = [user.api_key]
        if asset_id is not None:
            clauses.append("TOKEN_ID = ?")
            params.append(asset_id)
        if order_id is not None:
            clauses.append("ORDER_ID = ?")
            params.append(order_id)
        with self._db.read() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT ORDER_ID, TOKEN_ID, SIDE, PRICE, REMAINING_AMOUNT, MAKER, "
                "MAKER_AMOUNT, TAKER_AMOUNT, CREATED_AT, EXPIRATION, ORDER_TYPE "
                f"FROM orders WHERE {' AND '.join(clauses)} "
                "ORDER BY CREATED_AT DESC",
                params,
            ).fetchall()
            out: list[OpenOrder] = []
            for r in rows:
                resolved = resolve_by_token_id(conn, r["TOKEN_ID"])
                if resolved is None:
                    continue
                if market is not None and resolved.condition_id != market:
                    continue
                # Original outcome-token size: BUY → takerAmount, SELL → makerAmount.
                original = int(
                    r["TAKER_AMOUNT"] if r["SIDE"] == "BUY" else r["MAKER_AMOUNT"]
                )
                matched = original - int(r["REMAINING_AMOUNT"])
                outcome_label = resolved.market.erc1155_tokens[
                    resolved.outcome_index
                ][1]
                out.append(
                    OpenOrder(
                        id=r["ORDER_ID"],
                        owner=user.user_id,
                        maker_address=r["MAKER"],
                        market=resolved.condition_id,
                        asset_id=r["TOKEN_ID"],
                        side=r["SIDE"],
                        original_size=size_to_decimal_str(original),
                        size_matched=size_to_decimal_str(matched),
                        price=price_to_decimal_str(int(r["PRICE"])),
                        outcome=outcome_label,
                        created_at=int(r["CREATED_AT"]),
                        expiration=str(r["EXPIRATION"]),
                        order_type=r["ORDER_TYPE"],
                    )
                )
        return out
```
Add the imports it needs (extend the format import + add OpenOrder):
```python
from agentpit.polymarket.format import (
    decimal_str_to_size_micro,
    price_to_decimal_str,
    size_to_decimal_str,
)
from agentpit.datastructures.open_order import OpenOrder
```
Confirm `User` has `user_id` — it does (`agentpit/datastructures/user.py`).

- [ ] **Step 5: Replace the route**

In `agentpit/api/routes/orders.py`, remove `GET /orders/mine` and add (import `OpenOrder`):
```python
@router.get("/data/orders", response_model=list[OpenOrder])
def list_open_orders(
    user: CurrentUserDep,
    service: OrderServiceDep,
    market: str | None = None,
    asset_id: str | None = None,
    id: str | None = None,
) -> list[OpenOrder]:
    return service.list_open_orders(
        user, market=market, asset_id=asset_id, order_id=id
    )
```

- [ ] **Step 6: Migrate `tests/api/test_orders_mine.py`**

Replace its body with the `/data/orders` form (keep it in `tests/api/` — the empty case needs no chain):
```python
"""GET /data/orders returns the caller's open orders (bare OpenOrder[])."""

from fastapi.testclient import TestClient

from agentpit.api.main import app


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_data_orders_empty_for_new_user():
    with TestClient(app) as client:
        body = client.post(
            "/register",
            json={"email": "mine1@example.com", "password": "hunter22hunter22"},
        ).json()
        resp = client.get("/data/orders", headers=_hdr(body["access_token"]))
        assert resp.status_code == 200, resp.text
        assert resp.json() == []


def test_data_orders_requires_auth():
    with TestClient(app) as client:
        assert client.get("/data/orders").status_code == 401
```

- [ ] **Step 7: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/onchain/test_data_orders.py tests/api/test_orders_mine.py -v`
Expected: PASS (5 passed).

- [ ] **Step 8: Commit**

```bash
git add agentpit/datastructures/open_order.py agentpit/services/order_service.py agentpit/api/routes/orders.py tests/onchain/test_data_orders.py tests/api/test_orders_mine.py
git commit -m "feat(order): GET /data/orders returns OpenOrder[] (owner=USER_ID)"
```

---

## Task 9: Update `tests/onchain/test_trade_flow.py` to the new contract

**Files:**
- Modify: `tests/onchain/test_trade_flow.py`

The settlement round-trips are the behavioral coverage for Task 3. Switch to `POST /order`, share sizes, and the new response fields. Keep the `market_id`+`outcome` fallback here for now (Task 11 flips it to `token_id`).

- [ ] **Step 1: Update `test_match_settles_on_chain`**

Replace the two `client.post("/orders", …)` calls' path with `/order` and the sizes (`100_000_000` → `100`). Replace the matched-order assertions block:
```python
    assert pb["success"], pb
    assert pb["status"] == "matched"
    assert pb["makingAmount"] == "100"          # SELL taker gave 100 shares
    assert pb["takingAmount"] == "60"           # received 60 apUSD (100 @ 0.6)
    assert pb["transactionsHashes"]             # non-empty list
    assert "filledSize" not in pb
```
The on-chain balance assertions (`a_pre_usd - 60_000_000`, etc.) are unchanged — internal base units are unaffected by the request-size representation change.

- [ ] **Step 2: Update `test_complementary_buys_mint_via_split`**

Change both `/orders` → `/order`; sizes `100_000_000` → `100`, `50_000_000` → `50`. Replace the matched assertions:
```python
    assert pb["success"], pb
    assert pb["status"] == "matched", pb
    assert pb["makingAmount"] == "35"           # NO buyer paid 50 @ 0.70
    assert pb["transactionsHashes"], pb
```
The `/orderbook/.../YES` assertion stays (`REMAINING_AMOUNT == 50_000_000`) — the resting order still holds 50M base units outstanding; only the request representation changed.

- [ ] **Step 3: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/onchain/test_trade_flow.py -v`
Expected: PASS (3 passed). If `makingAmount`/`takingAmount` differ, cross-check the §8.1 derivation against the live Polymarket OpenAPI via the docs MCP (`docs.polymarket.com/mcp`, search `postOrder makingAmount`) and adjust the assertion to the verified semantics — do not weaken the round-trip.

- [ ] **Step 4: Commit**

```bash
git add tests/onchain/test_trade_flow.py
git commit -m "test: trade-flow uses POST /order, share sizes, postOrder response"
```

---

## Task 10: UI — order types, API module, OrderTicket

**Files:**
- Modify: `ui/src/types/order.ts`, `ui/src/api/orders.ts`, `ui/src/components/orders/OrderTicket.tsx`

Read each file first; match its existing idiom. The book/orderbook types and components stay on the old shape this phase (Phase 3). Only the place/cancel/open-orders path changes.

- [ ] **Step 1: Update the order types**

In `ui/src/types/order.ts`:
- `PlaceOrderRequest` → `{ token_id: string; price: number; size: number; side: "BUY" | "SELL"; order_type?: "GTC" | "FOK" | "FAK" | "GTD"; expiration?: number }`.
- `OrderResponse` → `{ success: boolean; errorMsg: string; orderID: string; status: string; transactionsHashes: string[]; takingAmount: string; makingAmount: string; tradeIDs: string[] }` (remove `filledSize`/`remainingSize`/`avgPrice`/`txHash`).
- If an `OpenOrder` type is needed by a consumer, add `{ id; status; owner; maker_address; market; asset_id; side; original_size; size_matched; price; associate_trades: string[]; outcome; created_at; expiration; order_type }`.

- [ ] **Step 2: Update the API module**

In `ui/src/api/orders.ts`:
- `placeOrder` → `POST /order` with the new `PlaceOrderRequest` (send `token_id`, `size` in whole shares).
- `cancelOrder(orderID)` → `apiFetch("/order", { method: "DELETE", body: JSON.stringify({ orderID }) })`; treat success as `orderID` appearing in `canceled` (response `{ canceled, not_canceled }`).
- Replace any `GET /orders/mine` call with `GET /data/orders` returning `OpenOrder[]`.
- Leave `getOrderbook`/book code unchanged (Phase 3).

- [ ] **Step 3: Update `OrderTicket.tsx`**

- Resolve `token_id` from the loaded market by selected outcome: parse `market.clobTokenIds` / use `erc1155_tokens` and the chosen outcome index (the Gamma `Market` adapter from Phase 1 exposes the token ids; pick the index matching the selected outcome label).
- Send `size` as whole shares (the input is already a share quantity in the UX; ensure it is not pre-scaled by 10⁶).
- Remove any use of `filledSize`/`remainingSize`/`avgPrice` from the place response; show submission success from `success`/`status`, and rely on `/data/orders` (or existing portfolio polling) for fill state.

- [ ] **Step 4: Typecheck / build**

Run: `cd ui && npm run build`
Expected: build succeeds (no TS errors). Fix any stale consumers the type changes surface.

- [ ] **Step 5: Commit**

```bash
git add ui/src/types/order.ts ui/src/api/orders.ts ui/src/components/orders/OrderTicket.tsx
git commit -m "feat(ui): order ticket sends token_id + share size; postOrder/cancel shapes"
```

---

## Task 11: Remove the `market_id`+`outcome` fallback (end-of-phase)

**Files:**
- Modify: `agentpit/datastructures/place_order_request.py`, `agentpit/services/order_service.py`, `tests/onchain/test_trade_flow.py`, `tests/test_place_order_request.py`

Per §8.1/§9, once the UI sends `token_id` the transitional fallback is removed. (`agentpit_bots` still sends `market_id`+`outcome`, but it is deferred to Phase 5 and its tests mock the server, so this does not break the suite.)

- [ ] **Step 1: Make `token_id` required on the request**

In `place_order_request.py`: make `token_id: str = Field(min_length=1)` (required), remove `market_id`/`outcome` fields and the `_require_identifier` model-validator. Keep `price`/`size`/`side`/`order_type`/`expiration`.

- [ ] **Step 2: Simplify the service resolver**

In `order_service.py` `_resolve_token`, drop the fallback/conflict branch:
```python
    def _resolve_token(self, payload: PlaceOrderRequest) -> tuple[int, str]:
        with self._db.read() as conn:
            resolved = resolve_by_token_id(conn, payload.token_id)
        if resolved is None:
            raise MarketStateError(f"unknown token_id '{payload.token_id}'")
        return int(resolved.token_id), resolved.token_id
```
Remove the now-unused `resolve_by_market_outcome` import if nothing else uses it in this module.

- [ ] **Step 3: Update tests to send `token_id`**

In `tests/onchain/test_trade_flow.py`, change the order bodies from `{"market_id": …, "outcome": "YES", …}` to `{"token_id": yes_id_str, …}` where `yes_id_str = market["erc1155_tokens"][0][0]` (YES) for both buyer and seller; for the complement test use the NO token id for B's NO order.
In `tests/test_place_order_request.py`, update `_req(...)` and the new tests to pass `token_id="123"` instead of `market_id`/`outcome`; drop `test_market_outcome_fallback_is_valid` and `test_requires_an_identifier` (no longer applicable), or replace with `test_token_id_required` asserting a `ValidationError` when `token_id` is missing.

- [ ] **Step 4: Run the order suite**

Run: `.venv/bin/python -m pytest tests/test_place_order_request.py tests/onchain/test_trade_flow.py tests/onchain/test_data_orders.py tests/onchain/test_order_cancel.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit/datastructures/place_order_request.py agentpit/services/order_service.py tests/onchain/test_trade_flow.py tests/test_place_order_request.py
git commit -m "feat(order): token_id required — remove market_id/outcome fallback"
```

---

## Final verification

- [ ] **Run the full suite**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider`
Expected: all pass (the new order tests + the existing 225 baseline; `tests/bots/*` remain green because they mock the bot client, which is untouched).

- [ ] **Confirm no dangling references to removed endpoints/fields in app code**

Run:
```bash
grep -rn "/orders/mine\|filledSize\|remainingSize\|avgPrice\|\.txHash\b" agentpit/ ui/src/ | grep -v node_modules
```
Expected: no hits in `agentpit/` (non-bot) or `ui/src/`. (`agentpit_bots/` hits are expected — Phase 5.)

- [ ] **Dispatch the final whole-phase code review** (per subagent-driven-development), then proceed to `superpowers:finishing-a-development-branch`.

---

## Notes for the implementer

- **Run Python via `.venv/bin/python`.** On-chain tests (`tests/onchain/`) require the forked anvil + deployed stack already running (`scripts/run_node.sh`, `scripts/deploy_exchange.sh`); the env is up as of this plan's baseline.
- **Cross-check shapes against the live Polymarket OpenAPI** via the docs MCP (`docs.polymarket.com/mcp`) when a wire detail is ambiguous — especially `postOrder` `makingAmount`/`takingAmount` units (Task 3/9) and the `OpenOrder` field set (Task 8).
- **Secret-safety (§13):** `owner` on `OpenOrder` is the `USER_ID`, never the api_key. The `tests/onchain/test_data_orders.py` owner assertion guards this — keep it.
- **`agentpit_bots` is out of scope** (Phase 5). Do not edit `agentpit_bots/` or `tests/bots/`.
- After editing, report any new LSP diagnostics in changed files and fix them.
