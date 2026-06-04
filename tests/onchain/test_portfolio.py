"""Migrated from old /portfolio endpoint to the new Polymarket-parity endpoints.

Scenarios preserved:
- fresh user → empty positions + positive USDC balance from signup grant.
- positions after split shows both YES and NO holdings.
"""

from tests.onchain._helpers import create_market, fresh_client, hdr, register


def test_fresh_user_shows_signup_grant_and_no_positions():
    client = fresh_client()
    user = register(client)
    eth_address = user["user"]["eth_address"]
    token = user["access_token"]

    # Positions are public-by-address — no auth required.
    positions = client.get(f"/positions?user={eth_address}").json()
    assert isinstance(positions, list)
    assert positions == []

    # Balance requires auth.
    resp = client.get(
        "/balance-allowance?asset_type=COLLATERAL", headers=hdr(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    # faucet drip happened at register — balance string must represent > 0 USDC.
    assert int(body["balance"]) > 0


def test_positions_after_split_shows_yes_and_no():
    client = fresh_client()
    user = register(client)
    token = user["access_token"]
    eth_address = user["user"]["eth_address"]
    market = create_market(client)
    yes_id, _ = market["erc1155_tokens"][0]
    no_id, _ = market["erc1155_tokens"][1]

    split_amount = 75_000_000  # micro-USDC (75 USDC)
    client.post(
        f"/markets/{market['market_id']}/split_position",
        headers=hdr(token),
        json={"amount": split_amount},
    ).raise_for_status()

    positions = client.get(f"/positions?user={eth_address}").json()
    by_asset = {p["asset"]: p for p in positions}

    assert yes_id in by_asset, "Expected YES position"
    assert no_id in by_asset, "Expected NO position"

    yes_pos = by_asset[yes_id]
    no_pos = by_asset[no_id]

    # split_amount is in micro-shares; size is display shares (divide by 1e6).
    expected_size = split_amount / 1_000_000
    assert yes_pos["size"] == expected_size
    assert yes_pos["outcome"] == "YES"
    assert yes_pos["proxyWallet"] == eth_address

    assert no_pos["size"] == expected_size
    assert no_pos["outcome"] == "NO"
    assert no_pos["proxyWallet"] == eth_address
