from fastapi.testclient import TestClient

from agentpit.fastapi import main


def test_read_root_returns_version():
    with TestClient(main.server) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json() == {"version": "1.0"}


def test_create_and_get_market():
    with TestClient(main.server) as client:
        # First create a market
        payload = {
            "question": "Will it snow today?",
            "description": "Weather prediction market",
            "erc155_tokens": [["1", "Yes"], ["2", "No"]],
        }
        create_resp = client.post("/markets", json=payload)
        assert create_resp.status_code == 200
        created_market = create_resp.json()
        market_id = created_market["market_id"]

        # Now get the market by ID
        get_resp = client.get(f"/markets/{market_id}")
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["market_id"] == market_id
        assert body["question"] == payload["question"]
        assert body["description"] == payload["description"]
        assert body["erc155_tokens"] == payload["erc155_tokens"]
        assert body["condition_id"] == created_market["condition_id"]
        assert body["market_state"] == "DRAFT"

        # Test getting a non-existent market
        resp = client.get("/markets/9999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Market not found"


def test_mint_usdc():
    with TestClient(main.server) as client:
        payload = {
            "api_key": "test_api_key_123",
            "amount": 1000000,
        }
        resp = client.post("/mint_usdc", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["eth_address"]  # ETH address is generated
        assert body["amount"] == payload["amount"]
        assert body["new_balance"] == payload["amount"]

        # Mint again to the same API key
        payload2 = {
            "api_key": "test_api_key_123",
            "amount": 500000,
        }
        resp2 = client.post("/mint_usdc", json=payload2)
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["eth_address"] == body["eth_address"]  # Same address
        assert body2["amount"] == payload2["amount"]
        assert body2["new_balance"] == payload["amount"] + payload2["amount"]



