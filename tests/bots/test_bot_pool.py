"""BotPool — bootstrap registers bots, persists creds, splits inventory."""
import json
from pathlib import Path

from agentpit_bots.bot_pool import BotPool, BotRole
from agentpit_bots.client import BotCredentials


class FakeClient:
    def __init__(self):
        self.registered: list[tuple[str, str]] = []
        self.marked: list[str] = []
        self.split: list[tuple[str, int, int]] = []
        self._next_eth = iter(["0xa1", "0xa2", "0xa3", "0xa4"])

    def register(self, *, email, password):
        self.registered.append((email, password))
        addr = next(self._next_eth)
        return BotCredentials(token=f"tok-{addr}", eth_address=addr)

    def mark_bot(self, *, eth_address):
        self.marked.append(eth_address)
        return {"eth_address": eth_address, "is_bot": True}

    def split_position(self, *, token, market_id, amount):
        self.split.append((token, market_id, amount))
        return {}


def test_bootstrap_registers_anchor_and_noise_bots(tmp_path: Path):
    creds = tmp_path / "creds.json"
    client = FakeClient()
    pool = BotPool(
        client=client, creds_path=str(creds),
        anchor_pool_size=1, noise_pool_size=2,
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
    creds.write_text(json.dumps([
        {"name": "anchor-0", "role": "ANCHOR",
         "token": "tok-existing", "eth_address": "0xexisting", "email": "x@x"},
    ]))
    client = FakeClient()
    pool = BotPool(
        client=client, creds_path=str(creds),
        anchor_pool_size=1, noise_pool_size=0,
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
        client=client, creds_path=str(creds),
        anchor_pool_size=1, noise_pool_size=1,
        inventory_split_shares=500,
        noise_inventory_split_shares=100,
    )
    pool.ensure_provisioned(market_ids_for_inventory=[7, 11])
    # 500 shares for anchor (tok-0xa1), 100 shares for noise (tok-0xa2),
    # one split per (bot, market). Order within each bot is the iteration
    # order of market_ids_for_inventory.
    assert client.split == [
        ("tok-0xa1", 7, 500 * 1_000_000),
        ("tok-0xa1", 11, 500 * 1_000_000),
        ("tok-0xa2", 7, 100 * 1_000_000),
        ("tok-0xa2", 11, 100 * 1_000_000),
    ]


def test_noise_skipped_when_noise_inventory_zero(tmp_path: Path):
    """Opt out of noise pre-funding by passing 0 — keeps the legacy behavior
    for callers who don't want the bootstrap on-chain cost."""
    creds = tmp_path / "creds.json"
    client = FakeClient()
    pool = BotPool(
        client=client, creds_path=str(creds),
        anchor_pool_size=1, noise_pool_size=1,
        inventory_split_shares=500,
        noise_inventory_split_shares=0,
    )
    pool.ensure_provisioned(market_ids_for_inventory=[7, 11])
    # Only anchor splits.
    assert client.split == [
        ("tok-0xa1", 7, 500 * 1_000_000),
        ("tok-0xa1", 11, 500 * 1_000_000),
    ]
