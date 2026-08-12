"""Auth + onboarding flow tests.

The three legacy doors -- `/register`, `/login`, `/auth/google` -- answer 410
since the cutover, and the tests that proved they worked have been inverted or
deleted. What is left is the two credentials that survive it: an AuthKit
bearer token, and the `X-API-Key` header every trading bot uses.

Anvil + the deployed exchange must be running — a first sign-in hits the
faucet and grants approvals as part of creating the account.
"""

import re

from fastapi.testclient import TestClient

from agentpit.api.main import app
from agentpit.db.table_read import TableRead


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ----- the doors that closed --------------------------------------------


def test_register_is_gone():
    with TestClient(app) as client:
        resp = client.post(
            "/register",
            json={"email": "x@example.com", "password": "hunter22hunter22"},
        )
    assert resp.status_code == 410, resp.text
    assert "mailed code" in resp.text


def test_login_is_gone():
    with TestClient(app) as client:
        resp = client.post(
            "/login",
            json={"email": "x@example.com", "password": "hunter22hunter22"},
        )
    assert resp.status_code == 410, resp.text


def test_nothing_reads_a_password_hash_any_more(monkeypatch):
    # The spec's plainest requirement, and the cheapest way to hold it: make
    # reading a hash raise, then drive the two paths that used to. A row's
    # PASSWORD_HASH survives the cutover as a rollback path and must simply go
    # unread until plan 4 drops the column.
    def _boom(*_args, **_kwargs):
        raise AssertionError("PASSWORD_HASH was read after the cutover")

    monkeypatch.setattr(TableRead, "get_password_hash_by_userid", _boom)

    with TestClient(app) as client:
        assert client.post(
            "/login", json={"email": "x@example.com", "password": "hunter22hunter22"}
        ).status_code == 410
        assert client.post(
            "/register",
            json={"email": "y@example.com", "password": "hunter22hunter22"},
        ).status_code == 410


# ----- the bearer token that replaced them ------------------------------


def test_me_requires_bearer_token():
    with TestClient(app) as client:
        assert client.get("/me").status_code == 401


def test_me_returns_current_user(sign_in):
    with TestClient(app) as client:
        token = sign_in(client, "eve@example.com")["access_token"]
        resp = client.get("/me", headers=_hdr(token))
        assert resp.status_code == 200
        assert resp.json()["email"] == "eve@example.com"


def test_me_rejects_invalid_token():
    with TestClient(app) as client:
        resp = client.get("/me", headers=_hdr("not.a.real.jwt"))
        assert resp.status_code == 401


def test_patch_me_updates_handle(sign_in):
    with TestClient(app) as client:
        token = sign_in(client, "frank@example.com")["access_token"]
        resp = client.patch("/me", headers=_hdr(token), json={"handle": "frank_1"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["handle"] == "frank_1"


def test_patch_me_rejects_duplicate_handle(sign_in):
    with TestClient(app) as client:
        first = sign_in(client, "grace@example.com")["access_token"]
        client.patch("/me", headers=_hdr(first), json={"handle": "grace"})
        second = sign_in(client, "heidi@example.com")["access_token"]

        resp = client.patch("/me", headers=_hdr(second), json={"handle": "grace"})
        assert resp.status_code == 409


def test_patch_me_rejects_invalid_handle_format(sign_in):
    with TestClient(app) as client:
        token = sign_in(client, "ivan@example.com")["access_token"]
        resp = client.patch("/me", headers=_hdr(token), json={"handle": "not valid"})
        assert resp.status_code == 422


def test_changing_a_password_on_a_mailed_code_account_is_refused(sign_in):
    """Nobody signing in today has a password to change.

    `change_password` refuses any row with a null PASSWORD_HASH, which is
    every account created since the cutover -- and it does so with the wrong
    reason, "this account signs in with Google", because a null hash used to
    mean exactly that. Pinned rather than fixed: the route survives only so
    that reverting the cutover commit restores a working legacy sign-in, and
    plan 4 deletes it. This test is where a decision to fix the wording
    instead should land.
    """
    with TestClient(app) as client:
        token = sign_in(client, "judy@example.com")["access_token"]
        resp = client.patch(
            "/me/password",
            headers=_hdr(token),
            json={
                "current_password": "hunter22hunter22",
                "new_password": "newhunter22hunter22",
            },
        )
        assert resp.status_code == 400, resp.text


# ----- X-API-Key, which the cutover does not touch ----------------------


def test_signing_in_exposes_an_api_key(sign_in):
    # The bot credential is minted by the account, not by the door it came
    # through, so the mailed-code path has to hand one back the way /register
    # did.
    with TestClient(app) as client:
        body = sign_in(client, "apikey@example.com")
        assert body["user"]["api_key"]


def test_me_accepts_api_key_header(sign_in):
    # The credential every bot trading today authenticates with. Nothing about
    # it moved to WorkOS, and if one assertion in this file survives, it is
    # this one.
    with TestClient(app) as client:
        api_key = sign_in(client, "akauth@example.com")["user"]["api_key"]
        resp = client.get("/me", headers={"X-API-Key": api_key})
        assert resp.status_code == 200, resp.text
        assert resp.json()["email"] == "akauth@example.com"


def test_me_rejects_invalid_api_key():
    with TestClient(app) as client:
        resp = client.get("/me", headers={"X-API-Key": "nope-not-a-key"})
        assert resp.status_code == 401


def test_signing_in_without_a_handle_generates_one(sign_in):
    """A leaderboard of accounts that never set a handle is a column of hex
    strings. The generated name is a starting point -- PATCH /me still
    changes it -- but nobody starts nameless. There is no signup form to type
    one into any more, so generation is the only source there is."""
    with TestClient(app) as client:
        handle = sign_in(client, "nameless@example.com")["user"]["handle"]
        assert handle, "signing in must not leave the handle blank"
        assert re.fullmatch(r"[a-zA-Z0-9_]{1,15}", handle), handle
