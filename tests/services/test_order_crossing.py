"""The matcher's crossing test must match the CTFExchange bit-for-bit
(CalculatorHelper.isCrossing over exact amounts, ONE=1e18, floored), so a DB
match can never trip the on-chain NotCrossing revert that fails the whole order
('No fills'). These pin the replica to the contract's semantics."""

from agentpit.services.order_service import (
    _EXCHANGE_ONE,
    _exchange_price,
    _orders_cross,
)


def test_exchange_price_floors_like_the_contract():
    assert _exchange_price(62, 100, "BUY") == 62 * _EXCHANGE_ONE // 100
    assert _exchange_price(100, 62, "SELL") == 62 * _EXCHANGE_ONE // 100
    assert _exchange_price(5, 0, "BUY") == 0  # zero taker amount -> 0


def test_buy_below_maker_price_does_not_cross():
    # The exact rounding-boundary bug: a taker BUY whose effective price is
    # 0.619 must NOT match a maker SELL @ 0.62 (the on-chain revert case).
    assert not _orders_cross(619, 1000, "BUY", 100, 62, "SELL")


def test_buy_crosses_equal_and_cheaper_asks():
    assert _orders_cross(62, 100, "BUY", 100, 62, "SELL")  # 0.62 vs 0.62 (inclusive)
    assert _orders_cross(62, 100, "BUY", 100, 60, "SELL")  # 0.62 vs 0.60


def test_sell_crosses_equal_and_higher_bids_only():
    assert _orders_cross(100, 40, "SELL", 40, 100, "BUY")     # 0.40 vs bid 0.40
    assert _orders_cross(100, 40, "SELL", 45, 100, "BUY")     # 0.40 vs bid 0.45
    assert not _orders_cross(100, 40, "SELL", 35, 100, "BUY")  # 0.40 vs bid 0.35


def test_mint_and_merge_boundaries():
    assert _orders_cross(62, 100, "BUY", 40, 100, "BUY")        # 1.02 >= 1 (MINT)
    assert not _orders_cross(30, 100, "BUY", 40, 100, "BUY")    # 0.70 < 1
    assert _orders_cross(100, 30, "SELL", 100, 40, "SELL")      # 0.70 <= 1 (MERGE)
    assert not _orders_cross(100, 60, "SELL", 100, 50, "SELL")  # 1.10 > 1


def test_zero_taker_amount_is_treated_as_crossing():
    assert _orders_cross(0, 0, "BUY", 100, 62, "SELL")
