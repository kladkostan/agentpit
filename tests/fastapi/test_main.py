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



