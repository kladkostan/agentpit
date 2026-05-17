import sqlite3
import json
import uuid
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from agentpit.utils.parse import parse_32b_hex_private_key
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState
from agentpit.datastructures.user import User
from ..datastructures.condition_id import ConditionId


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
        "API_KEY, ONBOARDED_AT, CREATED_AT"
    )

    @staticmethod
    def _row_to_user(row: tuple) -> User:
        (user_id, email, handle, eth_address, eth_private_key,
         api_key, onboarded_at, created_at) = row
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
        """
        Fetch a single market by MARKET_ID.

        Returns:
            Market instance if found, otherwise None.
        """
        cur = db.execute(
            """
             SELECT MARKET_ID, POLYMARKET_ID, POLYMARKET_CONDITION_ID, CONDITION_ID,
                   QUESTION, DESCRIPTION, SLUG,
                   START_DATE, END_DATE, ERC1155_TOKENS,
                   COALESCE(MARKET_STATE, 'DRAFT') as MARKET_STATE,
                   RESOLVED_OUTCOME
            FROM markets
            WHERE MARKET_ID = ?
            """,
            (market_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        (market_id_val, polymarket_id, polymarket_condition_id, condition_id_str,
         question, description, slug, start_date, end_date,
         erc1155_tokens_json, market_state, resolved_outcome) = row

        erc1155_tokens = json.loads(erc1155_tokens_json) if erc1155_tokens_json else []

        return Market(
            question=question,
            market_id=market_id_val,
            polymarket_id=polymarket_id,
            polymarket_condition_id=polymarket_condition_id,
            condition_id=ConditionId(condition_id_str),
            description=description,
            slug=slug,
            start_date=start_date,
            end_date=end_date,
            erc1155_tokens=erc1155_tokens,
            market_state=MarketState(market_state),
            resolved_outcome=resolved_outcome,
        )

    @staticmethod
    def read_market_by_condition_id(db: sqlite3.Connection, condition_id: ConditionId) -> Market | None:
        """
        Fetch a single market by CONDITION_ID.

        Returns:
            Market instance if found, otherwise None.
        """
        cur = db.execute(
            """
             SELECT MARKET_ID, POLYMARKET_ID, POLYMARKET_CONDITION_ID, CONDITION_ID,
                   QUESTION, DESCRIPTION, SLUG,
                   START_DATE, END_DATE, ERC1155_TOKENS,
                   COALESCE(MARKET_STATE, 'DRAFT') as MARKET_STATE,
                   RESOLVED_OUTCOME
            FROM markets
            WHERE CONDITION_ID = ?
            """,
            (condition_id.value,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        (market_id_val, polymarket_id, polymarket_condition_id,
         cond_id, question, description, slug, start_date, end_date,
         erc1155_tokens_json, market_state, resolved_outcome) = row

        erc1155_tokens = json.loads(erc1155_tokens_json) if erc1155_tokens_json else []

        return Market(
            question=question,
            market_id=market_id_val,
            polymarket_id=polymarket_id,
            polymarket_condition_id=polymarket_condition_id,
            condition_id=ConditionId(cond_id),
            description=description,
            slug=slug,
            start_date=start_date,
            end_date=end_date,
            erc1155_tokens=erc1155_tokens,
            market_state=MarketState(market_state),
            resolved_outcome=resolved_outcome,
        )

    @staticmethod
    def list_all_markets(db: sqlite3.Connection) -> list[Market]:
        """
        Fetch all markets from the database without pagination.

        Args:
            db: Database connection

        Returns:
            List of all Market instances
        """
        cur = db.execute(
            """
            SELECT MARKET_ID,
                   POLYMARKET_ID,
                   POLYMARKET_CONDITION_ID,
                   CONDITION_ID,
                   QUESTION,
                   DESCRIPTION,
                   SLUG,
                   ERC1155_TOKENS,
                   COALESCE(MARKET_STATE, 'DRAFT') as MARKET_STATE,
                   RESOLVED_OUTCOME,
                   START_DATE,
                   END_DATE
            FROM markets
            ORDER BY MARKET_ID
            """
        )

        markets: list[Market] = []
        for row in cur.fetchall():
            (
                market_id_val,
                polymarket_id,
                polymarket_condition_id,
                condition_id_str,
                question,
                description,
                slug,
                erc1155_tokens_json,
                market_state,
                resolved_outcome,
                start_date,
                end_date,
            ) = row
            erc1155_tokens = json.loads(erc1155_tokens_json) if erc1155_tokens_json else []
            markets.append(
                Market(
                    question=question,
                    market_id=market_id_val,
                    polymarket_id=polymarket_id,
                    polymarket_condition_id=polymarket_condition_id,
                    condition_id=ConditionId(condition_id_str),
                    description=description,
                    slug=slug,
                    erc1155_tokens=erc1155_tokens,
                    market_state=MarketState(market_state),
                    resolved_outcome=resolved_outcome,
                    start_date=start_date,
                    end_date=end_date
                )
            )

        return markets

    @staticmethod
    def list_markets(db: sqlite3.Connection, limit: int = 100, offset: int = 0) -> tuple[list[Market], int]:
        """
        Fetch a paginated list of markets.

        Args:
            db: Database connection
            limit: Maximum number of markets to return
            offset: Number of markets to skip

        Returns:
            Tuple of (list of Market instances, total count)
        """
        # Get total count
        count_cur = db.execute("SELECT COUNT(*) FROM markets")
        total = count_cur.fetchone()[0]

        # Get paginated markets including start/end dates
        cur = db.execute(
            """
            SELECT MARKET_ID,
                   POLYMARKET_ID,
                   POLYMARKET_CONDITION_ID,
                   CONDITION_ID,
                   QUESTION,
                   DESCRIPTION,
                   SLUG,
                   ERC1155_TOKENS,
                   COALESCE(MARKET_STATE, 'DRAFT') as MARKET_STATE,
                   RESOLVED_OUTCOME,
                   START_DATE,
                   END_DATE
            FROM markets
            ORDER BY MARKET_ID DESC LIMIT ?
            OFFSET ?
            """,
            (limit, offset),
        )

        markets: list[Market] = []
        for row in cur.fetchall():
            (
                market_id_val,
                polymarket_id,
                polymarket_condition_id,
                condition_id_str,
                question,
                description,
                slug,
                erc1155_tokens_json,
                market_state,
                resolved_outcome,
                start_date,
                end_date,
            ) = row
            erc1155_tokens = json.loads(erc1155_tokens_json) if erc1155_tokens_json else []
            markets.append(
                Market(
                    question=question,
                    market_id=market_id_val,
                    polymarket_id=polymarket_id,
                    polymarket_condition_id=polymarket_condition_id,
                    condition_id=ConditionId(condition_id_str),
                    description=description,
                    slug=slug,
                    erc1155_tokens=erc1155_tokens,
                    market_state=MarketState(market_state),
                    resolved_outcome=resolved_outcome,
                    start_date=start_date,
                    end_date=end_date
                )
            )

        return markets, total

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
            transactions.append({
                "transaction_id": row[0],
                "timestamp": row[1],
                "transaction_type": row[2],
                "market_id": row[3],
                "details": json.loads(row[4]) if row[4] else {},
            })
        return transactions
