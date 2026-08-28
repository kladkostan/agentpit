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

