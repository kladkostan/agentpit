from fastapi.testclient import TestClient

from agentpit.fastapi import main


def test_read_root_returns_version():
    with TestClient(main.server) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json() == {"version": "1.0"}


def test_create_market():
    with TestClient(main.server) as client:
        payload = {
            "condition_id": "0x" + "1" * 64,
            "description": "Will it rain tomorrow?",
            "erc155_tokens": [["1", "Yes"], ["2", "No"]],
        }
        resp = client.post("/markets", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["market_id"] == 1
        assert body["condition_id"] == payload["condition_id"]
        assert body["description"] == payload["description"]
        assert body["erc155_tokens"] == payload["erc155_tokens"]
        assert body["question"] == payload["description"]
        assert body["market_state"] == "DRAFT"
