"""What a position would actually fetch if it were sold right now.

A row's `currentValue` is `curPrice x size` and `curPrice` is the book
MIDPOINT, so the profile was quoting a price no one had offered: a sale
executes against the bids, below the mid, and walks down as it eats depth.
`sellableValue` / `sellableSize` are that walk, mirroring the order the Sell
button sends -- a GTC limit for the whole size at `max(best_bid - 0.02, 0.01)`
with the remainder cancelled (`placeMarketOrder` in `ui/src/api/orders.ts`,
`computeMarketSell` in `ui/src/components/orders/orderMath.ts`).
"""

from __future__ import annotations

import json
import time
import uuid

import pytest

from agentpit.auth.passwords import hash_password
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_write import TableWrite
from agentpit.services.account_service import AccountService, sellable_against_bids
from tests.db_helpers import fresh_test_db

# --- the walk itself -------------------------------------------------------


def test_one_deep_level_absorbs_the_whole_position():
    got = sellable_against_bids([(500_000, 100_000_000)], 40_000_000)
    assert got.size == 40.0
    assert got.value == pytest.approx(20.0)


def test_levels_are_consumed_best_price_first():
    """Deliberately fed worst-price-first: a walk that trusted row order would
    hand shares to the 0.48 bid while the 0.50 bid was still waiting."""
    got = sellable_against_bids(
        [(480_000, 10_000_000), (500_000, 10_000_000), (490_000, 10_000_000)],
        25_000_000,
    )
    assert got.size == 25.0
    assert got.value == pytest.approx(5.0 + 4.9 + 2.4)  # 10@.50 + 10@.49 + 5@.48


def test_a_bid_beneath_the_slippage_floor_is_left_untouched():
    """The order is a limit at `best_bid - SLIPPAGE_CAP`, so a bid one micro
    below that cannot fill it however deep it is -- here a thousand shares of
    depth that the position must not be told it can sell into."""
    got = sellable_against_bids(
        [(500_000, 10_000_000), (479_999, 1_000_000_000)], 100_000_000
    )
    assert got.size == 10.0
    assert got.value == pytest.approx(5.0)


def test_a_bid_exactly_at_the_floor_still_fills():
    """The cap is a limit price, and a limit fills AT its price."""
    got = sellable_against_bids(
        [(500_000, 10_000_000), (480_000, 10_000_000)], 20_000_000
    )
    assert got.size == 20.0
    assert got.value == pytest.approx(5.0 + 4.8)


def test_the_floor_never_falls_below_a_cent():
    """`MIN_PROB` clamps it: on a near-worthless token `best_bid - 0.02` is
    negative, and a floor below zero would sweep in bids the real order --
    which the API will not accept under $0.01 -- can never reach."""
    got = sellable_against_bids(
        [(15_000, 10_000_000), (9_000, 10_000_000)], 20_000_000
    )
    assert got.size == 10.0
    assert got.value == pytest.approx(0.15)


def test_depth_shorter_than_the_position_sells_only_what_is_there():
    """The ticket cancels the unfilled remainder, so the shares beyond the
    book's depth simply do not sell -- `sellableSize` is short of `size`."""
    got = sellable_against_bids([(500_000, 3_000_000)], 100_000_000)
    assert got.size == 3.0
    assert got.value == pytest.approx(1.5)


def test_a_book_with_no_bids_sells_nothing():
    got = sellable_against_bids([], 100_000_000)
    assert got.size == 0.0
    assert got.value == 0.0


# --- through the service ---------------------------------------------------


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


class _StubOnchain:
    """Fixed CTF balance per token id -- all `list_positions` reads from it."""

    def __init__(self, balances: dict[str, int]):
        self._balances = balances

    def ctf_balances(self, _eth_address: str, token_ids: list[int]) -> list[int]:
        return [self._balances.get(str(t), 0) for t in token_ids]


def _insert_trade(conn, *, market: str, asset: str, taker_api_key: str) -> None:
    """One CONFIRMED fill, which is also what puts the market in scope:
    `list_positions` only scans markets the account has traded."""
    conn.execute(
        "INSERT INTO trades (TRADE_ID, MARKET, ASSET_ID, SIDE, PRICE, TRADE_SIZE, "
        "STATUS, TAKER_API_KEY, MAKER_ORDERS, MATCH_TIME) "
        "VALUES (%s, %s, %s, 'BUY', 400000, 100000000, 'CONFIRMED', %s, %s, 0)",
        (
            uuid.uuid4().hex,
            market,
            asset,
            taker_api_key,
            json.dumps([{"side": "SELL"}]),
        ),
    )


def _insert_bid(conn, *, token_id: str, price: int, original: int, remaining: int):
    conn.execute(
        "INSERT INTO orders (ORDER_ID, TOKEN_ID, SIDE, PRICE, STATUS, "
        "MAKER_AMOUNT, TAKER_AMOUNT, REMAINING_AMOUNT, EXPIRATION, CREATED_AT, "
        "API_KEY) VALUES (%s, %s, 'BUY', %s, 'live', %s, %s, %s, 0, %s, 'maker')",
        (
            uuid.uuid4().hex,
            token_id,
            price,
            original * price // 1_000_000,
            original,
            remaining,
            int(time.time()),
        ),
    )


def _position(email: str, seed: str, *, bids: list[tuple[int, int]], resolved: bool):
    """The single `PositionWire` for an account holding 100 shares of the YES
    token, with `bids` -- `(price_micro, remaining_micro)` -- resting on it."""
    db = fresh_test_db()
    # `list_positions` does `int(token_id)`, so these have to parse as ints.
    base = int.from_bytes(seed.encode(), "big")
    yes_tok, no_tok = str(base * 10 + 1), str(base * 10 + 2)
    with db.write() as conn:
        _uid, acct, api_key = TableWrite.create_user(
            conn,
            email=email,
            password_hash=hash_password("pw12pw12pw12"),
            handle=None,
        )
        req = CreateMarketRequest(
            question="Win?",
            description="d",
            erc1155_tokens=[(yes_tok, "Yes"), (no_tok, "No")],
            slug=f"sell-{seed}",
            condition_id=ConditionId(_hex32(seed)),
            state=MarketState.ACTIVE,
        )
        m = TableWrite.create_market(conn, req, is_polygon_market=False)
        _insert_trade(conn, market=_hex32(seed), asset=yes_tok, taker_api_key=api_key)
        for price, remaining in bids:
            _insert_bid(
                conn,
                token_id=yes_tok,
                price=price,
                original=remaining * 2,
                remaining=remaining,
            )
        if resolved:
            TableWrite.resolve_market(
                conn, market_id=m.market_id, winning_outcome_index=0
            )

    onchain = _StubOnchain({yes_tok: 100_000_000})
    service = AccountService(db, onchain=onchain)  # type: ignore[arg-type]
    out = service.list_positions(acct.address)
    assert len(out) == 1
    return out[0]

