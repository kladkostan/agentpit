"""Admin endpoints — guarded by an X-Admin-Token header."""

from fastapi.testclient import TestClient

from agentpit.api.main import app

# AGENTPIT_ADMIN_TOKEN is read at app startup by Settings; tests rely on
# the default ("dev-admin-token") so we don't need to mutate env here.
ADMIN_TOKEN = "dev-admin-token"


def test_mark_bot_requires_admin_token(sign_in):
    with TestClient(app) as client:
        user = sign_in(client, "mark1@example.com")
        resp = client.post(
            "/admin/mark_bot",
            json={"eth_address": user["user"]["eth_address"]},
        )
        assert resp.status_code == 401


def test_mark_bot_flips_is_bot_flag(sign_in):
    with TestClient(app) as client:
        user = sign_in(client, "mark2@example.com")
        resp = client.post(
            "/admin/mark_bot",
            json={"eth_address": user["user"]["eth_address"]},
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "eth_address": user["user"]["eth_address"],
            "is_bot": True,
        }


def test_mark_bot_unknown_address_404():
    with TestClient(app) as client:
        resp = client.post(
            "/admin/mark_bot",
            json={"eth_address": "0x0000000000000000000000000000000000000000"},
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
        assert resp.status_code == 404
