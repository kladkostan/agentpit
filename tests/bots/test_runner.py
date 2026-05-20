"""Runner: discovers markets, loops bots, posts via the injected client.

The runner is wired with fakes here so tests are deterministic.
"""

import random

from agentpit_bots.bot_pool import Bot, BotRole
from agentpit_bots.client import BotCredentials
from agentpit_bots.config import BotConfig
from agentpit_bots.runner import Runner


class FakeOracle:
    def __init__(self, mids: dict[str, float]):
        self._mids = mids
        self.refreshed_with: list[list[str]] = []

    def refresh(self, token_ids):
        self.refreshed_with.append(list(token_ids))
        return self

    def midpoint(self, token_id):
        return self._mids.get(token_id)

    def is_stale(self, token_id, *, stale_after_sec, now=None):
        return False


class FakeClient:
    def __init__(self, markets, my_orders, portfolio=None):
        self._markets = markets
        self._my_orders = my_orders
        self._portfolio = portfolio or {"usdc_balance": 0, "positions": []}
        self.placed: list[dict] = []
        self.cancelled: list[str] = []

    def get_markets(self):
        return self._markets

    def list_my_orders(self, *, token):
        return list(self._my_orders.get(token, []))

    def get_portfolio(self, *, token, market_id=None):
        if market_id is None:
            return self._portfolio
        # Mirror server-side filter: only positions for the requested market.
        positions = [
            p
            for p in self._portfolio.get("positions", [])
            if int(p.get("market_id", 0)) == market_id
        ]
        return {**self._portfolio, "positions": positions}

    def place_order(self, *, token, market_id, outcome, side, price, size):
        self.placed.append(
            {
                "token": token,
                "market_id": market_id,
                "outcome": outcome,
                "side": side,
                "price": price,
                "size": size,
            }
        )
        return {
            "orderID": f"new-{len(self.placed)}",
            "status": "live",
            "success": True,
            "filledSize": "0",
            "remainingSize": str(size),
        }

    def cancel_order(self, *, token, order_id):
        self.cancelled.append(order_id)
        return {"order_id": order_id, "status": "cancelled"}


def _bot(name, role):
    return Bot(
        name=name,
        role=BotRole(role),
        creds=BotCredentials(token=f"tok-{name}", eth_address=f"0x{name}"),
    )


def test_runner_tick_places_anchor_quotes():
    markets = [
        {
            "market_id": 1,
            "market_state": "ACTIVE",
            "polymarket_yes_token_id": "poly-yes",
            "polymarket_no_token_id": "poly-no",
            "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
        }
    ]
    oracle = FakeOracle({"poly-yes": 0.50})
    client = FakeClient(markets=markets, my_orders={})
    bots = [_bot("anchor-0", "ANCHOR")]
    cfg = BotConfig(mm_half_spread_usd=0.01, mm_quote_size_shares=100)
    runner = Runner(client=client, oracle=oracle, cfg=cfg, bots=bots)

    runner.run_anchor_tick()

    # Four orders posted: YES BUY, YES SELL, NO BUY, NO SELL.
    assert len(client.placed) == 4
    yes_buy = next(
        p for p in client.placed if p["side"] == "BUY" and p["outcome"] == "Yes"
    )
    yes_sell = next(
        p for p in client.placed if p["side"] == "SELL" and p["outcome"] == "Yes"
    )
    assert yes_buy["price"] == "0.49"
    assert yes_sell["price"] == "0.51"


def test_runner_quotes_sub_cent_market_at_full_precision():
    """On a near-zero market the bid and ask differ by less than a cent. The
    quotes must be posted at full precision — truncating to whole cents
    collapses both onto the same price and the anchor locks against itself."""
    markets = [
        {
            "market_id": 1,
            "market_state": "ACTIVE",
            "polymarket_yes_token_id": "poly-yes",
            "polymarket_no_token_id": "poly-no",
            "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
        }
    ]
    # poly mid 0.0075, half-spread 0.005 → YES bid 0.0025 / ask 0.0125, which
    # snap to the 0.1¢ tick as 0.002 / 0.012. Whole-cent truncation would
    # collapse both onto $0.01; tick precision keeps them distinct.
    oracle = FakeOracle({"poly-yes": 0.0075})
    client = FakeClient(markets=markets, my_orders={})
    cfg = BotConfig()  # default mm_half_spread_usd = 0.005
    runner = Runner(
        client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")]
    )
    runner.run_anchor_tick()
    yes_buy = next(
        p for p in client.placed if p["side"] == "BUY" and p["outcome"] == "Yes"
    )
    yes_sell = next(
        p for p in client.placed if p["side"] == "SELL" and p["outcome"] == "Yes"
    )
    assert yes_buy["price"] == "0.002"
    assert yes_sell["price"] == "0.012"
    assert yes_buy["price"] != yes_sell["price"]
    assert yes_buy["price"] != yes_sell["price"]


def test_runner_skips_markets_without_upstream_token_ids():
    markets = [
        {
            "market_id": 1,
            "market_state": "ACTIVE",
            "polymarket_yes_token_id": None,
            "polymarket_no_token_id": None,
            "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
        }
    ]
    oracle = FakeOracle({})
    client = FakeClient(markets=markets, my_orders={})
    cfg = BotConfig()
    runner = Runner(
        client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")]
    )
    runner.run_anchor_tick()
    assert client.placed == []


def test_runner_noise_tick_emits_one_order_per_noise_bot():
    markets = [
        {
            "market_id": 1,
            "market_state": "ACTIVE",
            "polymarket_yes_token_id": "poly-yes",
            "polymarket_no_token_id": "poly-no",
            "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
        }
    ]
    # Both outcomes pre-funded so any SELL draw passes the bootstrap check.
    portfolio = {
        "usdc_balance": 10_000 * 1_000_000,
        "positions": [
            {"market_id": 1, "token_id": "local-yes", "balance": 1_000 * 1_000_000},
            {"market_id": 1, "token_id": "local-no", "balance": 1_000 * 1_000_000},
        ],
    }
    oracle = FakeOracle({"poly-yes": 0.5})
    client = FakeClient(markets=markets, my_orders={}, portfolio=portfolio)
    cfg = BotConfig()
    bots = [_bot("noise-0", "NOISE"), _bot("noise-1", "NOISE")]
    runner = Runner(
        client=client, oracle=oracle, cfg=cfg, bots=bots, rng=random.Random(0)
    )
    runner.run_noise_tick()
    assert len(client.placed) == 2  # one per noise bot


def test_runner_noise_tick_threads_portfolio_into_strategy(monkeypatch):
    """Runner fetches portfolio per noise bot and passes per-market balances
    to NoiseTrader.compute_desired_orders."""
    markets = [
        {
            "market_id": 1,
            "market_state": "ACTIVE",
            "polymarket_yes_token_id": "poly-yes",
            "polymarket_no_token_id": "poly-no",
            "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
        }
    ]
    portfolio = {
        "usdc_balance": 0,
        "positions": [
            {"market_id": 1, "token_id": "local-yes", "balance": 42},
            {"market_id": 1, "token_id": "local-no", "balance": 7},
            # Different market — should be filtered out.
            {"market_id": 2, "token_id": "other", "balance": 999},
        ],
    }
    oracle = FakeOracle({"poly-yes": 0.5})
    client = FakeClient(markets=markets, my_orders={}, portfolio=portfolio)
    cfg = BotConfig()
    runner = Runner(
        client=client,
        oracle=oracle,
        cfg=cfg,
        bots=[_bot("noise-0", "NOISE")],
        rng=random.Random(0),
    )

    seen: list[dict[str, int] | None] = []
    real_compute = runner._noise_strat.compute_desired_orders

    def spy(**kwargs):
        seen.append(kwargs.get("token_balances"))
        return real_compute(**kwargs)

    monkeypatch.setattr(runner._noise_strat, "compute_desired_orders", spy)
    runner.run_noise_tick()
    assert seen == [{"local-yes": 42, "local-no": 7}]


def test_runner_disabled_market_skipped():
    markets = [
        {
            "market_id": 99,
            "market_state": "ACTIVE",
            "polymarket_yes_token_id": "poly-yes",
            "polymarket_no_token_id": "poly-no",
            "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
        }
    ]
    cfg = BotConfig(disabled_market_ids=frozenset({99}))
    client = FakeClient(markets=markets, my_orders={})
    oracle = FakeOracle({"poly-yes": 0.5})
    runner = Runner(
        client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")]
    )
    runner.run_anchor_tick()
    assert client.placed == []


class FakeClientWithPortfolio(FakeClient):
    def __init__(self, markets, my_orders, portfolio):
        super().__init__(markets, my_orders)
        self._portfolio = portfolio
        self.merged: list[tuple[int, int]] = []
        self.split: list[tuple[int, int]] = []

    def get_portfolio(self, *, token, market_id=None):
        if market_id is None:
            return self._portfolio
        # Mirror server-side filter: only positions for the requested market.
        positions = [
            p
            for p in self._portfolio.get("positions", [])
            if int(p.get("market_id", 0)) == market_id
        ]
        return {**self._portfolio, "positions": positions}

    def merge_positions(self, *, token, market_id, amount):
        self.merged.append((market_id, amount))
        return {}

    def split_position(self, *, token, market_id, amount):
        self.split.append((market_id, amount))
        return {}


def test_rebalance_merges_when_both_sides_have_surplus():
    markets = [
        {
            "market_id": 1,
            "market_state": "ACTIVE",
            "polymarket_yes_token_id": "poly-yes",
            "polymarket_no_token_id": "poly-no",
            "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
        }
    ]
    portfolio = {
        "usdc_balance": 5000,
        "positions": [
            {"market_id": 1, "token_id": "local-yes", "balance": 800 * 1_000_000},
            {"market_id": 1, "token_id": "local-no", "balance": 700 * 1_000_000},
        ],
    }
    # One market, budget 200 → per-market target = 200 shares.
    cfg = BotConfig(anchor_inventory_budget_usd=200)
    oracle = FakeOracle({"poly-yes": 0.5})
    client = FakeClientWithPortfolio(markets=markets, my_orders={}, portfolio=portfolio)
    runner = Runner(
        client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")]
    )
    runner.run_rebalance_tick()
    # min(yes, no) = 700; surplus = 700 - 200 = 500 shares → merge raw 500*1e6.
    assert client.merged == [(1, 500 * 1_000_000)]


def test_split_when_one_side_depleted():
    markets = [
        {
            "market_id": 1,
            "market_state": "ACTIVE",
            "polymarket_yes_token_id": "poly-yes",
            "polymarket_no_token_id": "poly-no",
            "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
        }
    ]
    portfolio = {
        "usdc_balance": 5000,
        "positions": [
            {"market_id": 1, "token_id": "local-yes", "balance": 50 * 1_000_000},
            {
                "market_id": 1,
                "token_id": "local-no",
                "balance": 5 * 1_000_000,
            },  # depleted
        ],
    }
    # One market, budget 200 → per-market target = 200 shares. quote_size 100.
    cfg = BotConfig(mm_quote_size_shares=100, anchor_inventory_budget_usd=200)
    oracle = FakeOracle({"poly-yes": 0.5})
    client = FakeClientWithPortfolio(markets=markets, my_orders={}, portfolio=portfolio)
    runner = Runner(
        client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")]
    )
    runner.run_rebalance_tick()
    # min(yes, no) = 5 < quote_size 100 → top the depleted set back up to the
    # per-market target (200), i.e. split the 195-share gap, not a flat 100.
    assert client.split == [(1, 195 * 1_000_000)]


def test_rebalance_target_divides_budget_across_markets():
    """Per-market target = budget // num_markets, so the same budget spreads
    thinner as more markets come online."""
    markets = [
        {
            "market_id": mid,
            "market_state": "ACTIVE",
            "polymarket_yes_token_id": f"poly-yes-{mid}",
            "polymarket_no_token_id": f"poly-no-{mid}",
            "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
        }
        for mid in (1, 2)
    ]
    # Both markets depleted; budget 400 over 2 markets → target 200 each.
    portfolio = {
        "usdc_balance": 5000,
        "positions": [
            {"market_id": 1, "token_id": "local-yes", "balance": 5 * 1_000_000},
            {"market_id": 1, "token_id": "local-no", "balance": 5 * 1_000_000},
            {"market_id": 2, "token_id": "local-yes", "balance": 5 * 1_000_000},
            {"market_id": 2, "token_id": "local-no", "balance": 5 * 1_000_000},
        ],
    }
    cfg = BotConfig(mm_quote_size_shares=100, anchor_inventory_budget_usd=400)
    oracle = FakeOracle({"poly-yes-1": 0.5, "poly-yes-2": 0.5})
    client = FakeClientWithPortfolio(markets=markets, my_orders={}, portfolio=portfolio)
    runner = Runner(
        client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")]
    )
    runner.run_rebalance_tick()
    # 195-share gap to the 200 target in each of the two markets.
    assert sorted(client.split) == [(1, 195 * 1_000_000), (2, 195 * 1_000_000)]


def test_runner_emits_drift_log_per_market(caplog):
    """log_drift identifies each market by its human-readable slug, not the
    bare numeric id, and logs (local_mid, poly_mid, drift)."""
    import logging as _logging

    markets = [
        {
            "market_id": 1,
            "slug": "will-tunisia-win-the-2026-world-cup",
            "market_state": "ACTIVE",
            "polymarket_yes_token_id": "poly-yes",
            "polymarket_no_token_id": "poly-no",
            "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
        }
    ]
    oracle = FakeOracle({"poly-yes": 0.42})

    class FakeBookClient(FakeClient):
        def get_orderbook(self, *, market_id, outcome):
            return {"bids": [{"PRICE": 400_000}], "asks": [{"PRICE": 440_000}]}

    book_client = FakeBookClient(markets=markets, my_orders={})
    cfg = BotConfig()
    runner = Runner(client=book_client, oracle=oracle, cfg=cfg, bots=[])
    with caplog.at_level(_logging.INFO, logger="agentpit_bots.runner"):
        runner.log_drift()
    drift_lines = [r.message for r in caplog.records if "drift" in r.message]
    assert drift_lines
    assert "market=will-tunisia-win-the-2026-world-cup" in drift_lines[0]


def test_anchor_corrects_local_drift_with_taker_order():
    """When the local YES book has bids resting well above the Polymarket
    target, the anchor tick places a SELL at the target to sweep them down —
    the active local→Polymarket price sync."""
    markets = [
        {
            "market_id": 1,
            "market_state": "ACTIVE",
            "polymarket_yes_token_id": "poly-yes",
            "polymarket_no_token_id": "poly-no",
            "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
        }
    ]
    oracle = FakeOracle({"poly-yes": 0.10})  # target YES = 0.10

    class BookClient(FakeClient):
        def get_orderbook(self, *, market_id, outcome):
            if outcome == "Yes":  # inflated bids 0.30 — way above target
                return {
                    "bids": [{"PRICE": 300_000, "REMAINING_AMOUNT": 200 * 1_000_000}],
                    "asks": [],
                }
            return {"bids": [], "asks": []}

    client = BookClient(markets=markets, my_orders={})
    cfg = BotConfig(mm_correction_tolerance_usd=0.02, mm_correction_max_shares=10_000)
    runner = Runner(
        client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")]
    )
    runner.run_anchor_tick()
    sweeps = [
        p
        for p in client.placed
        if p["side"] == "SELL" and p["outcome"] == "Yes" and p["price"] == "0.1"
    ]
    assert len(sweeps) == 1, client.placed
    assert sweeps[0]["size"] == 200 * 1_000_000  # the excess bid volume above target
