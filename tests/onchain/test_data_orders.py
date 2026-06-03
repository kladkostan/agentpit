"""GET /data/orders returns the caller's open orders as a bare OpenOrder[]
(§8.3). Live-chain (placing orders needs a prepared market)."""

from tests.onchain._helpers import create_market, fresh_client, register, hdr


def _yes_token(market) -> str:
    return market["erc1155_tokens"][0][0]


def test_open_orders_shape_and_owner_is_user_id():
    client = fresh_client()
    reg = register(client)
    tok = reg["access_token"]
    user_id = reg["user"]["user_id"]
    # NB: the api_key is never serialized in any response (§13), so the test
    # asserts `owner` positively equals the non-secret user_id.
    market = create_market(client)
    yes = _yes_token(market)
    cond = market["condition_id"]["value"]

    placed = client.post(
        "/order",
        headers=hdr(tok),
        json={"token_id": yes, "side": "BUY", "price": "0.40", "size": 25},
    ).json()
    oid = placed["orderID"]

    body = client.get("/data/orders", headers=hdr(tok)).json()
    assert isinstance(body, list) and len(body) == 1
    o = body[0]
    assert o["id"] == oid
    assert o["status"] == "LIVE"
    assert o["owner"] == user_id          # non-secret USER_ID, never the api_key
    assert o["market"] == cond            # condition_id, not token_id
    assert o["asset_id"] == yes
    assert o["side"] == "BUY"
    assert o["original_size"] == "25"
    assert o["size_matched"] == "0"
    assert o["price"] == "0.4"
    assert o["associate_trades"] == []
    assert o["order_type"] == "GTC"


def test_open_orders_filtered_by_asset_id():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes_token(market)
    client.post(
        "/order",
        headers=hdr(tok),
        json={"token_id": yes, "side": "BUY", "price": "0.40", "size": 25},
    )
    hit = client.get(f"/data/orders?asset_id={yes}", headers=hdr(tok)).json()
    assert len(hit) == 1
    miss = client.get("/data/orders?asset_id=999999", headers=hdr(tok)).json()
    assert miss == []


def test_open_orders_requires_auth():
    client = fresh_client()
    assert client.get("/data/orders").status_code == 401
