from fastapi.testclient import TestClient

from agentpit.fastapi import main


def test_mint_usdc():
    with TestClient(main.app) as client:
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
    with TestClient(main.app) as client:
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
    with TestClient(main.app) as client:
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
    with TestClient(main.app) as client:
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

