"""We stop transacting from someone's wallet unless they asked us to.

A redeem is settlement rather than a decision, which is the case for doing it
automatically. It is outweighed by the wallet being theirs — the same wallet we
now hand them the key to.
"""

from __future__ import annotations

import json
import secrets
from unittest.mock import MagicMock

import pytest

from agentpit.db.table_write import TableWrite
from agentpit.polymarket.polymarket_sync import auto_redeem_resolved_markets
from agentpit.services.position_service import PositionService
from tests.db_helpers import fresh_test_db


@pytest.fixture()
def db_with_a_won_position(monkeypatch):
    """Builder for `(db, admin)`: a RESOLVED market with one holder of the
    winning token.

    `db` is a real DbSession carrying the market, a user, and the trade row
    `list_participant_api_keys_for_market` needs to find them. `admin` is a
    MagicMock whose `ctf_balance` reports a positive balance for the winning
    token and zero for the loser.

    `PositionService.redeem` is stubbed to a no-op: the on-chain send/sign
    plumbing it drives is already covered in tests/onchain, and a bare
    MagicMock admin can't survive a real `eth_account.sign_transaction` call.
    This keeps the test focused on what `auto_redeem_resolved_markets` itself
    decides -- whether to call redeem at all -- not on the transaction below it.
    """

    def _build(*, auto_redeem: bool):
        db = fresh_test_db()
        yes_token = str(int.from_bytes(secrets.token_bytes(8), "big"))
        no_token = str(int.from_bytes(secrets.token_bytes(8), "big"))

        with db.write() as conn:
            row = conn.execute(
                "INSERT INTO markets (CONDITION_ID, QUESTION, SLUG, DESCRIPTION, "
                "ERC1155_TOKENS, START_DATE, MARKET_STATE, RESOLVED_OUTCOME) "
                "VALUES (%s, 'Already won?', %s, 'd', %s, 100, 'RESOLVED', 0) "
                "RETURNING MARKET_ID",
                (
                    f"0x{secrets.token_hex(32)}",
                    f"already-won-{secrets.token_hex(4)}",
                    json.dumps([[yes_token, "YES"], [no_token, "NO"]]),
                ),
            ).fetchone()
            market_id = row["MARKET_ID"]

            user_id, _acct, api_key = TableWrite.create_user(
                conn,
                email=f"redeem-{secrets.token_hex(4)}@example.com",
                password_hash="x",
                handle=None,
            )
            TableWrite.set_auto_redeem(conn, user_id, auto_redeem)

            conn.execute(
                "INSERT INTO trades (TRADE_ID, ASSET_ID, TAKER_API_KEY, "
                "MAKER_API_KEY, STATUS, MATCH_TIME) VALUES (%s, %s, %s, %s, "
                "'MATCHED', 1)",
                (secrets.token_hex(8), yes_token, api_key, api_key),
            )

        assert market_id  # sanity: the market row was created

        def _ctf_balance(_address, token_id):
            return 100 if str(token_id) == yes_token else 0

        admin = MagicMock()
        admin.ctf_balance.side_effect = _ctf_balance
        monkeypatch.setattr(
            PositionService, "redeem", lambda self, user, market_id: None
        )

        return db, admin

    return _build


def test_an_account_that_has_not_opted_in_is_skipped(db_with_a_won_position):
    db, admin = db_with_a_won_position(auto_redeem=False)
    assert auto_redeem_resolved_markets(db, admin) == 0


def test_an_account_that_opted_in_is_claimed_for(db_with_a_won_position):
    db, admin = db_with_a_won_position(auto_redeem=True)
    assert auto_redeem_resolved_markets(db, admin) == 1


def test_no_gas_is_ever_sent(db_with_a_won_position):
    """Task 1 removed the top-up; this is the behavioural proof, not a grep."""
    db, admin = db_with_a_won_position(auto_redeem=True)
    auto_redeem_resolved_markets(db, admin)
    assert not admin.fund_gas.called
