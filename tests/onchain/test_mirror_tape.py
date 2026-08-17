from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.liquidity.tape import MIRROR_API_KEY, MIRROR_TRADE_STATUS, insert_mirrored_trade
from tests.onchain._helpers import create_market, fresh_client


def test_mirrored_trade_feeds_last_trade_price_but_no_user_feed():
    client = fresh_client()
    m = create_market(client)
    cond = m["condition_id"]["value"]
    yes_token = m["erc1155_tokens"][0][0]

    db = DbSession(Settings().database_url)
    with db.write() as conn:
        trade_id = insert_mirrored_trade(
            conn, condition_id=cond, local_token_id=yes_token,
            price_micro=480_000, size_micro=2_500_000, side="BUY",
            match_time_s=1_700_000_000,
        )

    with db.read() as conn:
        row = conn.execute(
            "SELECT * FROM trades WHERE TRADE_ID = %s", (trade_id,)).fetchone()
    assert row["STATUS"] == MIRROR_TRADE_STATUS
    assert row["TAKER_API_KEY"] == MIRROR_API_KEY      # never a real user's key
    assert int(row["PRICE"]) == 480_000
    # A mirrored print is a plain trade, not a mint: both columns the
    # matcher's own rows carry now stay filled here too.
    assert row["MAKER_ASSET_ID"] == yes_token
    assert row["MATCH_KIND"] == "NORMAL"

    # Token-scoped readers see it (STATUS != 'FAILED' filter passes)...
    book = client.get(f"/book?token_id={yes_token}").json()
    assert book["last_trade_price"] == "0.48"

    # ...user-scoped feeds can't: trades are keyed by real API keys only.
    with db.read() as conn:
        rows = TableRead.list_trades_for_api_key(conn, "any-real-user-key")
    assert all(r["TRADE_ID"] != trade_id for r in rows)
