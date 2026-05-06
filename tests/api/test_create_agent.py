from fastapi.testclient import TestClient
from agentpit.fastapi import main


def _create_personality(client, personality_id="default_personality"):
    """Helper to create a personality for agent tests."""
    payload = {
        "personality_id": personality_id,
        "title": "Test Personality",
        "beliefs": "Markets are efficient",
        "methods": "Follow the trend",
        "needs": "Price feeds",
    }
    resp = client.post("/create_personality", json=payload)
    assert resp.status_code == 200
    return resp.json()


def test_create_agent():
    with TestClient(main.app) as client:
        _create_personality(client, "p1")
        payload = {
            "agent_id": "agent_1",
            "personality_id": "p1",
        }
        resp = client.post("/create_agent", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent_id"] == "agent_1"
        assert body["personality_id"] == "p1"
        assert body["state"] == {}
        assert body["history"] == []
        assert body["todo"] == []


def test_create_agent_duplicate():
    with TestClient(main.app) as client:
        _create_personality(client, "p2")
        payload = {
            "agent_id": "agent_dup",
            "personality_id": "p2",
        }
        resp = client.post("/create_agent", json=payload)
        assert resp.status_code == 200

        # Same agent_id again should 409
        resp2 = client.post("/create_agent", json=payload)
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"]


def test_create_agent_missing_personality():
    with TestClient(main.app) as client:
        payload = {
            "agent_id": "agent_orphan",
            "personality_id": "nonexistent_personality",
        }
        resp = client.post("/create_agent", json=payload)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]


def test_create_agent_empty_agent_id():
    with TestClient(main.app) as client:
        _create_personality(client, "p3")
        payload = {
            "agent_id": "",
            "personality_id": "p3",
        }
        resp = client.post("/create_agent", json=payload)
        assert resp.status_code == 400  # check_state raises


def test_create_agent_empty_personality_id():
    with TestClient(main.app) as client:
        payload = {
            "agent_id": "agent_no_personality",
            "personality_id": "",
        }
        resp = client.post("/create_agent", json=payload)
        assert resp.status_code == 400  # check_state raises


def test_create_agent_missing_field():
    with TestClient(main.app) as client:
        resp = client.post("/create_agent", json={"agent_id": "agent_x"})
        assert resp.status_code == 422


def test_create_multiple_agents():
    with TestClient(main.app) as client:
        _create_personality(client, "shared_personality")
        for i in range(3):
            payload = {
                "agent_id": f"multi_agent_{i}",
                "personality_id": "shared_personality",
            }
            resp = client.post("/create_agent", json=payload)
            assert resp.status_code == 200
            body = resp.json()
            assert body["agent_id"] == f"multi_agent_{i}"
            assert body["personality_id"] == "shared_personality"

