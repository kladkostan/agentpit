"""Replaces deleted tests/api/test_portfolio.py.

/portfolio reads on-chain apUSD + ERC1155 outcome-token balances and joins
them with the local markets table.
"""
from tests.onchain._helpers import create_market, fresh_client, hdr, register


def test_portfolio_for_fresh_user_shows_signup_grant_and_no_positions():
    client = fresh_client()
    user = register(client)
    resp = client.get("/portfolio", headers=hdr(user["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["eth_address"] == user["user"]["eth_address"]
    assert body["usdc_balance"] > 0   # faucet drip happened at register
    assert body["positions"] == []


def test_portfolio_lists_positions_after_split():
    client = fresh_client()
    user = register(client)
    token = user["access_token"]
    market = create_market(client)
    mid = market["market_id"]
    yes_id, _ = market["erc1155_tokens"][0]
    no_id, _ = market["erc1155_tokens"][1]

    split_amount = 75_000_000
    client.post(
        f"/markets/{mid}/split_position",
        headers=hdr(token),
        json={"amount": split_amount},
    ).raise_for_status()

    body = client.get("/portfolio", headers=hdr(token)).json()
    by_token = {p["token_id"]: p for p in body["positions"]}
    assert by_token[yes_id]["balance"] == split_amount
    assert by_token[yes_id]["market_id"] == mid
    assert by_token[yes_id]["outcome_label"] == "YES"
    assert by_token[no_id]["balance"] == split_amount
    assert by_token[no_id]["outcome_label"] == "NO"
