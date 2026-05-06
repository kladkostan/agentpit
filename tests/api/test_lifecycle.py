from fastapi.testclient import TestClient

from agentpit.fastapi import main

def test_cancel_market():
    with TestClient(main.app) as client:
        # Create a market
        market_payload = {
            "question": "Cancel test?",
            "description": "Testing cancellation",
            "erc1155_tokens": [["1", "A"], ["2", "B"]],
        }
        market_resp = client.post("/markets", json=market_payload)
        market_id = market_resp.json()["market_id"]

        # Cancel from DRAFT state
        cancel_resp = client.post(f"/markets/{market_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["market"]["market_state"] == "CANCELLED"
        assert cancel_resp.json()["refunds_processed"] == 0

        # Verify state
        get_resp = client.get(f"/markets/{market_id}")
        assert get_resp.json()["market_state"] == "CANCELLED"


def test_market_lifecycle_happy_path():
    with TestClient(main.app) as client:
        # 1. Create Market (DRAFT)
        market_payload = {
            "question": "Lifecycle test?",
            "description": "Testing the market state machine",
            "erc1155_tokens": [["1", "A"], ["2", "B"]],
        }
        market_resp = client.post("/markets", json=market_payload)
        assert market_resp.status_code == 200
        market_id = market_resp.json()["market_id"]
        assert market_resp.json()["market_state"] == "DRAFT"

        # 2. Activate Market (DRAFT -> ACTIVE)
        activate_resp = client.post(f"/markets/{market_id}/activate")
        assert activate_resp.status_code == 200
        assert activate_resp.json()["market_state"] == "ACTIVE"

        # Verify state
        get_resp = client.get(f"/markets/{market_id}")
        assert get_resp.json()["market_state"] == "ACTIVE"

        # 3. Close Market (ACTIVE -> CLOSED)
        close_resp = client.post(f"/markets/{market_id}/close")
        assert close_resp.status_code == 200
        assert close_resp.json()["market_state"] == "CLOSED"

        # Verify state
        get_resp2 = client.get(f"/markets/{market_id}")
        assert get_resp2.json()["market_state"] == "CLOSED"

        # 4. Resolve Market (CLOSED -> RESOLVED)
        resolve_resp = client.post(f"/markets/{market_id}/resolve", json={"winning_outcome_index": 0})
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["market_state"] == "RESOLVED"

        # Verify state
        get_resp3 = client.get(f"/markets/{market_id}")
        assert get_resp3.json()["market_state"] == "RESOLVED"





def test_cancel_market_with_positions():
    with TestClient(main.app) as client:
        api_key = "canceller"
        market_payload = {
            "question": "Cancel with positions?",
            "description": "Testing cancellation refunds",
            "erc1155_tokens": [["1", "A"], ["2", "B"]],
        }
        market_resp = client.post("/markets", json=market_payload)
        market_id = market_resp.json()["market_id"]

        # Mint USDC and split positions
        client.post("/mint_usdc", json={"api_key": api_key, "amount": 100})
        client.post(f"/markets/{market_id}/split_position", json={"api_key": api_key, "amount": 50})

        # Check balance before cancel
        balance_before = client.get(f"/usdc_balance/{api_key}").json()["balance"]
        assert balance_before == 50

        # Cancel market
        cancel_resp = client.post(f"/markets/{market_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["refunds_processed"] == 1

        # Check balance after cancel (should be refunded)
        balance_after = client.get(f"/usdc_balance/{api_key}").json()["balance"]
        assert balance_after == 100


def test_invalid_state_transitions():
    with TestClient(main.app) as client:
        # Create a market, it starts in DRAFT
        market_payload = {"question": "Invalid transitions?", "description": "Test", "erc1155_tokens": [["1", "A"], ["2", "B"]]}
        market_resp = client.post("/markets", json=market_payload)
        market_id = market_resp.json()["market_id"]

        # DRAFT -> CLOSE (Invalid)
        resp = client.post(f"/markets/{market_id}/close")
        assert resp.status_code == 400
        assert "not in ACTIVE state" in resp.json()["detail"]

        # Activate market: DRAFT -> ACTIVE
        client.post(f"/markets/{market_id}/activate")

        # ACTIVE -> ACTIVATE (Invalid)
        resp = client.post(f"/markets/{market_id}/activate")
        assert resp.status_code == 400
        assert "not in DRAFT state" in resp.json()["detail"]

        # Close market: ACTIVE -> CLOSED
        client.post(f"/markets/{market_id}/close")

        # CLOSED -> ACTIVATE (Invalid)
        resp = client.post(f"/markets/{market_id}/activate")
        assert resp.status_code == 400
        assert "not in DRAFT state" in resp.json()["detail"]

        # CLOSED -> CLOSE (Invalid)
        resp = client.post(f"/markets/{market_id}/close")
        assert resp.status_code == 400
        assert "not in ACTIVE state" in resp.json()["detail"]

        # Resolve market: CLOSED -> RESOLVED
        client.post(f"/markets/{market_id}/resolve", json={"winning_outcome_index": 0})

        # RESOLVED -> any other state (Invalid)
        resp = client.post(f"/markets/{market_id}/activate")
        assert resp.status_code == 400
        resp = client.post(f"/markets/{market_id}/close")
        assert resp.status_code == 400
        resp = client.post(f"/markets/{market_id}/cancel")
        assert resp.status_code == 400
        resp = client.post(f"/markets/{market_id}/resolve", json={"winning_outcome_index": 0})
        assert resp.status_code == 400

