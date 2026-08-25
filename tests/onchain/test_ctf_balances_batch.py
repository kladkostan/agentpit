"""`ctf_balances` is the one call the position scan is allowed to make.

Its contract with the caller is narrow but load-bearing: the answers come
back in the order the tokens were asked for, an empty request costs nothing,
and a long request is split rather than sent whole — a node is entitled to
cap the size of an eth_call reply, and the list grows with how much the
account has traded.
"""

from __future__ import annotations

from agentpit.onchain.admin import _BALANCE_BATCH, OnchainAdmin


class _FakeBatchCall:
    def __init__(self, recorder, owners, ids):
        self._recorder = recorder
        self._owners = owners
        self._ids = ids

    def call(self):
        self._recorder.append((self._owners, self._ids))
        # The chain answers with the balance of each id, in order. Encoding the
        # id in the answer is what lets the caller's zip be checked.
        return [i * 2 for i in self._ids]


class _FakeFunctions:
    def __init__(self, recorder):
        self._recorder = recorder

    def balanceOfBatch(self, owners, ids):  # noqa: N802 - the ABI's own name
        return _FakeBatchCall(self._recorder, owners, ids)


class _FakeContracts:
    def __init__(self, recorder):
        self.ctf = type("_C", (), {"functions": _FakeFunctions(recorder)})()


def _admin(recorder) -> OnchainAdmin:
    return OnchainAdmin(client=None, contracts=_FakeContracts(recorder))  # type: ignore[arg-type]


HOLDER = "0x9D22FB092E79515611e8380026583929F88815b9"


def test_asks_for_every_token_in_one_call():
    calls: list = []
    out = _admin(calls).ctf_balances(HOLDER, [11, 22, 33])

    assert len(calls) == 1
    _owners, ids = calls[0]
    assert ids == [11, 22, 33]
    assert out == [22, 44, 66]


def test_answers_stay_in_the_order_the_tokens_were_asked():
    """The caller zips this list against its own token list, so a reordered
    reply would report a balance against the wrong outcome."""
    calls: list = []
    ids = [98, 3, 47, 12]
    assert _admin(calls).ctf_balances(HOLDER, ids) == [196, 6, 94, 24]


def test_the_holder_is_repeated_once_per_token():
    """balanceOfBatch takes parallel arrays; a shorter owners array reverts."""
    calls: list = []
    _admin(calls).ctf_balances(HOLDER, [1, 2, 3, 4])
    owners, ids = calls[0]
    assert len(owners) == len(ids) == 4
    assert set(owners) == {HOLDER}


def test_an_empty_request_never_reaches_the_chain():
    calls: list = []
    assert _admin(calls).ctf_balances(HOLDER, []) == []
    assert calls == []


def test_a_long_list_is_split_into_chunks():
    calls: list = []
    ids = list(range(1, _BALANCE_BATCH * 2 + 6))
    out = _admin(calls).ctf_balances(HOLDER, ids)

    assert len(calls) == 3
    assert [len(c[1]) for c in calls] == [_BALANCE_BATCH, _BALANCE_BATCH, 5]
    # Split or not, the caller sees one flat list in the original order.
    assert out == [i * 2 for i in ids]


def test_a_list_exactly_one_chunk_long_is_not_split():
    calls: list = []
    _admin(calls).ctf_balances(HOLDER, list(range(_BALANCE_BATCH)))
    assert len(calls) == 1
