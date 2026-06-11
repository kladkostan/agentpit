import secrets

import agentpit.polymarket.polymarket_sync as sync
from agentpit.datastructures.condition_id import ConditionId
from tests.db_helpers import fresh_test_db


def _pm_market() -> dict:
    return {
        "id": int(secrets.token_hex(4), 16),
        "conditionId": "0x" + secrets.token_hex(32),
        "question": f"Skip-known {secrets.token_hex(4)}?",
        "description": "d",
        "slug": f"skip-known-{secrets.token_hex(4)}",
        "startDate": "2020-01-01T00:00:00Z",
        "endDate": "2020-01-02T00:00:00Z",
        "active": True,
        "closed": False,
        "tokens": [
            {"token_id": str(int(secrets.token_hex(8), 16)), "outcome": "Yes"},
            {"token_id": str(int(secrets.token_hex(8), 16)), "outcome": "No"},
        ],
    }


def test_known_market_skips_on_chain_prepare(monkeypatch):
    db = fresh_test_db()
    pm = _pm_market()

    calls = {"n": 0}

    def spy(admin, question, labels):
        calls["n"] += 1
        # deterministic fake condition/token ids — no chain needed
        cid = ConditionId("0x" + secrets.token_hex(32))
        toks = [(str(int(secrets.token_hex(8), 16)), labels[0]),
                (str(int(secrets.token_hex(8), 16)), labels[1])]
        return cid, toks

    monkeypatch.setattr(sync, "prepare_market_on_chain", spy)

    with db.write() as conn:
        first = sync.create_polygon_market_if_does_not_exist(conn, pm, admin=None)
        assert first is not None
        assert calls["n"] == 1  # new market -> prepared once

        second = sync.create_polygon_market_if_does_not_exist(conn, pm, admin=None)
        assert second is None  # already synced
        assert calls["n"] == 1  # NOT prepared again — no on-chain work
