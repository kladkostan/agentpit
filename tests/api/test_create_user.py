from fastapi.testclient import TestClient

from agentpit.api.main import app as _app


def test_create_user():
    with TestClient(_app) as client:
        payload = {"user_id": "alice"}
        resp = client.post("/create_user", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "alice"
        assert body["api_key"]  # non-empty UUID
        assert body["eth_address"]  # non-empty ETH address
        assert body["eth_address"].startswith("0x")


def test_create_user_duplicate():
    with TestClient(_app) as client:
        payload = {"user_id": "bob"}
        resp = client.post("/create_user", json=payload)
        assert resp.status_code == 200

        # Same user_id again should 409
        resp2 = client.post("/create_user", json=payload)
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"]


def test_create_user_invalid_handle():
    with TestClient(_app) as client:
        # Too long (>15 chars)
        resp = client.post("/create_user", json={"user_id": "a" * 16})
        assert resp.status_code == 400  # check_state raises

        # Empty string
        resp2 = client.post("/create_user", json={"user_id": ""})
        assert resp2.status_code == 400

        # Invalid characters
        resp3 = client.post("/create_user", json={"user_id": "no spaces!"})
        assert resp3.status_code == 400


def test_create_user_missing_field():
    with TestClient(_app) as client:
        resp = client.post("/create_user", json={})
        assert resp.status_code == 422


def test_create_multiple_users_unique_keys():
    with TestClient(_app) as client:
        api_keys = []
        eth_addresses = []
        for name in ["user1", "user2", "user3"]:
            resp = client.post("/create_user", json={"user_id": name})
            assert resp.status_code == 200
            body = resp.json()
            api_keys.append(body["api_key"])
            eth_addresses.append(body["eth_address"])

        # All API keys and ETH addresses should be unique
        assert len(set(api_keys)) == 3
        assert len(set(eth_addresses)) == 3

