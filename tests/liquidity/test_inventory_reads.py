"""`_ensure_inventory` hands back what it read, so the pass reads it once.

Every reconcile pass used to ask the chain for the same two CTF balances
twice: once inside `_ensure_inventory` to decide whether to mint, and again
immediately after to cap the asks. On the anvil this was written against that
cost nothing measurable. Measured against the SKALE node on 2026-08-12 a
single `eth_call` round trip is **0.53s**, versus **0.001s** to a local anvil
— 530x — so the duplicate pair was most of a pass's wall clock, and the
mirror seeded roughly four markets a minute.

These tests pin the contract that removes it: the function returns the
holdings it read, and returns None exactly when it has nothing honest to
offer. What they deliberately do NOT assert is the read count through
`reconcile_market` itself — that needs a live OrderService placing orders
against a database, and a test built on that much scaffolding tends to pin
the scaffolding. The reuse is one `if held is None` in the caller; the
measurement that proves it is on production, in the pass timings.
"""
from agentpit.config import Settings
from agentpit.liquidity.reconciler import _ensure_inventory
from agentpit.liquidity.replica import BookSnapshot


class _Ref:
    # Numeric strings: the reconciler takes `int(ref.yes_token)` to call the
    # ERC-1155 balance, so a readable label like "tok-yes" would fail on a
    # cast rather than on anything this test is about.
    market_id = 1
    condition_id = "0x" + "ab" * 32
    yes_token = "111"
    no_token = "222"


class _User:
    eth_address = "0xabc"
    eth_key = "0xkey"


class _CountingOnchain:
    """Counts chain round trips, the way `tests/services/test_order_balance_hint`
    does — the cost being removed is round trips, so the test counts them."""

    def __init__(self, held: int):
        self._held = held
        self.ctf_reads = 0
        self.splits = 0

    def ctf_balance(self, _addr: str, _tok: int) -> int:
        self.ctf_reads += 1
        return self._held

    def user_split_position(self, _key, _cond, _add) -> None:
        self.splits += 1


def _snap():
    """A book that requires inventory: `split_target_micro` reads the asks."""
    return BookSnapshot(
        asset_id="pm-yes", bids=((400_000, 10),), asks=((600_000, 5),)
    )


def test_a_pass_that_needs_no_mint_hands_its_balances_back():
    # The common case, and the whole point: two reads, and the caller never
    # has to ask again.
    oc = _CountingOnchain(held=10**18)
    splits, held = _ensure_inventory(  # type: ignore[arg-type]
        oc, _User(), _Ref(), _snap(), Settings()
    )

    assert splits == 0
    assert oc.ctf_reads == 2
    assert held == {"111": 10**18, "222": 10**18}


def test_a_book_needing_nothing_reads_nothing_and_promises_nothing():
    # No asks means no inventory requirement, so the function returns before
    # touching the chain. It must NOT hand back a balance it never read --
    # `None` is what sends the caller to fetch its own.
    oc = _CountingOnchain(held=0)
    empty = BookSnapshot(asset_id="pm-yes", bids=(), asks=())
    splits, held = _ensure_inventory(  # type: ignore[arg-type]
        oc, _User(), _Ref(), empty, Settings()
    )

    assert (splits, held) == (0, None)
    assert oc.ctf_reads == 0


def test_after_a_mint_the_numbers_it_read_are_not_offered():
    # A split moves both balances, so what was read before it is stale. The
    # caller must re-read rather than trust arithmetic about a transaction:
    # inventory that reads high backs asks the house cannot cover.
    oc = _CountingOnchain(held=0)
    splits, held = _ensure_inventory(  # type: ignore[arg-type]
        oc, _User(), _Ref(), _snap(), Settings()
    )

    assert splits == 1
    assert oc.splits == 1
    assert held is None
