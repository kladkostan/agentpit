"""AgentpitClient — REST wrapper.

We don't use a real network — use a fake `requests`-like session that
records calls.
"""
import json

import pytest

from agentpit_bots.client import AgentpitClient


class FakeResponse:
    def __init__(self, status_code: int, body: dict | list | None = None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, str, dict | None, dict]] = []
        self.next_response: FakeResponse = FakeResponse(200)

    def request(self, method, url, *, json=None, headers=None, timeout=None):
        self.calls.append((method, url, json, dict(headers or {})))
        return self.next_response


@pytest.fixture
def session():
    return FakeSession()


def test_register_persists_and_returns_creds(session):
    session.next_response = FakeResponse(200, {
        "access_token": "tok-abc",
        "user": {"eth_address": "0xDEAD"},
    })
    c = AgentpitClient(base_url="http://x", session=session)
    creds = c.register(email="bot@x", password="hunter22hunter22")
    assert creds.token == "tok-abc"
    assert creds.eth_address == "0xDEAD"
    method, url, body, _ = session.calls[0]
    assert method == "POST"
    assert url == "http://x/register"
    assert body == {"email": "bot@x", "password": "hunter22hunter22"}


def test_place_order_includes_bearer_token(session):
    session.next_response = FakeResponse(200, {
        "success": True, "orderID": "0x1", "status": "live",
        "filledSize": "0", "remainingSize": "100",
    })
    c = AgentpitClient(base_url="http://x", session=session)
    c.place_order(
        token="tok-abc",
        market_id=1, outcome="Yes", side="BUY",
        price="0.5", size=100_000_000,
    )
    method, url, body, headers = session.calls[0]
    assert method == "POST"
    assert url == "http://x/orders"
    assert body == {
        "market_id": 1, "outcome": "Yes", "side": "BUY",
        "price": "0.5", "size": 100_000_000, "order_type": "GTC",
        "expiration": 0,
    }
    assert headers["Authorization"] == "Bearer tok-abc"


def test_list_mine(session):
    session.next_response = FakeResponse(200, {"orders": [{"ORDER_ID": "o1"}]})
    c = AgentpitClient(base_url="http://x", session=session)
    orders = c.list_my_orders(token="tok-abc")
    assert orders == [{"ORDER_ID": "o1"}]


def test_cancel_order(session):
    session.next_response = FakeResponse(200, {"order_id": "o1", "status": "cancelled"})
    c = AgentpitClient(base_url="http://x", session=session)
    c.cancel_order(token="tok-abc", order_id="o1")
    method, url, _, _ = session.calls[0]
    assert method == "DELETE"
    assert url == "http://x/orders/o1"


def test_mark_bot_uses_admin_header(session):
    session.next_response = FakeResponse(200, {"eth_address": "0xa", "is_bot": True})
    c = AgentpitClient(base_url="http://x", session=session, admin_token="secret")
    c.mark_bot(eth_address="0xa")
    method, url, body, headers = session.calls[0]
    assert method == "POST"
    assert url == "http://x/admin/mark_bot"
    assert body == {"eth_address": "0xa"}
    assert headers["X-Admin-Token"] == "secret"


def test_split_position(session):
    session.next_response = FakeResponse(200, {})
    c = AgentpitClient(base_url="http://x", session=session)
    c.split_position(token="tok-abc", market_id=5, amount=500)
    method, url, body, _ = session.calls[0]
    assert method == "POST"
    assert url == "http://x/markets/5/split_position"
    assert body == {"amount": 500}


def test_merge_positions(session):
    session.next_response = FakeResponse(200, {})
    c = AgentpitClient(base_url="http://x", session=session)
    c.merge_positions(token="tok-abc", market_id=5, amount=200)
    method, url, body, _ = session.calls[0]
    assert url == "http://x/markets/5/merge_positions"
    assert body == {"amount": 200}


def test_get_markets(session):
    session.next_response = FakeResponse(200, {"markets": [{"market_id": 1}]})
    c = AgentpitClient(base_url="http://x", session=session)
    out = c.get_markets()
    assert out == [{"market_id": 1}]
    method, url, _, _ = session.calls[0]
    assert method == "GET"
    assert url == "http://x/markets"


def test_get_portfolio(session):
    session.next_response = FakeResponse(200, {"usdc_balance": 1000, "positions": []})
    c = AgentpitClient(base_url="http://x", session=session)
    out = c.get_portfolio(token="tok-abc")
    assert out["usdc_balance"] == 1000
