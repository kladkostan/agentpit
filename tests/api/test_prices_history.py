"""GET /prices-history returns {history:[{t,p}]} (§8.6). The no-trade path
needs no chain (empty history)."""

from fastapi.testclient import TestClient

from agentpit.api.main import app


def test_prices_history_empty_for_unknown_token():
    with TestClient(app) as client:
        body = client.get("/prices-history?market=999999").json()
        assert body == {"history": []}


def test_prices_history_shape_keys():
    with TestClient(app) as client:
        body = client.get("/prices-history?market=1&interval=1w").json()
        assert "history" in body and isinstance(body["history"], list)
