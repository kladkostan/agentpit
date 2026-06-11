"""Up/Down markets must expose an upstream token id so the book mirror can
resolve them.

The mirror skips any market with a null `polymarket_yes_token_id`
(liquidity/mirror.py). For binary markets whose outcomes aren't literally
Yes/No (e.g. *BTC Up or Down 5m*), the extractor falls back to positional
mapping, and the cheap-path sync backfills already-synced rows.
"""

import secrets

from agentpit.datastructures.condition_id import ConditionId
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.polymarket.polymarket_sync import (
    _extract_yes_no_token_ids,
    build_create_market_request_from_json,
    create_polygon_market_if_does_not_exist,
)
from tests.db_helpers import fresh_test_conn


# ----- _extract_yes_no_token_ids ----------------------------------------------


def test_extract_matches_literal_yes_no():
    pm = {
        "tokens": [
            {"token_id": "111", "outcome": "Yes"},
            {"token_id": "222", "outcome": "No"},
        ]
    }
    assert _extract_yes_no_token_ids(pm) == ("111", "222")


def test_extract_positional_fallback_for_updown():
    pm = {
        "tokens": [
            {"token_id": "111", "outcome": "Up"},
            {"token_id": "222", "outcome": "Down"},
        ]
    }
    # Up -> yes-slot (index 0), Down -> no-slot (index 1).
    assert _extract_yes_no_token_ids(pm) == ("111", "222")


def test_extract_none_when_not_binary():
    pm = {
        "tokens": [
            {"token_id": "1", "outcome": "A"},
            {"token_id": "2", "outcome": "B"},
            {"token_id": "3", "outcome": "C"},
        ]
    }
    assert _extract_yes_no_token_ids(pm) == (None, None)


def test_build_request_captures_updown_token_ids():
    pm = {
        "id": 1,
        "conditionId": "0x" + "ab" * 32,
        "question": "Bitcoin Up or Down",
        "description": "d",
        "slug": "s",
        "startDate": "2026-01-01T00:00:00Z",
        "endDate": "2026-01-02T00:00:00Z",
        "active": True,
        "closed": False,
        "tokens": [
            {"token_id": "111", "outcome": "Up"},
            {"token_id": "222", "outcome": "Down"},
        ],
    }
    req = build_create_market_request_from_json(pm)
    assert req.polymarket_yes_token_id == "111"
    assert req.polymarket_no_token_id == "222"


# ----- update_market_polymarket_tokens (backfill seam) ------------------------


def _seed_market(conn, *, pmid, cond, yes, no):
    pm = {
        "id": pmid,
        "conditionId": "0x" + "ef" * 32,
        "question": f"q-{pmid}",
        "description": "d",
        "slug": f"s-{pmid}",
        "startDate": "2026-01-01T00:00:00Z",
        "endDate": "2026-01-02T00:00:00Z",
        "active": True,
        "closed": False,
        "tokens": [
            {"token_id": "111", "outcome": "Up"},
            {"token_id": "222", "outcome": "Down"},
        ],
    }
    req = build_create_market_request_from_json(pm)
    req.polymarket_yes_token_id = yes
    req.polymarket_no_token_id = no
    req.condition_id = ConditionId(cond)
    return TableWrite.create_market(conn, req, True)


def test_update_tokens_coalesce_and_noop():
    conn = fresh_test_conn()
    cond = "0x" + secrets.token_hex(32)
    _seed_market(conn, pmid=7, cond=cond, yes="AAA", no=None)

    # COALESCE: a None must not clobber an existing id; the other side fills in.
    TableWrite.update_market_polymarket_tokens(
        conn, polymarket_id=7, yes_token_id=None, no_token_id="BBB"
    )
    m = TableRead.read_market_by_condition_id(conn, ConditionId(cond))
    assert m is not None
    assert m.polymarket_yes_token_id == "AAA"
    assert m.polymarket_no_token_id == "BBB"

    # Both None -> no-op (no error, no change).
    TableWrite.update_market_polymarket_tokens(
        conn, polymarket_id=7, yes_token_id=None, no_token_id=None
    )
    m2 = TableRead.read_market_by_condition_id(conn, ConditionId(cond))
    assert m2 is not None
    assert (m2.polymarket_yes_token_id, m2.polymarket_no_token_id) == ("AAA", "BBB")
    conn.close()


# ----- cheap-path backfill on re-sync -----------------------------------------


def test_existing_updown_market_backfills_pm_tokens():
    conn = fresh_test_conn()
    cond = "0x" + secrets.token_hex(32)
    # Seed an existing market for pmid 555 with NULL upstream token ids
    # (the pre-fix state of every already-synced Up/Down window).
    _seed_market(conn, pmid=555, cond=cond, yes=None, no=None)
    seeded = TableRead.read_market_by_condition_id(conn, ConditionId(cond))
    assert seeded is not None and seeded.polymarket_yes_token_id is None

    # Re-sync the same upstream market → cheap path (already synced) backfills
    # the upstream token ids from the positional extraction.
    pm = {
        "id": 555,
        "conditionId": "0x" + "cd" * 32,
        "question": "BTC Up or Down window",
        "description": "d",
        "slug": "btc-updown-5m-1",
        "startDate": "2026-01-01T00:00:00Z",
        "endDate": "2026-01-02T00:00:00Z",
        "active": True,
        "closed": False,
        "tokens": [
            {"token_id": "111", "outcome": "Up"},
            {"token_id": "222", "outcome": "Down"},
        ],
    }
    result = create_polygon_market_if_does_not_exist(conn, pm, admin=None)
    assert result is None  # already synced — no on-chain prepare

    m = TableRead.read_market_by_condition_id(conn, ConditionId(cond))
    assert m is not None
    assert m.polymarket_yes_token_id == "111"
    assert m.polymarket_no_token_id == "222"
    conn.close()
