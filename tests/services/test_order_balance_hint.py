"""place_order(balance_hint=...) lets a batch caller (the mirror) supply a
same-cycle cached balance so the per-order on-chain balance read is skipped —
the dominant cost when replicating a deep book."""

import pytest

from agentpit.domain.exceptions import InsufficientBalanceError
from agentpit.services.order_service import OrderService


class _CountingOnchain:
    """Counts on-chain balance reads; returns fixed balances."""

    def __init__(self, usd: int = 1_000, ctf: int = 5) -> None:
        self._usd, self._ctf = usd, ctf
        self.usd_reads = 0
        self.ctf_reads = 0

    def usd_balance(self, _addr: str) -> int:
        self.usd_reads += 1
        return self._usd

    def ctf_balance(self, _addr: str, _tok: int) -> int:
        self.ctf_reads += 1
        return self._ctf


def _svc(oc: _CountingOnchain) -> OrderService:
    return OrderService(db=None, onchain=oc)  # type: ignore[arg-type]


def test_hint_is_used_without_an_on_chain_read():
    oc = _CountingOnchain()
    svc = _svc(oc)
    svc._check_balance("0xabc", "BUY", maker_amount=900, token_id_int=1, balance_hint=1_000)
    svc._check_balance("0xabc", "SELL", maker_amount=4, token_id_int=1, balance_hint=5)
    assert oc.usd_reads == 0 and oc.ctf_reads == 0  # never touched the chain


def test_hint_still_rejects_when_insufficient():
    oc = _CountingOnchain()
    svc = _svc(oc)
    with pytest.raises(InsufficientBalanceError):
        svc._check_balance("0xabc", "BUY", maker_amount=2_000, token_id_int=1, balance_hint=1_000)
    assert oc.usd_reads == 0  # the cap is enforced against the hint, no read


def test_no_hint_falls_back_to_on_chain_read():
    oc = _CountingOnchain()
    svc = _svc(oc)
    svc._check_balance("0xabc", "BUY", maker_amount=500, token_id_int=1)
    svc._check_balance("0xabc", "SELL", maker_amount=3, token_id_int=1)
    assert oc.usd_reads == 1 and oc.ctf_reads == 1  # hint omitted -> read each side
