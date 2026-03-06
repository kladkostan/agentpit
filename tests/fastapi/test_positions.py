from fastapi.testclient import TestClient

from agentpit.fastapi import main


def test_split_and_merge_positions():
    with TestClient(main.app) as client:
        api_key = "shares_test_key"

        # Create a market
        market_payload = {
            "question": "Will the sun rise tomorrow?",
            "description": "A very safe bet",
            "erc1155_tokens": [["1", "Yes"], ["2", "No"]],
        }
        market_resp = client.post("/markets", json=market_payload)
        assert market_resp.status_code == 200
        market_id = market_resp.json()["market_id"]

        # Mint USDC for the user
        mint_usdc_payload = {
            "api_key": api_key,
            "amount": 1000,
        }
        usdc_resp = client.post("/mint_usdc", json=mint_usdc_payload)
        assert usdc_resp.status_code == 200
        assert usdc_resp.json()["new_balance"] == 1000

        # Split position (complete sets)
        split_payload = {
            "api_key": api_key,
            "amount": 100,
        }
        split_resp = client.post(f"/markets/{market_id}/split_position", json=split_payload)
        assert split_resp.status_code == 200
        split_body = split_resp.json()
        assert split_body["market_id"] == market_id
        assert split_body["amount"] == 100
        assert split_body["collateral_amount"] == 100
        assert split_body["token_balances"]["1"] == 100  # Yes tokens
        assert split_body["token_balances"]["2"] == 100  # No tokens

        # Check USDC balance decreased
        balance_resp = client.get(f"/usdc_balance/{api_key}")
        assert balance_resp.status_code == 200
        assert balance_resp.json()["balance"] == 900  # 1000 - 100

        # Merge 50 positions back to USDC
        merge_payload = {
            "api_key": api_key,
            "amount": 50,
        }
        merge_resp = client.post(f"/markets/{market_id}/merge_positions", json=merge_payload)
        assert merge_resp.status_code == 200
        merge_body = merge_resp.json()
        assert merge_body["market_id"] == market_id
        assert merge_body["amount"] == 50
        assert merge_body["collateral_amount"] == 50
        assert merge_body["token_balances"]["1"] == 50  # 100 - 50
        assert merge_body["token_balances"]["2"] == 50  # 100 - 50

        # Check USDC balance increased
        balance_resp2 = client.get(f"/usdc_balance/{api_key}")
        assert balance_resp2.status_code == 200
        assert balance_resp2.json()["balance"] == 950  # 900 + 50


def test_split_position_insufficient_usdc():
    with TestClient(main.app) as client:
        api_key = "broke_user"

        # Create a market
        market_payload = {
            "question": "Will it rain?",
            "description": "Weather market",
            "erc1155_tokens": [["1", "Yes"], ["2", "No"]],
        }
        market_resp = client.post("/markets", json=market_payload)
        market_id = market_resp.json()["market_id"]

        # Try to split position without USDC
        split_payload = {
            "api_key": api_key,
            "amount": 100,
        }
        split_resp = client.post(f"/markets/{market_id}/split_position", json=split_payload)
        assert split_resp.status_code == 400
        assert "Insufficient USDC balance" in split_resp.json()["detail"]


def test_merge_positions_insufficient_tokens():
    with TestClient(main.app) as client:
        api_key = "partial_holder"

        # Create a market
        market_payload = {
            "question": "Test market?",
            "description": "Test",
            "erc1155_tokens": [["1", "Yes"], ["2", "No"]],
        }
        market_resp = client.post("/markets", json=market_payload)
        market_id = market_resp.json()["market_id"]

        # Mint USDC and split positions
        client.post("/mint_usdc", json={"api_key": api_key, "amount": 50})
        client.post(f"/markets/{market_id}/split_position", json={"api_key": api_key, "amount": 50})

        # Try to merge more than we have
        merge_payload = {
            "api_key": api_key,
            "amount": 100,
        }
        merge_resp = client.post(f"/markets/{market_id}/merge_positions", json=merge_payload)
        assert merge_resp.status_code == 400
        assert "Insufficient balance of token" in merge_resp.json()["detail"]

