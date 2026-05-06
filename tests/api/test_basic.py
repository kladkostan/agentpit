from fastapi.testclient import TestClient

from agentpit.api.main import app as _app


def test_read_root_returns_version():
    with TestClient(_app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json() == {"version": "1.0"}

