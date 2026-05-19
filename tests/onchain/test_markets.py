"""Replaces deleted tests/api/test_markets.py.

Live-chain because POST /markets calls prepareCondition + registerToken.
"""

from tests.onchain._helpers import create_market, fresh_client, unique_question


def test_create_and_get_market_round_trip():
    client = fresh_client()
    q = unique_question()
    created = create_market(client, q)
    assert created["market_state"] == "DRAFT"
    assert created["question"] == q
    assert created["condition_id"]["value"].startswith("0x")
    assert len(created["erc1155_tokens"]) == 2
    yes_id, yes_label = created["erc1155_tokens"][0]
    no_id, no_label = created["erc1155_tokens"][1]
    assert yes_label == "YES" and no_label == "NO"
    assert int(yes_id) > 0 and int(no_id) > 0

    fetched = client.get(f"/markets/{created['market_id']}").json()
    assert fetched["market_id"] == created["market_id"]
    assert fetched["condition_id"] == created["condition_id"]
    assert fetched["erc1155_tokens"] == created["erc1155_tokens"]


def test_get_unknown_market_returns_404():
    client = fresh_client()
    resp = client.get("/markets/9999")
    assert resp.status_code == 404


def test_list_markets_paginates():
    client = fresh_client()
    ids = []
    for _ in range(3):
        ids.append(create_market(client)["market_id"])

    body = client.get("/markets?limit=100&offset=0").json()
    assert body["total"] >= 3
    fetched_ids = {m["market_id"] for m in body["markets"]}
    assert set(ids).issubset(fetched_ids)

    page = client.get("/markets?limit=2&offset=0").json()
    assert page["limit"] == 2
    assert len(page["markets"]) == 2

    bad = client.get("/markets?limit=2000")
    assert bad.status_code == 400
    bad2 = client.get("/markets?offset=-1")
    assert bad2.status_code == 400
