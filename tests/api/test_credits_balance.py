"""The credit balance is what pays for a transaction. Without it a user can
hold a won position and be unable to claim it.

Anvil + the deployed exchange must be running -- a first sign-in funds the
account's wallet with native gas on chain the same way every other onboarding
test relies on.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from agentpit.api.main import app


@dataclass
class _SignedInUser:
    user_id: str
    eth_address: str
    auth_header: dict


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def signed_in_user(client, sign_in) -> _SignedInUser:
    body = sign_in(client, "creditsbalance@example.com")
    return _SignedInUser(
        user_id=body["user"]["user_id"],
        eth_address=body["user"]["eth_address"],
        auth_header={"Authorization": f"Bearer {body['access_token']}"},
    )


def test_credits_are_reported_as_a_string(client, signed_in_user):
    r = client.get("/me/credits", headers=signed_in_user.auth_header)
    assert r.status_code == 200
    assert isinstance(r.json()["credits_wei"], str)
    # A first sign-in funds the wallet (per this module's docstring) -- assert
    # a real balance, not merely a non-negative one, so a hardcoded "0"
    # can't pass this test.
    assert int(r.json()["credits_wei"]) > 0


def test_credits_need_authentication(client):
    assert client.get("/me/credits").status_code == 401
