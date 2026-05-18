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
    def __init__(self, markets, my_orders):
        self._markets = markets
        self._my_orders = my_orders
        self.placed: list[dict] = []
        self.cancelled: list[str] = []

    def get_markets(self):
        return self._markets

    def list_my_orders(self, *, token):
        return list(self._my_orders.get(token, []))

    def place_order(self, *, token, market_id, outcome, side, price, size):
        self.placed.append({
            "token": token, "market_id": market_id, "outcome": outcome,
            "side": side, "price": price, "size": size,
        })
        return {"orderID": f"new-{len(self.placed)}", "status": "live",
                "success": True, "filledSize": "0", "remainingSize": str(size)}

    def cancel_order(self, *, token, order_id):
        self.cancelled.append(order_id)
        return {"order_id": order_id, "status": "cancelled"}


def _bot(name, role):
    return Bot(name=name, role=BotRole(role),
               creds=BotCredentials(token=f"tok-{name}", eth_address=f"0x{name}"))


def test_runner_tick_places_anchor_quotes():
    markets = [{
        "market_id": 1, "market_state": "ACTIVE",
        "polymarket_yes_token_id": "poly-yes",
        "polymarket_no_token_id": "poly-no",
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    oracle = FakeOracle({"poly-yes": 0.50})
    client = FakeClient(markets=markets, my_orders={})
    bots = [_bot("anchor-0", "ANCHOR")]
    cfg = BotConfig(mm_half_spread_usd=0.01, mm_quote_size_shares=100)
    runner = Runner(client=client, oracle=oracle, cfg=cfg, bots=bots)

    runner.run_anchor_tick()

    # Four orders posted: YES BUY, YES SELL, NO BUY, NO SELL.
    assert len(client.placed) == 4
    yes_buy = next(p for p in client.placed if p["side"] == "BUY" and p["outcome"] == "Yes")
    yes_sell = next(p for p in client.placed if p["side"] == "SELL" and p["outcome"] == "Yes")
    assert yes_buy["price"] == "0.49"
    assert yes_sell["price"] == "0.51"


def test_runner_skips_markets_without_upstream_token_ids():
    markets = [{
        "market_id": 1, "market_state": "ACTIVE",
        "polymarket_yes_token_id": None,
        "polymarket_no_token_id": None,
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    oracle = FakeOracle({})
    client = FakeClient(markets=markets, my_orders={})
    cfg = BotConfig()
    runner = Runner(client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")])
    runner.run_anchor_tick()
    assert client.placed == []


def test_runner_noise_tick_emits_one_order_per_noise_bot():
    markets = [{
        "market_id": 1, "market_state": "ACTIVE",
        "polymarket_yes_token_id": "poly-yes",
        "polymarket_no_token_id": "poly-no",
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    oracle = FakeOracle({"poly-yes": 0.5})
    client = FakeClient(markets=markets, my_orders={})
    cfg = BotConfig()
    bots = [_bot("noise-0", "NOISE"), _bot("noise-1", "NOISE")]
    runner = Runner(client=client, oracle=oracle, cfg=cfg, bots=bots,
                    rng=random.Random(0))
    runner.run_noise_tick()
    assert len(client.placed) == 2  # one per noise bot


def test_runner_disabled_market_skipped():
    markets = [{
        "market_id": 99, "market_state": "ACTIVE",
        "polymarket_yes_token_id": "poly-yes",
        "polymarket_no_token_id": "poly-no",
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    cfg = BotConfig(disabled_market_ids=frozenset({99}))
    client = FakeClient(markets=markets, my_orders={})
    oracle = FakeOracle({"poly-yes": 0.5})
    runner = Runner(client=client, oracle=oracle, cfg=cfg,
                    bots=[_bot("anchor-0", "ANCHOR")])
    runner.run_anchor_tick()
    assert client.placed == []


class FakeClientWithPortfolio(FakeClient):
    def __init__(self, markets, my_orders, portfolio):
        super().__init__(markets, my_orders)
        self._portfolio = portfolio
        self.merged: list[tuple[int, int]] = []
        self.split: list[tuple[int, int]] = []

    def get_portfolio(self, *, token):
        return self._portfolio

    def merge_positions(self, *, token, market_id, amount):
        self.merged.append((market_id, amount))
        return {}

    def split_position(self, *, token, market_id, amount):
        self.split.append((market_id, amount))
        return {}


def test_rebalance_merges_when_both_sides_have_surplus():
    markets = [{
        "market_id": 1, "market_state": "ACTIVE",
        "polymarket_yes_token_id": "poly-yes",
        "polymarket_no_token_id": "poly-no",
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    portfolio = {
        "usdc_balance": 5000,
        "positions": [
            {"market_id": 1, "token_id": "local-yes", "balance": 800 * 1_000_000},
            {"market_id": 1, "token_id": "local-no",  "balance": 700 * 1_000_000},
        ],
    }
    cfg = BotConfig(mm_rebalance_floor_shares=200)
    oracle = FakeOracle({"poly-yes": 0.5})
    client = FakeClientWithPortfolio(markets=markets, my_orders={}, portfolio=portfolio)
    runner = Runner(client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")])
    runner.run_rebalance_tick()
    # min(yes, no) = 700; surplus = 700 - 200 = 500 → merge 500.
    assert client.merged == [(1, 500)]


def test_split_when_one_side_depleted():
    markets = [{
        "market_id": 1, "market_state": "ACTIVE",
        "polymarket_yes_token_id": "poly-yes",
        "polymarket_no_token_id": "poly-no",
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    portfolio = {
        "usdc_balance": 5000,
        "positions": [
            {"market_id": 1, "token_id": "local-yes", "balance": 50 * 1_000_000},
            {"market_id": 1, "token_id": "local-no",  "balance": 5 * 1_000_000},   # depleted
        ],
    }
    cfg = BotConfig(mm_quote_size_shares=100)
    oracle = FakeOracle({"poly-yes": 0.5})
    client = FakeClientWithPortfolio(markets=markets, my_orders={}, portfolio=portfolio)
    runner = Runner(client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")])
    runner.run_rebalance_tick()
    # min(yes, no) = 5 < quote_size 100 → re-split a complete set of quote_size.
    assert client.split == [(1, 100)]
