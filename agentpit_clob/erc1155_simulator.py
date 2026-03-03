import sqlite3


from web3 import Web3  # pip install web3

from .parse import normalize_eth_address, hex_u256_to_int
from agentpit_clob.db.table_utils import TableUtils


class ERC115Simulator:
    @staticmethod
    def mint(
        db: sqlite3.Connection, eth_address: str, asset_address: str, value: int
    ) -> None:
        norm_token_id = normalize_eth_address(eth_address)
        norm_key = normalize_eth_address(asset_address)

        if not isinstance(value, int):
            raise TypeError("value must be int")
        if value < 0 or value >= (1 << 256):
            raise ValueError("value must be a u256 (0 <= value < 2**256)")
        if value == 0:
            return

        # use context manager for atomic transaction; any exception rolls back
        with db:
            TableUtils.ensure_erc155_ownership_row(db, norm_token_id)
            ownership_map = TableUtils.load_erc155_ownership_map(db, norm_token_id)

            current = 0
            if norm_key in ownership_map:
                current = hex_u256_to_int(ownership_map[norm_key])

            new_value = current + value
            if new_value >= (1 << 256):
                raise OverflowError("u256 overflow")

            ownership_map[norm_key] = Web3.to_hex(new_value).lower()

            TableUtils.store_erc155_ownership_map(db, norm_token_id, ownership_map)

    @staticmethod
    def transfer(
        db: sqlite3.Connection,
        src_address: str,
        destination_address: str,
        value: int,
        asset_address: str,
    ) -> None:
        norm_src_token = normalize_eth_address(src_address)
        norm_dst_token = normalize_eth_address(destination_address)
        norm_key = normalize_eth_address(asset_address)

        if not isinstance(value, int):
            raise TypeError("value must be int")
        if value < 0 or value >= (1 << 256):
            raise ValueError("value must be a u256 (0 <= value < 2**256)")
        if value == 0 or norm_src_token == norm_dst_token:
            return

        # use context manager for atomic transaction; any exception rolls back
        with db:
            TableUtils.ensure_erc155_ownership_row(db, norm_src_token)
            TableUtils.ensure_erc155_ownership_row(db, norm_dst_token)
            src_map = TableUtils.load_erc155_ownership_map(db, norm_src_token)
            dst_map = TableUtils.load_erc155_ownership_map(db, norm_dst_token)

            raw_src_bal = src_map.get(norm_key)
            src_bal = 0 if raw_src_bal is None else hex_u256_to_int(raw_src_bal)

            if src_bal < value:
                raise ValueError(f"Insufficient balance: {src_bal} < {value}")

            raw_dst_bal = dst_map.get(norm_key)
            dst_bal = 0 if raw_dst_bal is None else hex_u256_to_int(raw_dst_bal)

            new_src = src_bal - value
            new_dst = dst_bal + value
            if new_dst >= (1 << 256):
                raise OverflowError("u256 overflow")

            src_map[norm_key] = Web3.to_hex(new_src).lower()
            dst_map[norm_key] = Web3.to_hex(new_dst).lower()

            TableUtils.store_erc155_ownership_map(db, norm_src_token, src_map)
            TableUtils.store_erc155_ownership_map(db, norm_dst_token, dst_map)
