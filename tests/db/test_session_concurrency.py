"""Pool concurrency test for DbSession (Postgres backend).

Verifies that many threads can concurrently read and write through the
connection pool without errors or data inconsistency. The Postgres pool
(psycopg_pool) hands each thread its own connection, so there is no
shared-state hazard as there was with the old sqlite3 single-connection
approach.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from tests.db_helpers import fresh_test_db


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


def _seed_market(session, label: str) -> int:
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


def test_pool_concurrent_reads_and_writes_do_not_raise():
    """20 threads concurrently read existing markets and write new ones; no
    exceptions and all inserted markets are visible to subsequent reads.

    Writes are serialized through a lock because `create_market` computes the
    next ID via MAX()+1 rather than a sequence — that is an app-level constraint
    that the pool itself is not responsible for.  What we are testing here is
    that the pool hands every thread its own connection (no shared-state
    corruption) and that concurrent reads across multiple pool connections are
    stable.
    """
    session = fresh_test_db()
    try:
        # Seed a handful of markets before spawning threads.
        seed_ids = [_seed_market(session, f"seed{i}") for i in range(5)]

        n_threads = 20
        read_barrier = threading.Barrier(n_threads)
        write_lock = threading.Lock()  # serialise writes (MAX()+1 not atomic)
        errors: list[BaseException] = []
        errors_lock = threading.Lock()
        written_ids: list[int] = []

        def worker(tid: int) -> None:
            read_barrier.wait()  # maximise read contention
            try:
                # Concurrent read round across pool connections.
                for mid in seed_ids:
                    with session.read() as conn:
                        market = TableRead.read_market(conn, mid)
                        assert market is not None, (
                            f"thread {tid}: seed market {mid} missing"
                        )

                # Concurrent list round.
                with session.read() as conn:
                    _markets, total = TableRead.list_markets(conn, limit=30)
                    assert total >= len(seed_ids)

                # Sequential write: each thread adds one unique market.
                with write_lock:
                    new_id = _seed_market(session, f"thr{tid}")
                    written_ids.append(new_id)

                # Read back its own write (pool gives a fresh connection).
                with session.read() as conn:
                    created = TableRead.read_market(conn, new_id)
                    assert created is not None, (
                        f"thread {tid}: own write {new_id} not found"
                    )

            except BaseException as exc:  # noqa: BLE001 — capture everything
                with errors_lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=n_threads) as ex:
            futures = [ex.submit(worker, t) for t in range(n_threads)]
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"concurrent pool ops raised: {errors[:3]}"

        # All written markets must now be in the DB.
        assert len(written_ids) == n_threads
        with session.read() as conn:
            _, total = TableRead.list_markets(conn, limit=1)
        assert total >= len(seed_ids) + n_threads

    finally:
        session.close()
