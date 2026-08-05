from fastapi.testclient import TestClient

from agentpit.api.deps import get_account_service, get_onchain_admin
from agentpit.api.main import app
from agentpit.db.table_write import TableWrite
from tests.db_helpers import fresh_test_conn


def _seed_traded_account(
    *, handle: str, capital_raw: int, deposited_raw: int, email: str
) -> str:
    """Insert a traded, snapshotted account directly against the test DB, so
    GET /leaderboard has a real row to serve -- the account_snapshots row is
    what makes it survive build_board's `latest.get(account.user_id)` check.
    Returns the account's address."""
    conn = fresh_test_conn()
    user_id, acct, key = TableWrite.create_user(
        conn, email=email, password_hash="x", handle=handle
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s)",
        (f"t-{handle}", key, 1_700_000_000),
    )
    TableWrite.insert_account_snapshot(
        conn, user_id, 1_800_000_000, capital_raw, deposited_raw
    )
    conn.close()
    return acct.address


def test_leaderboard_is_public():
    """No key needed: it is a public board, like /positions and /value."""
    with TestClient(app) as client:
        assert client.get("/leaderboard").status_code == 200


def test_no_email_appears_in_the_payload():
    """Nobody is put on a public board under the address they signed up with.
    Asserted against the raw body so a nested field cannot slip one through.

    Seeded with a real traded, snapshotted account -- an empty board would
    make the "@" assertion trivially true regardless of whether the guarantee
    (no email field on the models; handles are [a-zA-Z0-9_]{1,15}) holds."""
    _seed_traded_account(
        handle="trader1",
        capital_raw=110_000_000_000,
        deposited_raw=100_000_000_000,
        email="trader1@example.com",
    )
    with TestClient(app) as client:
        body = client.get("/leaderboard").text
    assert "trader1" in body, "the row must actually be in the response"
    assert "@" not in body


def test_unknown_sort_falls_back_to_return():
    with TestClient(app) as client:
        assert client.get("/leaderboard?sort=nonsense").json()["sort"] == "return"


class _FakeOnchain:
    """Records nothing -- just raises, so the test can prove GET /leaderboard
    never reaches it. The chain work happens in take_snapshot, on a timer."""

    def usd_balance(self, address: str) -> int:
        raise AssertionError("GET /leaderboard must not call the chain at all")


class _FakeAccounts:
    """total_value also raises on purpose, alongside _FakeOnchain.usd_balance,
    so the endpoint is proven to reach neither collaborator."""

    def total_value(self, address: str) -> list[dict]:
        raise AssertionError("GET /leaderboard must not walk positions on chain")


def test_get_leaderboard_does_not_touch_the_chain():
    """The board is served from the database and a cache; a LeaderboardService
    built with collaborators that raise on any chain read must still answer
    200 with the seeded row -- proving both that build_board() actually ran
    (this is a cache miss: conftest's autouse fixture clears _board_cache
    before every test, so there is nothing to hit) and that it never called
    onchain or accounts. A prior version of this test seeded no data and
    stayed silent about the cache, so it passed even while every request
    after the first was served from a stale cache entry without recomputing
    at all -- proving nothing about the request actually under test."""
    address = _seed_traded_account(
        handle="chain-proof",
        capital_raw=150_000_000_000,
        deposited_raw=100_000_000_000,
        email="chain-proof@example.com",
    )
    with TestClient(app) as client:
        previous_onchain = app.dependency_overrides.get(get_onchain_admin)
        previous_accounts = app.dependency_overrides.get(get_account_service)
        app.dependency_overrides[get_onchain_admin] = lambda: _FakeOnchain()
        app.dependency_overrides[get_account_service] = lambda: _FakeAccounts()
        try:
            resp = client.get("/leaderboard")
        finally:
            if previous_onchain is None:
                app.dependency_overrides.pop(get_onchain_admin, None)
            else:
                app.dependency_overrides[get_onchain_admin] = previous_onchain
            if previous_accounts is None:
                app.dependency_overrides.pop(get_account_service, None)
            else:
                app.dependency_overrides[get_account_service] = previous_accounts

        assert resp.status_code == 200, resp.text
        entries = resp.json()["entries"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["address"] == address
        assert entry["name"] == "chain-proof"
        assert entry["capital"] == "150000000000"
        assert entry["earned"] == "50000000000"
        assert entry["trades"] == 1


def test_history_returns_the_accounts_curve():
    conn = fresh_test_conn()
    user_id, acct, key = TableWrite.create_user(
        conn, email="curve@example.com", password_hash="x", handle="curvy"
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s)",
        ("t-curve", key, 1_700_000_000),
    )
    TableWrite.insert_account_snapshot(
        conn, user_id, 1_800_000_000, 100_000_000_000, 100_000_000_000
    )
    TableWrite.insert_account_snapshot(
        conn, user_id, 1_800_000_300, 150_000_000_000, 100_000_000_000
    )
    conn.close()

    with TestClient(app) as client:
        resp = client.get(f"/leaderboard/{acct.address}/history")

    assert resp.status_code == 200, resp.text
    points = resp.json()["points"]
    assert [p["t"] for p in points] == [1_800_000_000, 1_800_000_300]
    assert points[-1]["capital"] == "150000000000"
    assert points[-1]["earned"] == "50000000000"
    assert points[-1]["returnPct"] == 50.0


def test_history_of_an_unknown_address_is_a_404():
    with TestClient(app) as client:
        resp = client.get("/leaderboard/0x" + "00" * 20 + "/history")
    assert resp.status_code == 404


def test_history_carries_no_email():
    """Same guarantee as the board: nobody's signup address on a public
    endpoint, asserted against the raw body."""
    conn = fresh_test_conn()
    user_id, acct, _key = TableWrite.create_user(
        conn, email="private@example.com", password_hash="x", handle="private1"
    )
    TableWrite.insert_account_snapshot(
        conn, user_id, 1_800_000_000, 1, 1
    )
    conn.close()

    with TestClient(app) as client:
        body = client.get(f"/leaderboard/{acct.address}/history").text
    assert "@" not in body
