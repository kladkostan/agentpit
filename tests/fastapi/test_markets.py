from fastapi.testclient import TestClient

from agentpit.fastapi import main


def test_create_and_get_market():
    with TestClient(main.app) as client:
        # First create a market
        payload = {
            "question": "Will it snow today?",
            "description": "Weather prediction market",
            "erc1155_tokens": [["1", "Yes"], ["2", "No"]],
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
        assert body["erc1155_tokens"] == payload["erc1155_tokens"]
        assert body["condition_id"] == created_market["condition_id"]
        assert body["market_state"] == "DRAFT"

        # Test getting a non-existent market
        resp = client.get("/markets/9999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Market not found"


def test_list_markets():
    with TestClient(main.app) as client:
        # List markets when empty
        resp = client.get("/markets")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["markets"] == []
        assert body["limit"] == 100
        assert body["offset"] == 0

        # Create multiple markets
        for i in range(5):
            payload = {
                "question": f"Question {i}?",
                "description": f"Description {i}",
                "erc1155_tokens": [["1", "Yes"], ["2", "No"]],
            }
            client.post("/markets", json=payload)

        # List all markets
        resp = client.get("/markets")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert len(body["markets"]) == 5
        assert body["limit"] == 100
        assert body["offset"] == 0

        # Test pagination with limit
        resp = client.get("/markets?limit=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert len(body["markets"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0

        # Test pagination with offset
        resp = client.get("/markets?limit=2&offset=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert len(body["markets"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 2

        # Test invalid limit
        resp = client.get("/markets?limit=2000")
        assert resp.status_code == 400
        assert "limit" in resp.json()["detail"].lower()

        # Test invalid offset
        resp = client.get("/markets?offset=-1")
        assert resp.status_code == 400
        assert "offset" in resp.json()["detail"].lower()

