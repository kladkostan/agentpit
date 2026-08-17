"""Mirror the real Polymarket tape: one synthetic trades row per
last_trade_price WSS event.

STATUS='MIRRORED' is distinct for provenance yet passes every reader's
`STATUS != 'FAILED'` filter (last-trade-price, price history, charts).
TAKER/MAKER_API_KEY are fabricated constants so user-scoped feeds
(/data/trades, /activity) never surface these rows. No FK constraints exist
on trades (table_create.py), so order-less rows are safe.

MATCH_KIND is always 'NORMAL' and MAKER_ASSET_ID always the same token as
ASSET_ID: a mirrored tape print stands in for a plain trade, never a mint or
merge, so both parties transact in the one token by construction.
"""
import secrets

import psycopg

MIRROR_TRADE_STATUS = "MIRRORED"
MIRROR_API_KEY = "mirror-tape"  # opaque, never a real user's api key


def insert_mirrored_trade(
    conn: psycopg.Connection,
    *,
    condition_id: str,
    local_token_id: str,
    price_micro: int,
    size_micro: int,
    side: str,
    match_time_s: int,
) -> str:
    trade_id = f"mirror-{secrets.token_hex(12)}"
    conn.execute(
        """
        INSERT INTO trades (
            TRADE_ID, TAKER_ORDER_ID, MAKER_ORDERS, MARKET, ASSET_ID,
            MAKER_ASSET_ID, MATCH_KIND,
            PRICE, TRADE_SIZE, REMAINING_SIZE, SIDE, STATUS,
            MATCH_TIME, TRANSACTION_HASH, BUCKET_INDEX, FEE_RATE_BPS,
            TAKER_API_KEY, MAKER_API_KEY
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            trade_id, "", "[]", condition_id, local_token_id,
            local_token_id, "NORMAL",
            price_micro, size_micro, 0, side, MIRROR_TRADE_STATUS,
            match_time_s, "", 0, 0,
            MIRROR_API_KEY, MIRROR_API_KEY,
        ),
    )
    return trade_id
