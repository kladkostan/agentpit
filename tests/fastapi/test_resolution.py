from fastapi.testclient import TestClient

from agentpit.fastapi import main


def test_resolve_market_and_redeem():
    with TestClient(main.server) as client:
        api_key_winner = "winner_key"
        api_key_loser = "loser_key"

        # Create a market
        market_payload = {
            "question": "Will the test pass?",
            "description": "Testing market resolution",
            "erc155_tokens": [["1", "Yes"], ["2", "No"]],
        }
        market_resp = client.post("/markets", json=market_payload)
        assert market_resp.status_code == 200
        market_id = market_resp.json()["market_id"]

        # Verify market is initially in DRAFT state
        get_resp = client.get(f"/markets/{market_id}")
        assert get_resp.json()["market_state"] == "DRAFT"
        assert get_resp.json()["resolved_outcome"] is None

        # Winner: Mint USDC and get outcome tokens
        client.post("/mint_usdc", json={"api_key": api_key_winner, "amount": 1000})
        split_resp = client.post(
            f"/markets/{market_id}/split_position",
            json={"api_key": api_key_winner, "amount": 100}
        )
        assert split_resp.status_code == 200
        assert split_resp.json()["token_balances"]["1"] == 100
        assert split_resp.json()["token_balances"]["2"] == 100

        # Loser: Mint USDC and get outcome tokens
        client.post("/mint_usdc", json={"api_key": api_key_loser, "amount": 500})
        client.post(
            f"/markets/{market_id}/split_position",
            json={"api_key": api_key_loser, "amount": 50}
        )

        # Resolve the market with winning outcome index 0 (Yes wins)
        resolve_payload = {
            "winning_outcome_index": 0,
        }
        resolve_resp = client.post(f"/markets/{market_id}/resolve", json=resolve_payload)
        assert resolve_resp.status_code == 200
        resolved_market = resolve_resp.json()
        assert resolved_market["market_id"] == market_id
        assert resolved_market["market_state"] == "RESOLVED"
        assert resolved_market["resolved_outcome"] == 0

        # Verify market state persists
        get_resp2 = client.get(f"/markets/{market_id}")
        fetched_market = get_resp2.json()
        assert fetched_market["market_state"] == "RESOLVED"
        assert fetched_market["resolved_outcome"] == 0

        # Winner redeems positions
        winner_balance_before = client.get(f"/usdc_balance/{api_key_winner}").json()["balance"]
        redeem_winner = client.post(
            f"/markets/{market_id}/redeem_position",
            json={"api_key": api_key_winner}
        )
        assert redeem_winner.status_code == 200
        redeem_winner_body = redeem_winner.json()
        assert redeem_winner_body["market_id"] == market_id
        assert redeem_winner_body["payout_usdc"] == 100
        assert redeem_winner_body["tokens_redeemed"]["1"] == 100
        assert redeem_winner_body["tokens_redeemed"]["2"] == 100

        # Verify winner's USDC balance increased
        winner_balance_after = client.get(f"/usdc_balance/{api_key_winner}").json()["balance"]
        assert winner_balance_after == winner_balance_before + 100

        # Loser redeems positions
        loser_balance_before = client.get(f"/usdc_balance/{api_key_loser}").json()["balance"]
        redeem_loser = client.post(
            f"/markets/{market_id}/redeem_position",
            json={"api_key": api_key_loser}
        )
        assert redeem_loser.status_code == 200
        redeem_loser_body = redeem_loser.json()
        assert redeem_loser_body["market_id"] == market_id
        assert redeem_loser_body["payout_usdc"] == 50
        assert redeem_loser_body["tokens_redeemed"]["1"] == 50
        assert redeem_loser_body["tokens_redeemed"]["2"] == 50

        # Verify loser's USDC balance increased by the value of their winning tokens
        loser_balance_after = client.get(f"/usdc_balance/{api_key_loser}").json()["balance"]
        assert loser_balance_after == loser_balance_before + 50


def test_resolve_market_not_found():
    with TestClient(main.server) as client:
        resolve_payload = {"winning_outcome_index": 0}
        resolve_resp = client.post("/markets/9999/resolve", json=resolve_payload)
        assert resolve_resp.status_code == 400
        assert "Market not found" in resolve_resp.json()["detail"]


def test_resolve_market_already_resolved():
    with TestClient(main.server) as client:
        market_payload = {"question": "Q", "description": "D", "erc155_tokens": [["1", "A"], ["2", "B"]]}
        market_resp = client.post("/markets", json=market_payload)
        market_id = market_resp.json()["market_id"]

        # Resolve once
        client.post(f"/markets/{market_id}/resolve", json={"winning_outcome_index": 0})

        # Try to resolve again
        resolve_resp = client.post(f"/markets/{market_id}/resolve", json={"winning_outcome_index": 1})
        assert resolve_resp.status_code == 400
        assert "already resolved" in resolve_resp.json()["detail"]


def test_resolve_market_invalid_outcome_index():
    with TestClient(main.server) as client:
        market_payload = {"question": "Q", "description": "D", "erc155_tokens": [["1", "A"], ["2", "B"]]}
        market_resp = client.post("/markets", json=market_payload)
        market_id = market_resp.json()["market_id"]

        # Index out of bounds
        resolve_resp = client.post(f"/markets/{market_id}/resolve", json={"winning_outcome_index": 2})
        assert resolve_resp.status_code == 400
        assert "Invalid winning_outcome_index" in resolve_resp.json()["detail"]

        # Negative index
        resolve_resp = client.post(f"/markets/{market_id}/resolve", json={"winning_outcome_index": -1})
        assert resolve_resp.status_code == 400
        assert "Invalid winning_outcome_index" in resolve_resp.json()["detail"]


def test_redeem_position_unresolved_market():
    with TestClient(main.server) as client:
        api_key = "eager_redeemer"
        market_payload = {"question": "Q", "description": "D", "erc155_tokens": [["1", "A"], ["2", "B"]]}
        market_resp = client.post("/markets", json=market_payload)
        market_id = market_resp.json()["market_id"]

        client.post("/mint_usdc", json={"api_key": api_key, "amount": 100})
        client.post(f"/markets/{market_id}/split_position", json={"api_key": api_key, "amount": 50})

        redeem_resp = client.post(f"/markets/{market_id}/redeem_position", json={"api_key": api_key})
        assert redeem_resp.status_code == 400
        assert "not resolved" in redeem_resp.json()["detail"].lower()


def test_redeem_position_market_not_found():
    with TestClient(main.server) as client:
        redeem_resp = client.post("/markets/9999/redeem_position", json={"api_key": "any_key"})
        assert redeem_resp.status_code == 404
        assert "Market not found" in redeem_resp.json()["detail"]

