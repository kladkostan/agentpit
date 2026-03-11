from fastapi.testclient import TestClient

from agentpit.fastapi import main


def test_create_personality():
    with TestClient(main.app) as client:
        payload = {
            "title": "Contrarian Trader",
            "beliefs": "Markets overreact to news",
            "methods": "Fade large moves and revert to mean",
            "needs": "Real-time sentiment data",
        }
        resp = client.post("/create_personality", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["personality_id"] > 0
        assert body["title"] == payload["title"]
        assert body["spec"]["beliefs"] == payload["beliefs"]
        assert body["spec"]["methods"] == payload["methods"]
        assert body["spec"]["needs"] == payload["needs"]


def test_create_personality_missing_field():
    with TestClient(main.app) as client:
        # Missing 'needs'
        payload = {
            "title": "Incomplete",
            "beliefs": "Something",
            "methods": "Something else",
        }
        resp = client.post("/create_personality", json=payload)
        assert resp.status_code == 422


def test_create_personality_empty_title():
    with TestClient(main.app) as client:
        payload = {
            "title": "",
            "beliefs": "Believe in efficiency",
            "methods": "Arbitrage",
            "needs": "Low latency feeds",
        }
        resp = client.post("/create_personality", json=payload)
        assert resp.status_code == 500  # check_state raises


def test_create_multiple_personalities():
    with TestClient(main.app) as client:
        ids = []
        for i in range(3):
            payload = {
                "title": f"Personality {i}",
                "beliefs": f"Belief {i}",
                "methods": f"Method {i}",
                "needs": f"Need {i}",
            }
            resp = client.post("/create_personality", json=payload)
            assert resp.status_code == 200
            body = resp.json()
            ids.append(body["personality_id"])

        # All IDs should be unique
        assert len(set(ids)) == 3

