"""POST /order idempotency: a repeated client_order_id replays the first order
instead of placing a second; absent client_order_id keeps legacy behavior."""

from tests.onchain._helpers import create_market, fresh_client, register, hdr


def _yes(market) -> str:
    return market["erc1155_tokens"][0][0]


def test_same_client_order_id_places_once():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes(market)
    body = {
        "token_id": yes, "side": "BUY", "price": "0.40", "size": 10,
        "client_order_id": "coid-abc",
    }
    r1 = client.post("/order", headers=hdr(tok), json=body).json()
    r2 = client.post("/order", headers=hdr(tok), json=body).json()
    assert r1["orderID"] == r2["orderID"]

    orders = client.get("/data/orders", headers=hdr(tok)).json()
    assert len([o for o in orders if o["asset_id"] == yes]) == 1


def test_absent_client_order_id_allows_two_orders():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes(market)
    body = {"token_id": yes, "side": "BUY", "price": "0.40", "size": 10}
    o1 = client.post("/order", headers=hdr(tok), json=body).json()["orderID"]
    o2 = client.post("/order", headers=hdr(tok), json=body).json()["orderID"]
    assert o1 != o2
