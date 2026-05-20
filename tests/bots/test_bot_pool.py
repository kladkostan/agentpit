"""BotPool — bootstrap registers bots, persists creds, splits inventory."""

import json
import threading
import time
from pathlib import Path

from agentpit_bots.bot_pool import BotPool, BotRole
from agentpit_bots.client import BotCredentials
from agentpit_bots.config import SHARES_SCALE


class FakeClient:
    def __init__(self):
        self.registered: list[tuple[str, str]] = []
        self.marked: list[str] = []
        self.split: list[tuple[str, int, int]] = []
        # token -> get_portfolio response. Default (missing) = no positions,
        # so a fresh bot is provisioned across every market.
        self.portfolios: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._next_eth = iter(["0xa1", "0xa2", "0xa3", "0xa4"])

    def register(self, *, email, password):
        self.registered.append((email, password))
        addr = next(self._next_eth)
        return BotCredentials(token=f"tok-{addr}", eth_address=addr)

    def mark_bot(self, *, eth_address):
        self.marked.append(eth_address)
        return {"eth_address": eth_address, "is_bot": True}

    def get_portfolio(self, *, token, market_id=None):
        return self.portfolios.get(token, {"positions": []})

    def split_position(self, *, token, market_id, amount):
        # Provisioning runs one thread per bot, so guard the shared list.
        with self._lock:
            self.split.append((token, market_id, amount))
        return {}


def _full_set(market_id: int, shares: int) -> list[dict]:
    """Both outcome tokens of `market_id` held at `shares` display shares."""
    raw = shares * SHARES_SCALE
    return [
        {"market_id": market_id, "token_id": "y", "balance": raw},
        {"market_id": market_id, "token_id": "n", "balance": raw},
    ]


def test_bootstrap_registers_anchor_and_noise_bots(tmp_path: Path):
    creds = tmp_path / "creds.json"
    client = FakeClient()
    pool = BotPool(
        client=client,
        creds_path=str(creds),
        anchor_pool_size=1,
        noise_pool_size=2,
    )
    bots = pool.ensure_provisioned(market_ids_for_inventory=[])
    assert len(bots) == 3
    assert [b.role for b in bots] == [BotRole.ANCHOR, BotRole.NOISE, BotRole.NOISE]
    # Every bot was marked.
    assert set(client.marked) == {b.creds.eth_address for b in bots}
    # creds.json persisted.
    saved = json.loads(creds.read_text())
    assert len(saved) == 3


def test_bootstrap_is_idempotent_via_creds_file(tmp_path: Path):
    creds = tmp_path / "creds.json"
    creds.write_text(
        json.dumps(
            [
                {
                    "name": "anchor-0",
                    "role": "ANCHOR",
                    "token": "tok-existing",
                    "eth_address": "0xexisting",
                    "email": "x@x",
                },
            ]
        )
    )
    client = FakeClient()
    pool = BotPool(
        client=client,
        creds_path=str(creds),
        anchor_pool_size=1,
        noise_pool_size=0,
    )
    bots = pool.ensure_provisioned(market_ids_for_inventory=[])
    # No new registrations because the only required bot already exists.
    assert client.registered == []
    assert len(bots) == 1
    assert bots[0].creds.eth_address == "0xexisting"


def test_anchor_and_noise_both_get_inventory_with_different_sizes(tmp_path: Path):
    """Anchor needs deep inventory to quote both sides on every market; noise
    needs only a small float so its SELL picks can fire. Both pre-fund at
    bootstrap to unblock the ask side for noise bots that would otherwise
    never acquire outcome tokens (their resting BUYs don't cross the anchor)."""
    creds = tmp_path / "creds.json"
    client = FakeClient()
    pool = BotPool(
        client=client,
        creds_path=str(creds),
        anchor_pool_size=1,
        noise_pool_size=1,
        inventory_split_shares=500,
        noise_inventory_split_shares=100,
    )
    pool.ensure_provisioned(market_ids_for_inventory=[7, 11])
    # 500 shares for anchor (tok-0xa1), 100 shares for noise (tok-0xa2), one
    # split per (bot, market). Bots are provisioned on separate threads, so
    # cross-bot ordering is not deterministic — but each bot still walks
    # market_ids_for_inventory in order.
    anchor_splits = [s for s in client.split if s[0] == "tok-0xa1"]
    noise_splits = [s for s in client.split if s[0] == "tok-0xa2"]
    assert anchor_splits == [
        ("tok-0xa1", 7, 500 * 1_000_000),
        ("tok-0xa1", 11, 500 * 1_000_000),
    ]
    assert noise_splits == [
        ("tok-0xa2", 7, 100 * 1_000_000),
        ("tok-0xa2", 11, 100 * 1_000_000),
    ]
    assert len(client.split) == 4


def test_noise_skipped_when_noise_inventory_zero(tmp_path: Path):
    """Opt out of noise pre-funding by passing 0 — keeps the legacy behavior
    for callers who don't want the bootstrap on-chain cost."""
    creds = tmp_path / "creds.json"
    client = FakeClient()
    pool = BotPool(
        client=client,
        creds_path=str(creds),
        anchor_pool_size=1,
        noise_pool_size=1,
        inventory_split_shares=500,
        noise_inventory_split_shares=0,
    )
    pool.ensure_provisioned(market_ids_for_inventory=[7, 11])
    # Only anchor splits.
    assert client.split == [
        ("tok-0xa1", 7, 500 * 1_000_000),
        ("tok-0xa1", 11, 500 * 1_000_000),
    ]


def test_skips_markets_already_funded_to_target(tmp_path: Path):
    """Idempotency: a bot that already holds a complete set at/above the
    target in a market is not re-split there — only unfunded markets are."""
    creds = tmp_path / "creds.json"
    client = FakeClient()
    # Anchor (tok-0xa1) already holds 500/500 in market 7 from a prior run.
    client.portfolios["tok-0xa1"] = {"positions": _full_set(7, 500)}
    pool = BotPool(
        client=client,
        creds_path=str(creds),
        anchor_pool_size=1,
        noise_pool_size=0,
        inventory_split_shares=500,
    )
    pool.ensure_provisioned(market_ids_for_inventory=[7, 11])
    # Market 7 is satisfied → skipped; only the empty market 11 is split.
    assert client.split == [("tok-0xa1", 11, 500 * 1_000_000)]


def test_resplits_market_below_target(tmp_path: Path):
    """A market holding less than the target on either side is topped up."""
    creds = tmp_path / "creds.json"
    client = FakeClient()
    # Only 100/100 in market 7, target is 500 → still needs a split.
    client.portfolios["tok-0xa1"] = {"positions": _full_set(7, 100)}
    pool = BotPool(
        client=client,
        creds_path=str(creds),
        anchor_pool_size=1,
        noise_pool_size=0,
        inventory_split_shares=500,
    )
    pool.ensure_provisioned(market_ids_for_inventory=[7])
    assert client.split == [("tok-0xa1", 7, 500 * 1_000_000)]


def test_resplits_market_missing_one_side(tmp_path: Path):
    """Holding only one outcome token (the other depleted to 0) is not a
    complete set, so the market is re-provisioned."""
    creds = tmp_path / "creds.json"
    client = FakeClient()
    client.portfolios["tok-0xa1"] = {
        "positions": [
            {"market_id": 7, "token_id": "y", "balance": 500 * SHARES_SCALE},
        ]
    }
    pool = BotPool(
        client=client,
        creds_path=str(creds),
        anchor_pool_size=1,
        noise_pool_size=0,
        inventory_split_shares=500,
    )
    pool.ensure_provisioned(market_ids_for_inventory=[7])
    assert client.split == [("tok-0xa1", 7, 500 * 1_000_000)]


class BarrierFakeClient(FakeClient):
    """Each bot's first split blocks on a barrier sized to the number of
    bots. If provisioning runs the bots concurrently they all reach the
    barrier and proceed; if it runs them sequentially the first bot waits
    alone until the barrier times out and trips ``BrokenBarrierError``."""

    def __init__(self, *, parties: int, timeout: float = 2.0):
        super().__init__()
        self._barrier = threading.Barrier(parties, timeout=timeout)
        self._waited: set[str] = set()

    def split_position(self, *, token, market_id, amount):
        with self._lock:
            first = token not in self._waited
            self._waited.add(token)
        if first:
            self._barrier.wait()  # raises BrokenBarrierError on timeout
        return super().split_position(token=token, market_id=market_id, amount=amount)


def test_bots_provisioned_concurrently(tmp_path: Path):
    """All bots are provisioned in parallel — proven by a barrier that only
    trips when every bot reaches its first split at the same time."""
    creds = tmp_path / "creds.json"
    client = BarrierFakeClient(parties=3)  # 1 anchor + 2 noise
    pool = BotPool(
        client=client,
        creds_path=str(creds),
        anchor_pool_size=1,
        noise_pool_size=2,
        inventory_split_shares=500,
        noise_inventory_split_shares=100,
    )
    pool.ensure_provisioned(market_ids_for_inventory=[7])
    # Every bot got through its split → barrier released → concurrent.
    assert len(client.split) == 3


class ConcurrencyTrackingClient(FakeClient):
    """Records the peak number of splits running simultaneously."""

    def __init__(self):
        super().__init__()
        self.active = 0
        self.peak = 0

    def split_position(self, *, token, market_id, amount):
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.05)  # hold the slot so overlap is observable
        with self._lock:
            self.active -= 1
        return super().split_position(token=token, market_id=market_id, amount=amount)


def test_provisioning_concurrency_is_bounded(tmp_path: Path):
    """Provisioning fans out per bot but never exceeds provision_concurrency
    in flight at once. An unbounded fan-out (one thread per bot) buried the
    single-worker dev server under 31 concurrent on-chain calls and timed out;
    the cap keeps the in-flight on-chain work within what the server serves."""
    creds = tmp_path / "creds.json"
    client = ConcurrencyTrackingClient()
    pool = BotPool(
        client=client,
        creds_path=str(creds),
        anchor_pool_size=1,
        noise_pool_size=3,  # 4 bots all need inventory
        provision_concurrency=2,
    )
    pool.ensure_provisioned(market_ids_for_inventory=[1])
    assert len(client.split) == 4  # every bot still provisioned the market
    assert client.peak == 2  # but never more than the cap ran at once
