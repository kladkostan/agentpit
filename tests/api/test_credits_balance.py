"""The credit balance is what pays for a transaction. Without it a user can
hold a won position and be unable to claim it.

Anvil + the deployed exchange must be running -- registering funds the
account's wallet with native gas on chain the same way every other onboarding
test relies on.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from agentpit.api.main import app


@dataclass
class _RegisteredUser:
    user_id: str
    eth_address: str
    auth_header: dict


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def registered_user(client) -> _RegisteredUser:
    body = client.post(
        "/register",
        json={"email": "creditsbalance@example.com", "password": "hunter22hunter22"},
    ).json()
    return _RegisteredUser(
        user_id=body["user"]["user_id"],
        eth_address=body["user"]["eth_address"],
        auth_header={"Authorization": f"Bearer {body['access_token']}"},
    )


def test_credits_are_reported_as_a_string(client, registered_user):
    r = client.get("/me/credits", headers=registered_user.auth_header)
    assert r.status_code == 200
    assert isinstance(r.json()["credits_wei"], str)
    assert int(r.json()["credits_wei"]) >= 0


def test_credits_need_authentication(client):
    assert client.get("/me/credits").status_code == 401
