"""A reconcile pass asks the chain for its balances once, and all at once.

It used to ask five times in a row: two CTF reads inside `_ensure_inventory`
to decide whether to mint, the same two again to cap the asks, and a USD read
after that. On the anvil this was written against, an `eth_call` costs 0.001s
and none of it was visible.

Measured against the SKALE node on 2026-08-12, from inside the api container:

    three reads in a row     1583 ms
    the same three together   545 ms

So the pass now takes all three together and keeps them, and
`_ensure_inventory` reads nothing at all — it is handed what the caller
already has.

What these tests pin is the read count and the handing-over. They do NOT
assert that the three run concurrently: a timing assertion would be flaky in
CI and would prove nothing about a real chain anyway. That was verified on
production instead — five runs of three parallel reads returned numbers
identical to the sequential ones, which is also what showed a shared web3
client is safe to use from several threads at once.
"""
from agentpit.config import Settings
from agentpit.liquidity.reconciler import _ensure_inventory, _read_balances
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
    does — what is being removed is round trips, so the test counts them."""

    def __init__(self, held: int = 0, usd: int = 0):
        self._held = held
        self._usd = usd
        self.ctf_reads = 0
        self.usd_reads = 0
        self.splits = 0

    def ctf_balance(self, _addr: str, _tok: int) -> int:
        self.ctf_reads += 1
        return self._held

    def usd_balance(self, _addr: str) -> int:
        self.usd_reads += 1
        return self._usd

    def user_split_position(self, _key, _cond, add) -> None:
        self.splits += 1
        self._held += add


def _snap():
    """A book that requires inventory: `split_target_micro` reads the asks."""
    return BookSnapshot(
        asset_id="pm-yes", bids=((400_000, 10),), asks=((600_000, 5),)
    )


def test_a_pass_reads_each_balance_exactly_once():
    oc = _CountingOnchain(held=7, usd=9)

    held, usd = _read_balances(oc, _User(), _Ref())  # type: ignore[arg-type]

    assert held == {"111": 7, "222": 7}
    assert usd == 9
    assert (oc.ctf_reads, oc.usd_reads) == (2, 1)


def test_deciding_whether_to_mint_costs_no_round_trip():
    # The whole point of passing `held` in. If this ever reads again, the pass
    # is back to paying twice for the same two numbers.
    oc = _CountingOnchain()

    splits = _ensure_inventory(  # type: ignore[arg-type]
        oc, _User(), _Ref(), _snap(), Settings(), {"111": 10**18, "222": 10**18}
    )

    assert splits == 0
    assert (oc.ctf_reads, oc.usd_reads) == (0, 0)


def test_a_book_needing_nothing_does_not_mint():
    # No asks means no inventory requirement, so nothing is minted however
    # empty the house is.
    oc = _CountingOnchain()
    empty = BookSnapshot(asset_id="pm-yes", bids=(), asks=())

    splits = _ensure_inventory(  # type: ignore[arg-type]
        oc, _User(), _Ref(), empty, Settings(), {"111": 0, "222": 0}
    )

    assert splits == 0
    assert oc.splits == 0


def test_an_empty_house_mints_against_the_requirement():
    # And the caller is told so by the return value, which is its signal that
    # the balances it holds are now stale.
    oc = _CountingOnchain()

    splits = _ensure_inventory(  # type: ignore[arg-type]
        oc, _User(), _Ref(), _snap(), Settings(), {"111": 0, "222": 0}
    )

    assert splits == 1
    assert oc.splits == 1
