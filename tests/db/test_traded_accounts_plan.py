"""`list_traded_accounts` excludes the mirror tape, and that changes nothing.

The exclusion is a performance fix wearing a semantic no-op's clothes, so what
these tests guard is the "no-op" half: a hint that changes an answer is a bug.

## What the fix was for, measured on production 2026-08-12

`trades` there is 523,000 rows and 99.76% of them are the liquidity mirror's
synthetic tape, all under the single api key `MIRROR_API_KEY`. So
`TAKER_API_KEY` had six distinct values across half a million rows, and from
that the planner concluded any given key matches ~87,000 of them -- meaning an
`EXISTS` would stop on its first row and a sequential scan would be nearly free.

It did not stop. The accounts being probed have no trades at all, so each of
the thirty probes per request read the table to the end:

    Seq Scan on users  (rows=6)                       3258 ms
      SubPlan 1 -> Seq Scan on trades  x18 loops
      SubPlan 2 -> Seq Scan on trades  x12 loops
      Buffers: shared read=1032046

Adding `<> MIRROR_API_KEY` removes the value that dominates the statistics, the
estimate becomes accurate, and the indexes the query was written for are used:

    Index Scan using users_pkey  (rows=6)             0.518 ms
      SubPlan 1 -> Index Scan using idx_trades_taker_api_key  x18
      SubPlan 3 -> Index Scan using idx_trades_maker_api_key  x12
      Buffers: shared hit=82 read=16

3258ms -> 0.518ms, and a million block reads -> sixteen.

## Why there is no test asserting the plan

There was one, briefly. It cannot be made honest: which plan Postgres picks
depends on the size of BOTH tables, and the isolated test database is truncated
between tests, so `users` holds a row or two and a sequential scan of `trades`
is genuinely the cheaper plan. Measured while trying: at 2,000, 5,000 and
20,000 tape rows the planner still chose -- correctly -- to scan. Reproducing
the crossover would mean fixtures of a size no unit test should carry.

A plan assertion that passes because the fixture is small is not coverage, it
is a green light with nothing behind it. The regression is guarded by the
comment on `TableRead.TRADED_ACCOUNTS_SQL` and by these correctness tests; if
somebody removes the predicate as "dead weight", nothing here will fail, and
that is stated plainly rather than papered over.
"""
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.liquidity.tape import MIRROR_API_KEY


def _add_tape(conn, count: int) -> None:
    """Rows shaped like the mirror's own: all under the one opaque key."""
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MAKER_API_KEY, "
        "MATCH_TIME, STATUS) SELECT 'tape-'||g, %s, %s, 1700000000+g, 'MATCHED' "
        "FROM generate_series(1, %s) g",
        (MIRROR_API_KEY, MIRROR_API_KEY, count),
    )


def test_excluding_the_tape_cannot_change_who_is_on_the_board():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        user_id, _acct, api_key = TableWrite.create_user(
            conn, email="trader@example.com", password_hash=None, handle=None
        )
        conn.execute(
            "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME, STATUS) "
            "VALUES ('real-1', %s, 1700000000, 'MATCHED')",
            (api_key,),
        )
        _add_tape(conn, 50)

    with db.read() as conn:
        accounts = TableRead.list_traded_accounts(conn)

    assert [a.user_id for a in accounts] == [user_id]


def test_a_maker_side_trade_still_counts():
    # The second `EXISTS` carries the same predicate as the first, and a
    # copy-paste that fixed one and not the other would drop every account
    # that has only ever been the maker.
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        user_id, _acct, api_key = TableWrite.create_user(
            conn, email="maker@example.com", password_hash=None, handle=None
        )
        conn.execute(
            "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MAKER_API_KEY, "
            "MATCH_TIME, STATUS) VALUES ('real-2', 'someone-else', %s, "
            "1700000000, 'MATCHED')",
            (api_key,),
        )
        _add_tape(conn, 50)

    with db.read() as conn:
        accounts = TableRead.list_traded_accounts(conn)

    assert [a.user_id for a in accounts] == [user_id]


def test_an_account_with_only_tape_beside_it_is_not_on_the_board():
    # The tape is nobody's trading history. An account that never traded must
    # stay off the board however much tape sits in the table beside it.
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        TableWrite.create_user(
            conn, email="idle@example.com", password_hash=None, handle=None
        )
        _add_tape(conn, 50)

    with db.read() as conn:
        assert TableRead.list_traded_accounts(conn) == []


def test_a_failed_trade_still_does_not_put_an_account_on_the_board():
    # The status filter predates this change and must survive it: the new
    # predicate sits beside it in the same WHERE, which is exactly where an
    # `AND`/`OR` slip would quietly widen the rule.
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        _uid, _acct, api_key = TableWrite.create_user(
            conn, email="failed@example.com", password_hash=None, handle=None
        )
        conn.execute(
            "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME, STATUS) "
            "VALUES ('failed-1', %s, 1700000000, 'FAILED')",
            (api_key,),
        )

    with db.read() as conn:
        assert TableRead.list_traded_accounts(conn) == []
