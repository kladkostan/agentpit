import sqlite3
import json
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from agentpit.utils.parse import normalize_eth_address, hex_u256_to_int, parse_32b_hex_private_key
from .table_utils import TableUtils
from agentpit.datastructures.market import Market


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
            SELECT MARKET_ID, CONDITION_ID, DESCRIPTION, ERC155_TOKENS
            FROM markets
            WHERE MARKET_ID = ?
            """,
            (market_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        market_id_val, condition_id, description, erc155_tokens_json = row

        # JSON errors propagate; no exception handling here
        erc155_tokens = json.loads(erc155_tokens_json) if erc155_tokens_json else []

        return Market(
            market_id=market_id_val,
            condition_id=condition_id,
            description=description,
            erc155_tokens=erc155_tokens,
        )
