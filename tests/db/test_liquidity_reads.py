"""Tests for the liquidity-engine read helpers added in Phase 5b Task 4."""

from agentpit.auth.passwords import hash_password
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from tests.db_helpers import fresh_test_conn


def _make_user(conn, email):
    uid, acct, api_key = TableWrite.create_user(
        conn, email=email, password_hash=hash_password("pw12pw12pw12"), handle=None
    )
    return uid, api_key


def _hex32(seed: str) -> str:
    """Return a 32-byte hex condition_id derived from a short label."""
    payload = seed.encode().hex().ljust(64, "0")[:64]
    return "0x" + payload


def _make_market(conn, *, question: str, cond_id: str, polymarket_condition_id=None,
                 state: MarketState = MarketState.DRAFT):
    """Insert a market via CreateMarketRequest, then force state/polymarket_condition_id."""
    request = CreateMarketRequest(
        question=question,
        description=f"desc for {question}",
        erc1155_tokens=[(f"{cond_id}-yes", "Yes"), (f"{cond_id}-no", "No")],
        slug=question.lower().replace(" ", "-").replace("?", ""),
        condition_id=ConditionId(cond_id),
        state=MarketState.DRAFT,
        polymarket_condition_id=polymarket_condition_id,
    )
    market = TableWrite.create_market(conn, request, is_polygon_market=False)
    # Force desired state via direct UPDATE (create_market sets state from request,
    # but we use DRAFT first so we can control each case explicitly below).
    if state != MarketState.DRAFT or polymarket_condition_id is not None:
        conn.execute(
            "UPDATE markets SET MARKET_STATE = %s, POLYMARKET_CONDITION_ID = %s "
            "WHERE MARKET_ID = %s",
            (state.value, polymarket_condition_id, market.market_id),
        )
    return market


# ---------------------------------------------------------------------------
# list_bot_users
# ---------------------------------------------------------------------------


def test_list_bot_users_only_bots():
    conn = fresh_test_conn()
    _make_user(conn, "human@x.com")
    _uid, bot_key = _make_user(conn, "bot@x.com")
    TableWrite.mark_user_as_bot(conn, bot_key)
    bots = TableRead.list_bot_users(conn)
    assert [u.email for u in bots] == ["bot@x.com"]
    assert bots[0].is_bot is True
    assert bots[0].eth_key is not None


def test_list_bot_users_empty_when_no_bots():
    conn = fresh_test_conn()
    _make_user(conn, "regular@x.com")
    assert TableRead.list_bot_users(conn) == []


def test_list_bot_users_returns_multiple_bots():
    conn = fresh_test_conn()
    _, k1 = _make_user(conn, "bot1@x.com")
    _, k2 = _make_user(conn, "bot2@x.com")
    _make_user(conn, "human@x.com")
    TableWrite.mark_user_as_bot(conn, k1)
    TableWrite.mark_user_as_bot(conn, k2)
    bots = TableRead.list_bot_users(conn)
    assert len(bots) == 2
    assert all(b.is_bot for b in bots)


# ---------------------------------------------------------------------------
# list_active_synced_markets
# ---------------------------------------------------------------------------


def test_list_active_synced_markets_filters():
    conn = fresh_test_conn()

    # (a) ACTIVE + has polymarket_condition_id -> expected
    m_a = _make_market(
        conn,
        question="Active synced?",
        cond_id=_hex32("active-synced"),
        polymarket_condition_id="0xdeadbeef" + "0" * 56,
        state=MarketState.ACTIVE,
    )

    # (b) ACTIVE but NO polymarket_condition_id -> excluded
    _make_market(
        conn,
        question="Active unsynced?",
        cond_id=_hex32("active-unsynced"),
        polymarket_condition_id=None,
        state=MarketState.ACTIVE,
    )

    # (c) RESOLVED + has polymarket_condition_id -> excluded
    _make_market(
        conn,
        question="Resolved synced?",
        cond_id=_hex32("resolved-synced"),
        polymarket_condition_id="0xcafebabe" + "0" * 56,
        state=MarketState.RESOLVED,
    )

    got = TableRead.list_active_synced_markets(conn)
    assert len(got) == 1
    assert got[0].market_id == m_a.market_id
    assert got[0].market_state == MarketState.ACTIVE
    assert got[0].polymarket_condition_id is not None


def test_list_active_synced_markets_empty_when_none_qualify():
    conn = fresh_test_conn()
    # Only a DRAFT market — should not appear
    _make_market(
        conn,
        question="Draft?",
        cond_id=_hex32("draft-market"),
        polymarket_condition_id="0xaabbccdd" + "0" * 56,
        state=MarketState.DRAFT,
    )
    assert TableRead.list_active_synced_markets(conn) == []


def test_list_active_synced_markets_ordered_by_market_id():
    conn = fresh_test_conn()
    pcid_a = "0x" + "aa" * 32
    pcid_b = "0x" + "bb" * 32
    m1 = _make_market(
        conn,
        question="First?",
        cond_id=_hex32("first"),
        polymarket_condition_id=pcid_a,
        state=MarketState.ACTIVE,
    )
    m2 = _make_market(
        conn,
        question="Second?",
        cond_id=_hex32("second"),
        polymarket_condition_id=pcid_b,
        state=MarketState.ACTIVE,
    )
    got = TableRead.list_active_synced_markets(conn)
    assert [m.market_id for m in got] == sorted([m1.market_id, m2.market_id])
