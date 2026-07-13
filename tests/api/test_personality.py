from fastapi.testclient import TestClient

from agentpit.api.main import app as _app

# AGENTPIT_ADMIN_TOKEN is read at app startup by Settings; tests rely on
# the default ("dev-admin-token") so we don't need to mutate env here.
ADMIN_TOKEN = "dev-admin-token"
ADMIN_HDR = {"X-Admin-Token": ADMIN_TOKEN}


def test_create_personality():
    with TestClient(_app) as client:
        payload = {
            "personality_id": "contrarian_1",
            "title": "Contrarian Trader",
            "beliefs": "Markets overreact to news",
            "methods": "Fade large moves and revert to mean",
            "needs": "Real-time sentiment data",
        }
        resp = client.post("/create_personality", json=payload, headers=ADMIN_HDR)
        assert resp.status_code == 200
        body = resp.json()
        assert body["personality_id"] == "contrarian_1"
        assert body["title"] == payload["title"]
        assert body["spec"]["beliefs"] == payload["beliefs"]
        assert body["spec"]["methods"] == payload["methods"]
        assert body["spec"]["needs"] == payload["needs"]


def test_create_personality_missing_field():
    with TestClient(_app) as client:
        # Missing 'needs'
        payload = {
            "personality_id": "incomplete_1",
            "title": "Incomplete",
            "beliefs": "Something",
            "methods": "Something else",
        }
        resp = client.post("/create_personality", json=payload, headers=ADMIN_HDR)
        assert resp.status_code == 422


def test_create_personality_empty_title():
    with TestClient(_app) as client:
        payload = {
            "personality_id": "empty_title_1",
            "title": "",
            "beliefs": "Believe in efficiency",
            "methods": "Arbitrage",
            "needs": "Low latency feeds",
        }
        resp = client.post("/create_personality", json=payload, headers=ADMIN_HDR)
        assert resp.status_code == 400  # check_state raises


def test_create_multiple_personalities():
    with TestClient(_app) as client:
        ids = []
        for i in range(3):
            payload = {
                "personality_id": f"personality_{i}",
                "title": f"Personality {i}",
                "beliefs": f"Belief {i}",
                "methods": f"Method {i}",
                "needs": f"Need {i}",
            }
            resp = client.post("/create_personality", json=payload, headers=ADMIN_HDR)
            assert resp.status_code == 200
            body = resp.json()
            ids.append(body["personality_id"])

        # All IDs should be unique
        assert len(set(ids)) == 3
