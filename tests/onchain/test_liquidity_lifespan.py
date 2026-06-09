from fastapi.testclient import TestClient

from agentpit.api.app import create_app
from agentpit.db.table_read import TableRead
from tests.db_helpers import fresh_test_conn


def test_engine_disabled_by_default():
    # Engine off by default → lifespan enter/exit clean, no house accounts created.
    with TestClient(create_app()):
        pass
    conn = fresh_test_conn()
    assert TableRead.list_bot_users(conn) == []


def test_engine_enabled_provisions_and_ticks(monkeypatch):
    monkeypatch.setenv("LIQUIDITY_ENGINE", "true")
    monkeypatch.setenv("AGENTPIT_LIQUIDITY_HOUSE_ACCOUNTS", "2")
    monkeypatch.setenv("AGENTPIT_LIQUIDITY_FUNDING_DRIPS", "1")
    monkeypatch.setenv("AGENTPIT_LIQUIDITY_INTERVAL_SECONDS", "0.2")
    import time
    with TestClient(create_app()):
        time.sleep(1.0)  # let provisioning finish + a few ticks run
        conn = fresh_test_conn()
        bots = TableRead.list_bot_users(conn)
    assert len(bots) == 2  # provisioned exactly the target, no exceptions raised
