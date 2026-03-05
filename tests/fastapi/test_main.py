from fastapi.testclient import TestClient

from agentpit.fastapi import main


def test_read_root_returns_version():
    with TestClient(main.server) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json() == {"version": "1.0"}


def test_create_and_get_market():
    with TestClient(main.server) as client:
        # First create a market
        payload = {
            "question": "Will it snow today?",
            "description": "Weather prediction market",
            "erc155_tokens": [["1", "Yes"], ["2", "No"]],
        }
        create_resp = client.post("/markets", json=payload)
        assert create_resp.status_code == 200
        created_market = create_resp.json()
        market_id = created_market["market_id"]

        # Now get the market by ID
        get_resp = client.get(f"/markets/{market_id}")
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["market_id"] == market_id
        assert body["question"] == payload["question"]
        assert body["description"] == payload["description"]
        assert body["erc155_tokens"] == payload["erc155_tokens"]
        assert body["condition_id"] == created_market["condition_id"]
        assert body["market_state"] == "DRAFT"

        # Test getting a non-existent market
        resp = client.get("/markets/9999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Market not found"


def test_list_markets():
    with TestClient(main.server) as client:
        # List markets when empty
        resp = client.get("/markets")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["markets"] == []
        assert body["limit"] == 100
        assert body["offset"] == 0

        # Create multiple markets
        for i in range(5):
            payload = {
                "question": f"Question {i}?",
                "description": f"Description {i}",
                "erc155_tokens": [["1", "Yes"], ["2", "No"]],
            }
            client.post("/markets", json=payload)

        # List all markets
        resp = client.get("/markets")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert len(body["markets"]) == 5
        assert body["limit"] == 100
        assert body["offset"] == 0

        # Test pagination with limit
        resp = client.get("/markets?limit=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert len(body["markets"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0

        # Test pagination with offset
        resp = client.get("/markets?limit=2&offset=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert len(body["markets"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 2

        # Test invalid limit
        resp = client.get("/markets?limit=2000")
        assert resp.status_code == 400
        assert "limit" in resp.json()["detail"].lower()

        # Test invalid offset
        resp = client.get("/markets?offset=-1")
        assert resp.status_code == 400
        assert "offset" in resp.json()["detail"].lower()


def test_mint_usdc():
    with TestClient(main.server) as client:
        payload = {
            "api_key": "test_api_key_123",
            "amount": 1000000,
        }
        resp = client.post("/mint_usdc", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["eth_address"]  # ETH address is generated
        assert body["amount"] == payload["amount"]
        assert body["new_balance"] == payload["amount"]

        # Mint again to the same API key
        payload2 = {
            "api_key": "test_api_key_123",
            "amount": 500000,
        }
        resp2 = client.post("/mint_usdc", json=payload2)
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["eth_address"] == body["eth_address"]  # Same address
        assert body2["amount"] == payload2["amount"]
        assert body2["new_balance"] == payload["amount"] + payload2["amount"]


def test_get_usdc_balance():
    with TestClient(main.server) as client:
        api_key = "test_balance_key"

        # Check balance before minting (should be 0)
        resp = client.get(f"/usdc_balance/{api_key}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["eth_address"]
        assert body["balance"] == 0

        # Mint some USDC
        mint_payload = {
            "api_key": api_key,
            "amount": 2000000,
        }
        mint_resp = client.post("/mint_usdc", json=mint_payload)
        assert mint_resp.status_code == 200

        # Check balance after minting
        resp2 = client.get(f"/usdc_balance/{api_key}")
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["eth_address"] == body["eth_address"]
        assert body2["balance"] == 2000000


def test_transfer_usdc():
    with TestClient(main.server) as client:
        sender_key = "sender_key"
        receiver_key = "receiver_key"

        # Mint USDC to sender
        mint_payload = {
            "api_key": sender_key,
            "amount": 5000000,
        }
        mint_resp = client.post("/mint_usdc", json=mint_payload)
        assert mint_resp.status_code == 200
        sender_address = mint_resp.json()["eth_address"]

        # Get receiver address
        receiver_resp = client.get(f"/usdc_balance/{receiver_key}")
        assert receiver_resp.status_code == 200
        receiver_address = receiver_resp.json()["eth_address"]
        assert receiver_resp.json()["balance"] == 0

        # Transfer USDC from sender to receiver
        transfer_payload = {
            "api_key": sender_key,
            "destination_address": receiver_address,
            "amount": 3000000,
        }
        transfer_resp = client.post("/transfer_usdc", json=transfer_payload)
        assert transfer_resp.status_code == 200
        transfer_body = transfer_resp.json()
        assert transfer_body["from_address"] == sender_address
        assert transfer_body["to_address"] == receiver_address
        assert transfer_body["amount"] == 3000000
        assert transfer_body["new_balance"] == 2000000  # 5000000 - 3000000

        # Verify sender balance
        sender_balance = client.get(f"/usdc_balance/{sender_key}")
        assert sender_balance.json()["balance"] == 2000000

        # Verify receiver balance
        receiver_balance = client.get(f"/usdc_balance/{receiver_key}")
        assert receiver_balance.json()["balance"] == 3000000


def test_transfer_usdc_insufficient_balance():
    with TestClient(main.server) as client:
        sender_key = "poor_sender"
        receiver_address = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"

        # Mint small amount
        mint_payload = {
            "api_key": sender_key,
            "amount": 100,
        }
        client.post("/mint_usdc", json=mint_payload)

        # Try to transfer more than balance
        transfer_payload = {
            "api_key": sender_key,
            "destination_address": receiver_address,
            "amount": 1000,
        }
        transfer_resp = client.post("/transfer_usdc", json=transfer_payload)
        assert transfer_resp.status_code == 400  # Should fail with insufficient balance
        assert "Insufficient balance" in transfer_resp.json()["detail"]


def test_split_and_merge_positions():
    with TestClient(main.server) as client:
        api_key = "shares_test_key"

        # Create a market
        market_payload = {
            "question": "Will the sun rise tomorrow?",
            "description": "A very safe bet",
            "erc155_tokens": [["1", "Yes"], ["2", "No"]],
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
    with TestClient(main.server) as client:
        api_key = "broke_user"

        # Create a market
        market_payload = {
            "question": "Will it rain?",
            "description": "Weather market",
            "erc155_tokens": [["1", "Yes"], ["2", "No"]],
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
    with TestClient(main.server) as client:
        api_key = "partial_holder"

        # Create a market
        market_payload = {
            "question": "Test market?",
            "description": "Test",
            "erc155_tokens": [["1", "Yes"], ["2", "No"]],
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



