import sqlite3
import json
import uuid
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from agentpit.utils.parse import normalize_eth_address, hex_u256_to_int, parse_32b_hex_private_key
from .table_utils import TableUtils
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
    def get_erc20_asset_ownership(
        db: sqlite3.Connection, eth_address: str, asset_address: str
    ) -> int:
        norm_eth = normalize_eth_address(eth_address)
        norm_asset = normalize_eth_address(asset_address)

        # Use shared strict loader; raises on any JSON/type corruption.
        ownership_map = TableUtils.load_erc20_ownership_map(db, norm_eth)

        # Exact canonical key
        if norm_asset in ownership_map:
            return hex_u256_to_int(ownership_map[norm_asset])

        # Fallback for older/non-canonical data, but still strict on value
        for k, v in ownership_map.items():
            nk = normalize_eth_address(k)
            if nk == norm_asset:
                return hex_u256_to_int(v)

        return 0

    @staticmethod
    def get_erc1155_asset_ownership(
        db: sqlite3.Connection, eth_address: str, token_id: str
    ) -> int:
        norm_eth = normalize_eth_address(eth_address)

        # Use shared strict loader; raises on any JSON/type corruption.
        ownership_map = TableUtils.load_erc1155_ownership_map(db, norm_eth)

        # For ERC1155, keys in the map are token IDs (opaque strings), not ETH addresses.
        if token_id in ownership_map:
            return hex_u256_to_int(ownership_map[token_id])

        return 0

    @staticmethod
    def get_private_key_for_api_key(
        db: sqlite3.Connection, api_key: str
    ) -> LocalAccount:
        row = db.execute(
            "SELECT ETH_PRIVATE_KEY FROM users WHERE API_KEY = ? LIMIT 1",
            (api_key,),
        ).fetchone()

        if row is not None:
            # Row exists: enforce "create once" => never rotate here.
            # parse_32b_hex_private_key raises on any error.
            existing_key = parse_32b_hex_private_key(row[0])
            return Account.from_key(existing_key)

        # No row: generate once and insert. Any DB / Web3 error propagates.
        acct: LocalAccount = Account.create()
        key_hex: str = Web3.to_hex(acct.key)
        user_id: str = str(uuid.uuid4())

        with db:
            db.execute(
                """
                INSERT INTO users (USER_ID, API_KEY, ETH_PRIVATE_KEY)
                VALUES (?, ?, ?)
                """,
                (user_id, api_key, key_hex),
            )

        return acct

    @staticmethod
    def get_eth_address_for_api_key_creating_if_needed(db: sqlite3.Connection, api_key: str) -> str:
        acct = TableRead.get_private_key_for_api_key(db, api_key)
        return acct.address

    @staticmethod
    def get_user_by_userid(db: sqlite3.Connection, user_id: str) -> User | None:
        """
        Fetch a user by their user_id.
        """
        row = db.execute(
            "SELECT API_KEY, ETH_PRIVATE_KEY FROM users WHERE USER_ID = ? LIMIT 1",
            (user_id,),
        ).fetchone()

        if row is None:
            return None

        api_key_val, eth_private_key = row
        existing_key = parse_32b_hex_private_key(eth_private_key)
        acct = Account.from_key(existing_key)

        return User(
            user_id=user_id,
            eth_key=acct,
            api_key=api_key_val
        )

    @staticmethod
    def get_user_by_api_key(db: sqlite3.Connection, api_key: str) -> User | None:
        """
        Fetch a user by their API key.
        """
        row = db.execute(
            "SELECT USER_ID, ETH_PRIVATE_KEY FROM users WHERE API_KEY = ? LIMIT 1",
            (api_key,),
        ).fetchone()

        if row is None:
            return None

        user_id_val, eth_private_key = row
        existing_key = parse_32b_hex_private_key(eth_private_key)
        acct = Account.from_key(existing_key)

        return User(
            user_id=user_id_val,
            eth_key=acct,
            api_key=api_key
        )

    @staticmethod
    def read_market(db: sqlite3.Connection, market_id: int) -> Market | None:
        """
        Fetch a single market by MARKET_ID.

        Returns:
            Market instance if found, otherwise None.
        """
        cur = db.execute(
            """
            SELECT MARKET_ID, POLYMARKET_ID, CONDITION_ID, QUESTION, DESCRIPTION, SLUG,
                   START_DATE, END_DATE, erc1155_TOKENS,
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

        market_id_val, polymarket_id, condition_id_str, question, description, slug, start_date, end_date, erc1155_tokens_json, market_state, resolved_outcome = row

        # JSON errors propagate; no exception handling here
        erc1155_tokens = json.loads(erc1155_tokens_json) if erc1155_tokens_json else []

        return Market(
            question=question,
            market_id=market_id_val,
            polymarket_id=polymarket_id,
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
            SELECT MARKET_ID, POLYMARKET_ID, CONDITION_ID, QUESTION, DESCRIPTION, SLUG,
                   START_DATE, END_DATE, erc1155_TOKENS,
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

        (market_id_val, polymarket_id,
         cond_id, question, description, slug, start_date, end_date, erc1155_tokens_json,
         market_state, resolved_outcome) = row

        # JSON errors propagate; no exception handling here
        erc1155_tokens = json.loads(erc1155_tokens_json) if erc1155_tokens_json else []

        return Market(
            question=question,
            market_id=market_id_val,
            polymarket_id=polymarket_id,
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
                   CONDITION_ID,
                   QUESTION,
                   DESCRIPTION,
                   SLUG,
                   erc1155_TOKENS,
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
                   CONDITION_ID,
                   QUESTION,
                   DESCRIPTION,
                   SLUG,
                   erc1155_TOKENS,
                   COALESCE(MARKET_STATE, 'DRAFT') as MARKET_STATE,
                   RESOLVED_OUTCOME,
                   START_DATE,
                   END_DATE
            FROM markets
            ORDER BY MARKET_ID LIMIT ?
            OFFSET ?
            """,
            (limit, offset),
        )

        markets: list[Market] = []
        for row in cur.fetchall():
            (
                market_id_val,
                polymarket_id,
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
            SELECT transaction_id, timestamp, transaction_type, market_id, details
            FROM transactions
            WHERE api_key = ?
            ORDER BY timestamp DESC
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
