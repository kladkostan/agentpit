"""Replaces deleted tests/api/test_lifecycle.py.

Markets state-machine: DRAFT → ACTIVE → CLOSED → RESOLVED, plus cancel and
invalid transitions. Lives on-chain because market creation does prepareCondition.
"""
from tests.onchain._helpers import create_market, fresh_client


def test_market_lifecycle_happy_path():
    client = fresh_client()
    market = create_market(client)
    mid = market["market_id"]
    assert market["market_state"] == "DRAFT"

    activate = client.post(f"/markets/{mid}/activate").json()
    assert activate["market_state"] == "ACTIVE"
    assert client.get(f"/markets/{mid}").json()["market_state"] == "ACTIVE"

    close = client.post(f"/markets/{mid}/close").json()
    assert close["market_state"] == "CLOSED"
    assert client.get(f"/markets/{mid}").json()["market_state"] == "CLOSED"

    resolve = client.post(
        f"/markets/{mid}/resolve", json={"winning_outcome_index": 0}
    ).json()
    assert resolve["market_state"] == "RESOLVED"
    assert resolve["resolved_outcome"] == 0


def test_cancel_market_from_draft():
    client = fresh_client()
    mid = create_market(client)["market_id"]
    cancel = client.post(f"/markets/{mid}/cancel").json()
    assert cancel["market"]["market_state"] == "CANCELLED"
    # On-chain CTF positions: refund flows are now off-loaded to merge/redeem
    # by users themselves, so the backend-side counter is always 0.
    assert cancel["refunds_processed"] == 0
    assert client.get(f"/markets/{mid}").json()["market_state"] == "CANCELLED"


def test_invalid_state_transitions():
    client = fresh_client()
    mid = create_market(client)["market_id"]

    # DRAFT → CLOSE is invalid
    resp = client.post(f"/markets/{mid}/close")
    assert resp.status_code == 400
    assert "ACTIVE" in resp.json()["detail"]

    client.post(f"/markets/{mid}/activate")
    # ACTIVE → ACTIVATE is invalid
    resp = client.post(f"/markets/{mid}/activate")
    assert resp.status_code == 400
    assert "DRAFT" in resp.json()["detail"]


def test_resolve_unknown_market_404():
    client = fresh_client()
    resp = client.post("/markets/9999/resolve", json={"winning_outcome_index": 0})
    assert resp.status_code == 404


def test_resolve_twice_is_400():
    client = fresh_client()
    mid = create_market(client)["market_id"]
    client.post(f"/markets/{mid}/resolve", json={"winning_outcome_index": 0})
    resp = client.post(f"/markets/{mid}/resolve", json={"winning_outcome_index": 1})
    assert resp.status_code == 400
    assert "already resolved" in resp.json()["detail"]
