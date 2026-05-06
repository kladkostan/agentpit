from fastapi.testclient import TestClient

from agentpit.fastapi import main


def test_get_transaction_history():
    with TestClient(main.app) as client:
        api_key = "history_test_key"

        # 1. Initially, history should be empty
        resp = client.get(f"/markets/history/{api_key}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["eth_address"]  # Address is created on first call
        assert body["transactions"] == []

        # 2. Create a market and perform some actions
        market_payload = {"question": "History test?", "description": "...", "erc1155_tokens": [["1", "A"], ["2", "B"]]}
        market_resp = client.post("/markets", json=market_payload)
        market_id = market_resp.json()["market_id"]

        client.post("/mint_usdc", json={"api_key": api_key, "amount": 1000})
        client.post(f"/markets/{market_id}/split_position", json={"api_key": api_key, "amount": 100})
        client.post(f"/markets/{market_id}/merge_positions", json={"api_key": api_key, "amount": 20})

        # 3. Check history again
        resp2 = client.get(f"/markets/history/{api_key}")
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert len(body2["transactions"]) == 2

        # Don't assume API ordering; find transactions by type.
        tx_by_type = {tx["transaction_type"]: tx for tx in body2["transactions"]}

        merge_tx = tx_by_type["MERGE"]
        assert merge_tx["market_id"] == market_id
        assert merge_tx["details"]["amount"] == 20
        assert merge_tx["details"]["collateral_minted"] == 20

        split_tx = tx_by_type["SPLIT"]
        assert split_tx["market_id"] == market_id
        assert split_tx["details"]["amount"] == 100
        assert split_tx["details"]["collateral_burned"] == 100

        # 4. Resolve and redeem
        client.post(f"/markets/{market_id}/resolve", json={"winning_outcome_index": 0})
        client.post(f"/markets/{market_id}/redeem_position", json={"api_key": api_key})

        # 5. Final history check
        resp3 = client.get(f"/markets/history/{api_key}")
        assert resp3.status_code == 200
        body3 = resp3.json()
        assert len(body3["transactions"]) == 3

        redeem_tx = next(tx for tx in body3["transactions"] if tx["transaction_type"] == "REDEEM")
        assert redeem_tx["market_id"] == market_id
        assert redeem_tx["details"]["payout_usdc"] > 0
