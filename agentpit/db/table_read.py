import sqlite3
import json
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from agentpit.utils.parse import normalize_eth_address, hex_u256_to_int, parse_32b_hex_private_key
from .table_utils import TableUtils
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState


class TableRead:
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
    def get_erc155_asset_ownership(
        db: sqlite3.Connection, eth_address: str, token_id: str
    ) -> int:
        norm_eth = normalize_eth_address(eth_address)

        # Use shared strict loader; raises on any JSON/type corruption.
        ownership_map = TableUtils.load_erc155_ownership_map(db, norm_eth)

        # For ERC1155, keys in the map are token IDs (opaque strings), not ETH addresses.
        if token_id in ownership_map:
            return hex_u256_to_int(ownership_map[token_id])

        return 0

    @staticmethod
    def get_private_key_for_api_key(
        db: sqlite3.Connection, api_key: str
    ) -> LocalAccount:
        row = db.execute(
            "SELECT ETH_PRIVATE_KEY FROM keys WHERE API_KEY = ? LIMIT 1",
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

        with db:
            db.execute(
                """
                INSERT INTO keys (API_KEY, ETH_PRIVATE_KEY)
                VALUES (?, ?)
                """,
                (api_key, key_hex),
            )

        return acct

    @staticmethod
    def get_eth_address_for_api_key(db: sqlite3.Connection, api_key: str) -> str:
        acct = TableRead.get_private_key_for_api_key(db, api_key)
        return acct.address

    @staticmethod
    def read_market(db: sqlite3.Connection, market_id: int) -> Market | None:
        """
        Fetch a single market by MARKET_ID.

        Returns:
            Market instance if found, otherwise None.
        """
        cur = db.execute(
            """
            SELECT MARKET_ID, CONDITION_ID, QUESTION, DESCRIPTION, ERC155_TOKENS,
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

        market_id_val, condition_id, question, description, erc155_tokens_json, market_state, resolved_outcome = row

        # JSON errors propagate; no exception handling here
        erc155_tokens = json.loads(erc155_tokens_json) if erc155_tokens_json else []

        return Market(
            question=question,
            market_id=market_id_val,
            condition_id=condition_id,
            description=description,
            erc155_tokens=erc155_tokens,
            market_state=MarketState(market_state),
            resolved_outcome=resolved_outcome,
        )

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

        # Get paginated markets
        cur = db.execute(
            """
            SELECT MARKET_ID, CONDITION_ID, QUESTION, DESCRIPTION, ERC155_TOKENS,
                   COALESCE(MARKET_STATE, 'DRAFT') as MARKET_STATE,
                   RESOLVED_OUTCOME
            FROM markets
            ORDER BY MARKET_ID
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )

        markets = []
        for row in cur.fetchall():
            market_id_val, condition_id, question, description, erc155_tokens_json, market_state, resolved_outcome = row
            erc155_tokens = json.loads(erc155_tokens_json) if erc155_tokens_json else []
            markets.append(Market(
                question=question,
                market_id=market_id_val,
                condition_id=condition_id,
                description=description,
                erc155_tokens=erc155_tokens,
                market_state=MarketState(market_state),
                resolved_outcome=resolved_outcome,
            ))

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

