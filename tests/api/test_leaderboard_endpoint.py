from fastapi.testclient import TestClient

from agentpit.api.deps import get_account_service, get_onchain_admin
from agentpit.api.main import app


def test_leaderboard_is_public():
    """No key needed: it is a public board, like /positions and /value."""
    with TestClient(app) as client:
        assert client.get("/leaderboard").status_code == 200


def test_no_email_appears_in_the_payload():
    """Nobody is put on a public board under the address they signed up with.
    Asserted against the raw body so a nested field cannot slip one through."""
    with TestClient(app) as client:
        body = client.get("/leaderboard").text
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
    200 -- proving build_board() never calls onchain or accounts."""
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
