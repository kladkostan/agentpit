"""GET/POST /me/top-up.

The arithmetic (topup_amount_raw, next_allowed_at, the atomic claim) is
covered by tests/test_balance_topup.py. This file covers the HTTP layer:
auth gates, route registration, and the GET side's read-only contract.
"""

from fastapi.testclient import TestClient

from agentpit.api.deps import get_db_session, get_onchain_admin
from agentpit.api.main import app
from agentpit.db.table_read import TableRead


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_top_up_requires_auth():
    with TestClient(app) as client:
        assert client.post("/me/top-up").status_code in (401, 403)


def test_top_up_status_requires_auth():
    with TestClient(app) as client:
        assert client.get("/me/top-up").status_code in (401, 403)


def test_top_up_route_exists():
    """Registered at all — the route table is the thing under test here; the
    arithmetic is covered by tests/test_balance_topup.py."""
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/me/top-up" in paths


class _FakeOnchain:
    """Records every mint_to call so the test can assert none happened."""

    def __init__(self):
        self.mints: list[tuple[str, int]] = []

    def usd_balance(self, address: str) -> int:
        raise AssertionError("GET /me/top-up must not call the chain at all")

    def mint_to(self, recipient: str, amount_raw: int, *, timeout: int = 30):
        self.mints.append((recipient, amount_raw))


def test_top_up_status_does_not_mint_or_touch_last_topup_at():
    with TestClient(app) as client:
        reg = client.post(
            "/register",
            json={"email": "topup-get@example.com", "password": "hunter22hunter22"},
        ).json()
        token = reg["access_token"]
        user_id = reg["user"]["user_id"]

        fake = _FakeOnchain()
        previous = app.dependency_overrides.get(get_onchain_admin)
        app.dependency_overrides[get_onchain_admin] = lambda: fake
        try:
            resp = client.get("/me/top-up", headers=_hdr(token))
        finally:
            if previous is None:
                app.dependency_overrides.pop(get_onchain_admin, None)
            else:
                app.dependency_overrides[get_onchain_admin] = previous

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"nextAllowedAt": 0}
        assert fake.mints == []

    # Confirm LAST_TOPUP_AT was never written, via the same session the app used.
    session = app.dependency_overrides[get_db_session]()
    with session.read() as conn:
        assert TableRead.get_last_topup_at(conn, user_id) is None
