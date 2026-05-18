"""Regression test for the shared-connection concurrency bug.

`DbSession.read()` originally used a ReaderWriterLock that allowed multiple
threads to invoke `.execute()` on the same `sqlite3.Connection` at the same
time. SQLite cannot handle concurrent use of one connection across threads
(check_same_thread=False just disables Python's safety check; it does not
make sqlite3 internally thread-safe), and the corruption surfaces as
``sqlite3.InterfaceError: bad parameter or other API misuse``.

This was first observed when the new EventDetailPage fired 30+ parallel
orderbook fetches against a multi-market event.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


def _seed_market(session: DbSession, label: str) -> int:
    req = CreateMarketRequest(
        question=f"q-{label}",
        description=f"d-{label}",
        erc1155_tokens=[(f"{label}-y", "Yes"), (f"{label}-n", "No")],
        slug=f"s-{label}",
        condition_id=ConditionId(_hex32(label)),
        state=MarketState.ACTIVE,
    )
    with session.write() as conn:
        return TableWrite.create_market(conn, req, is_polygon_market=False).market_id


@pytest.fixture()
def session():
    s = DbSession(":memory:")
    yield s
    s.close()


def test_concurrent_reads_do_not_raise_interface_error(session):
    """Hammer the read path from many threads — no sqlite3.InterfaceError."""
    market_ids = [_seed_market(session, f"m{i}") for i in range(8)]

    n_threads = 16
    iterations_per_thread = 30
    barrier = threading.Barrier(n_threads)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def worker(tid: int) -> None:
        barrier.wait()  # maximise contention by starting all threads together
        try:
            for i in range(iterations_per_thread):
                mid = market_ids[(tid + i) % len(market_ids)]
                with session.read() as conn:
                    market = TableRead.read_market(conn, mid)
                    assert market is not None
        except BaseException as exc:  # noqa: BLE001 — capture EVERYTHING
            with errors_lock:
                errors.append(exc)

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        futures = [ex.submit(worker, t) for t in range(n_threads)]
        for f in as_completed(futures):
            f.result()

    assert errors == [], f"concurrent reads raised: {errors[:3]}"
