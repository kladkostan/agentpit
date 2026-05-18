import sqlite3
import json
import uuid
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from agentpit.utils.parse import parse_32b_hex_private_key
from agentpit.datastructures.event import Event
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState
from agentpit.datastructures.user import User
from ..datastructures.condition_id import ConditionId


_MARKET_COLS = (
    "MARKET_ID, POLYMARKET_ID, POLYMARKET_CONDITION_ID, CONDITION_ID, "
    "QUESTION, DESCRIPTION, SLUG, "
    "START_DATE, END_DATE, ERC1155_TOKENS, "
    "COALESCE(MARKET_STATE, 'DRAFT') as MARKET_STATE, "
    "RESOLVED_OUTCOME, "
    "EVENT_ID, OUTCOME_LABEL, ICON_URL, "
    "POLYMARKET_YES_TOKEN_ID, POLYMARKET_NO_TOKEN_ID"
)


def _row_to_market(row: tuple) -> Market:
    (
        market_id,
        polymarket_id,
        polymarket_condition_id,
        condition_id_str,
        question,
        description,
        slug,
        start_date,
        end_date,
        erc1155_tokens_json,
        market_state,
        resolved_outcome,
        event_id,
        outcome_label,
        icon_url,
        polymarket_yes_token_id,
        polymarket_no_token_id,
    ) = row
    erc1155_tokens = json.loads(erc1155_tokens_json) if erc1155_tokens_json else []
    return Market(
        question=question,
        market_id=market_id,
        polymarket_id=polymarket_id,
        polymarket_condition_id=polymarket_condition_id,
        polymarket_yes_token_id=polymarket_yes_token_id,
        polymarket_no_token_id=polymarket_no_token_id,
        condition_id=ConditionId(condition_id_str),
        description=description,
        slug=slug,
        start_date=start_date,
        end_date=end_date,
        erc1155_tokens=erc1155_tokens,
        market_state=MarketState(market_state),
        resolved_outcome=resolved_outcome,
        event_id=event_id,
        outcome_label=outcome_label,
        icon_url=icon_url,
    )


class TableRead:
    @staticmethod
    def read_condition_id_by_polymarket_id(
        db: sqlite3.Connection, polymarket_id: int
    ) -> int | None:
        """Return MARKET_ID for a Polymarket id, or None if not found."""
        row = db.execute(
            "SELECT CONDITION_ID FROM markets WHERE POLYMARKET_ID = ? LIMIT 1",
            (polymarket_id,),
        ).fetchone()
        return ConditionId(str(row[0])) if row is not None else None

    @staticmethod
    def market_exists_by_polymarket_id(
        db: sqlite3.Connection, polymarket_id: int
    ) -> bool:
        """Return True if a market row exists for the given Polymarket id."""
        row = db.execute(
            "SELECT 1 FROM markets WHERE POLYMARKET_ID = ? LIMIT 1",
            (polymarket_id,),
        ).fetchone()
        return row is not None

    @staticmethod
    def get_market_status_by_condition_id(
        db: sqlite3.Connection, condition_id: str
    ) -> tuple[MarketState, int | None] | None:
        """
        Fetch the market state and resolved outcome by CONDITION_ID.

        Returns:
            Tuple of (MarketState, resolved_outcome) if found, otherwise None.
        """
        row = db.execute(
            "SELECT COALESCE(MARKET_STATE, 'DRAFT'), RESOLVED_OUTCOME FROM markets WHERE CONDITION_ID = ? LIMIT 1",
            (condition_id,),
        ).fetchone()

        if row is None:
            return None

        return MarketState(row[0]), row[1]

    @staticmethod
    def get_market_state(
        db: sqlite3.Connection, condition_id: ConditionId
    ) -> MarketState | None:
        """
        Fetch the market state by CONDITION_ID.

        Returns:
            MarketState if found, otherwise None.
        """
        row = db.execute(
            "SELECT COALESCE(MARKET_STATE, 'DRAFT') FROM markets WHERE CONDITION_ID = ? LIMIT 1",
            (condition_id.value,),
        ).fetchone()

        if row is None:
            return None

        return MarketState(row[0])

    @staticmethod
    def get_private_key_for_api_key(
        db: sqlite3.Connection, api_key: str
    ) -> LocalAccount | None:
        """Return the eth account for an API key, or None if no user matches.

        Read-only — never inserts. Anonymous user creation is gone now that auth
        is required: a request with an unknown api_key resolves to None.
        """
        row = db.execute(
            "SELECT ETH_PRIVATE_KEY FROM users WHERE API_KEY = ? LIMIT 1",
            (api_key,),
        ).fetchone()
        if row is None:
            return None
        existing_key = parse_32b_hex_private_key(row[0])
        return Account.from_key(existing_key)

    @staticmethod
    def get_eth_address_for_api_key(db: sqlite3.Connection, api_key: str) -> str | None:
        """Return the eth address for an API key, or None if no user matches."""
        row = db.execute(
            "SELECT ETH_ADDRESS FROM users WHERE API_KEY = ? LIMIT 1",
            (api_key,),
        ).fetchone()
        return row[0] if row else None

    @staticmethod
    def get_agent_by_id(db: sqlite3.Connection, agent_id: str) -> dict | None:
        """
        Fetch an agent by AGENT_ID.
        Returns a dict with agent_id, personality_id, state, history, todo or None.
        """
        row = db.execute(
            "SELECT PERSONALITY, STATE, HISTORY, TODO FROM agents WHERE AGENT_ID = ? LIMIT 1",
            (agent_id,),
        ).fetchone()

        if row is None:
            return None

        personality, state_json, history_json, todo_json = row
        return {
            "agent_id": agent_id,
            "personality_id": personality,
            "state": json.loads(state_json),
            "history": json.loads(history_json),
            "todo": json.loads(todo_json),
        }

    _USER_COLS = (
        "USER_ID, EMAIL, HANDLE, ETH_ADDRESS, ETH_PRIVATE_KEY, "
        "API_KEY, ONBOARDED_AT, CREATED_AT, IS_BOT"
    )

    @staticmethod
    def _row_to_user(row: tuple) -> User:
        (
            user_id,
            email,
            handle,
            eth_address,
            eth_private_key,
            api_key,
            onboarded_at,
            created_at,
            is_bot,
        ) = row
        existing_key = parse_32b_hex_private_key(eth_private_key)
        acct = Account.from_key(existing_key)
        return User(
            user_id=user_id,
            email=email,
            eth_key=acct,
            eth_address=eth_address,
            api_key=api_key,
            handle=handle,
            onboarded_at=onboarded_at,
            created_at=created_at if created_at is not None else 0,
            is_bot=bool(is_bot),
        )

    @staticmethod
    def get_user_by_userid(db: sqlite3.Connection, user_id: str) -> User | None:
        row = db.execute(
            f"SELECT {TableRead._USER_COLS} FROM users WHERE USER_ID = ? LIMIT 1",
            (user_id,),
        ).fetchone()
        return TableRead._row_to_user(row) if row else None

    @staticmethod
    def get_user_by_api_key(db: sqlite3.Connection, api_key: str) -> User | None:
        row = db.execute(
            f"SELECT {TableRead._USER_COLS} FROM users WHERE API_KEY = ? LIMIT 1",
            (api_key,),
        ).fetchone()
        return TableRead._row_to_user(row) if row else None

    @staticmethod
    def get_user_by_email(db: sqlite3.Connection, email: str) -> User | None:
        row = db.execute(
            f"SELECT {TableRead._USER_COLS} FROM users WHERE EMAIL = ? LIMIT 1",
            (email,),
        ).fetchone()
        return TableRead._row_to_user(row) if row else None

    @staticmethod
    def get_password_hash_by_email(db: sqlite3.Connection, email: str) -> str | None:
        """Used by login — returns the bcrypt hash so the service can verify."""
        row = db.execute(
            "SELECT PASSWORD_HASH FROM users WHERE EMAIL = ? LIMIT 1",
            (email,),
        ).fetchone()
        return row[0] if row else None

    @staticmethod
    def read_market(db: sqlite3.Connection, market_id: int) -> Market | None:
        row = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets WHERE MARKET_ID = ?",
            (market_id,),
        ).fetchone()
        return _row_to_market(row) if row else None

    @staticmethod
    def read_market_by_condition_id(
        db: sqlite3.Connection, condition_id: ConditionId
    ) -> Market | None:
        row = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets WHERE CONDITION_ID = ?",
            (condition_id.value,),
        ).fetchone()
        return _row_to_market(row) if row else None

    @staticmethod
    def list_all_markets(db: sqlite3.Connection) -> list[Market]:
        cur = db.execute(f"SELECT {_MARKET_COLS} FROM markets ORDER BY MARKET_ID")
        return [_row_to_market(row) for row in cur.fetchall()]

    @staticmethod
    def list_markets(
        db: sqlite3.Connection, limit: int = 100, offset: int = 0
    ) -> tuple[list[Market], int]:
        total = db.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
        cur = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            "ORDER BY MARKET_ID DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        markets = [_row_to_market(row) for row in cur.fetchall()]
        return markets, total

    _EVENT_COLS = (
        "EVENT_ID, SLUG, TITLE, DESCRIPTION, ICON_URL, CATEGORY, "
        "START_DATE, END_DATE, POLYMARKET_EVENT_ID"
    )

    @staticmethod
    def _row_to_event(row: tuple) -> Event:
        (
            event_id,
            slug,
            title,
            description,
            icon_url,
            category,
            start_date,
            end_date,
            polymarket_event_id,
        ) = row
        return Event(
            event_id=event_id,
            slug=slug,
            title=title,
            description=description or "",
            icon_url=icon_url,
            category=category,
            start_date=start_date,
            end_date=end_date,
            polymarket_event_id=polymarket_event_id,
        )

    @staticmethod
    def get_event_by_id(db: sqlite3.Connection, event_id: int) -> Event | None:
        row = db.execute(
            f"SELECT {TableRead._EVENT_COLS} FROM events WHERE EVENT_ID = ? LIMIT 1",
            (event_id,),
        ).fetchone()
        return TableRead._row_to_event(row) if row else None

    @staticmethod
    def get_event_by_slug(db: sqlite3.Connection, slug: str) -> Event | None:
        row = db.execute(
            f"SELECT {TableRead._EVENT_COLS} FROM events WHERE SLUG = ? LIMIT 1",
            (slug,),
        ).fetchone()
        return TableRead._row_to_event(row) if row else None

    @staticmethod
    def get_event_by_polymarket_event_id(
        db: sqlite3.Connection, polymarket_event_id: str
    ) -> Event | None:
        row = db.execute(
            f"SELECT {TableRead._EVENT_COLS} FROM events "
            "WHERE POLYMARKET_EVENT_ID = ? LIMIT 1",
            (polymarket_event_id,),
        ).fetchone()
        return TableRead._row_to_event(row) if row else None

    @staticmethod
    def list_markets_by_event_id(db: sqlite3.Connection, event_id: int) -> list[Market]:
        cur = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            "WHERE EVENT_ID = ? ORDER BY MARKET_ID",
            (event_id,),
        )
        return [_row_to_market(row) for row in cur.fetchall()]

    @staticmethod
    def list_events_with_markets(
        db: sqlite3.Connection, limit: int = 100, offset: int = 0
    ) -> tuple[list[tuple[Event, list[Market]]], int]:
        """Return events ordered by newest, each paired with its child markets.

        Used by the home page: every market belongs to an event, so this is
        the primary listing query. One query for the event page + one for
        all member markets (bucketed in Python) — no N+1.
        """
        total = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        events_cur = db.execute(
            f"SELECT {TableRead._EVENT_COLS} FROM events "
            "ORDER BY EVENT_ID DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        events = [TableRead._row_to_event(r) for r in events_cur.fetchall()]
        if not events:
            return [], total

        ids = [ev.event_id for ev in events]
        placeholders = ",".join("?" * len(ids))
        markets_cur = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            f"WHERE EVENT_ID IN ({placeholders}) ORDER BY EVENT_ID, MARKET_ID",
            ids,
        )
        by_event: dict[int, list[Market]] = {eid: [] for eid in ids}
        for row in markets_cur.fetchall():
            market = _row_to_market(row)
            assert market.event_id is not None  # guaranteed by WHERE clause
            by_event[market.event_id].append(market)
        return [(ev, by_event[ev.event_id]) for ev in events], total

    @staticmethod
    def list_orphan_markets(db: sqlite3.Connection) -> list[Market]:
        """Markets with no EVENT_ID — used by the auto-wrap singleton helper."""
        cur = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            "WHERE EVENT_ID IS NULL ORDER BY MARKET_ID"
        )
        return [_row_to_market(row) for row in cur.fetchall()]

    @staticmethod
    def get_transaction_history(db: sqlite3.Connection, api_key: str) -> list:
        """
        Fetch the transaction history for a given API key.
        """
        cursor = db.execute(
            """
            SELECT TRANSACTION_ID, TIMESTAMP, TRANSACTION_TYPE, MARKET_ID, DETAILS
            FROM transactions
            WHERE API_KEY = ?
            ORDER BY TIMESTAMP DESC
            """,
            (api_key,),
        )
        transactions = []
        for row in cursor.fetchall():
            transactions.append(
                {
                    "transaction_id": row[0],
                    "timestamp": row[1],
                    "transaction_type": row[2],
                    "market_id": row[3],
                    "details": json.loads(row[4]) if row[4] else {},
                }
            )
        return transactions
