"""Replaces deleted tests/api/test_positions.py.

splitPosition + mergePositions + insufficient-balance rejections. All flows
go through real CTF on-chain calls signed by the user's server-held key.
"""

from tests.onchain._helpers import create_market, fresh_client, hdr, register


def test_split_then_merge_round_trip():
    client = fresh_client()
    user = register(client)
    token = user["access_token"]
    market = create_market(client)
    mid = market["market_id"]
    yes_id, no_id = market["erc1155_tokens"][0][0], market["erc1155_tokens"][1][0]

    initial = client.get("/usdc_balance", headers=hdr(token)).json()["balance"]

    split_amount = 100_000_000
    split = client.post(
        f"/markets/{mid}/split_position",
        headers=hdr(token),
        json={"amount": split_amount},
    )
    assert split.status_code == 200, split.text
    body = split.json()
    assert body["amount"] == split_amount
    assert body["token_balances"][yes_id] == split_amount
    assert body["token_balances"][no_id] == split_amount

    after_split = client.get("/usdc_balance", headers=hdr(token)).json()["balance"]
    assert after_split == initial - split_amount

    merge_amount = 40_000_000
    merge = client.post(
        f"/markets/{mid}/merge_positions",
        headers=hdr(token),
        json={"amount": merge_amount},
    )
    assert merge.status_code == 200, merge.text
    mbody = merge.json()
    assert mbody["amount"] == merge_amount
    assert mbody["token_balances"][yes_id] == split_amount - merge_amount
    assert mbody["token_balances"][no_id] == split_amount - merge_amount

    after_merge = client.get("/usdc_balance", headers=hdr(token)).json()["balance"]
    assert after_merge == initial - split_amount + merge_amount


def test_split_insufficient_usdc_is_400():
    client = fresh_client()
    user = register(client)
    market = create_market(client)
    # Faucet grants 1M apUSD = 1_000_000 * 10**6 raw; ask for more than that.
    resp = client.post(
        f"/markets/{market['market_id']}/split_position",
        headers=hdr(user["access_token"]),
        json={"amount": 10**18},
    )
    assert resp.status_code == 400
    assert "need" in resp.json()["detail"]


def test_merge_insufficient_tokens_is_400():
    client = fresh_client()
    user = register(client)
    market = create_market(client)
    mid = market["market_id"]
    # No splitPosition first → user holds 0 outcome tokens
    resp = client.post(
        f"/markets/{mid}/merge_positions",
        headers=hdr(user["access_token"]),
        json={"amount": 10},
    )
    assert resp.status_code == 400
    assert "have 0" in resp.json()["detail"]
