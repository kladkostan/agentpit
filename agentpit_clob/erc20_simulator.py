from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3  # pip install web3
import json
import sqlite3

from agentpit_clob.tables import Tables


class Erc20Simulator:
    @staticmethod
    def mint(
            db: sqlite3.Connection, eth_address: str, asset_address: str, value: int
    ) -> None:
        norm_eth = Tables._normalize_eth_address(eth_address)
        norm_asset = Tables._normalize_eth_address(asset_address)
        if norm_eth is None or norm_asset is None:
            raise ValueError("Invalid eth_address or asset_address")

        if not isinstance(value, int):
            raise TypeError("value must be int")
        if value < 0 or value >= (1 << 256):
            raise ValueError("value must be a u256 (0 <= value < 2**256)")

        # Ensure row exists.
        db.execute(
            """
            INSERT INTO token_ownership (ETH_ADDRESS, OWNERSHIP)
            VALUES (?, ?) ON CONFLICT(ETH_ADDRESS) DO NOTHING
            """,
            (norm_eth, "{}"),
        )

        row = db.execute(
            "SELECT OWNERSHIP FROM token_ownership WHERE ETH_ADDRESS = ? LIMIT 1",
            (norm_eth,),
        ).fetchone()
        ownership_json = "{}" if row is None or row[0] is None else row[0]

        try:
            ownership_map = json.loads(ownership_json)
        except (TypeError, json.JSONDecodeError):
            ownership_map = {}

        if not isinstance(ownership_map, dict):
            ownership_map = {}

        current = 0
        if norm_asset in ownership_map:
            current = Tables._hex_u256_to_int(ownership_map.get(norm_asset))

        new_value = current + value
        if new_value >= (1 << 256):
            raise OverflowError("u256 overflow")

        # Store as canonical 0x-prefixed lowercase hex string.
        ownership_map[norm_asset] = Web3.to_hex(new_value).lower()

        db.execute(
            "UPDATE token_ownership SET OWNERSHIP = ? WHERE ETH_ADDRESS = ?",
            (json.dumps(ownership_map, separators=(",", ":")), norm_eth),
        )


    @staticmethod
    def transfer(
            db: sqlite3.Connection,
            src_address: str,
            destination_address: str,
            value: int,
            asset_address: str,
    ) -> None:
        norm_src = Tables._normalize_eth_address(src_address)
        norm_dst = Tables._normalize_eth_address(destination_address)
        norm_asset = Tables._normalize_eth_address(asset_address)
        if norm_src is None or norm_dst is None or norm_asset is None:
            raise ValueError("Invalid src_address, destination_address, or asset_address")

        if not isinstance(value, int):
            raise TypeError("value must be int")
        if value < 0 or value >= (1 << 256):
            raise ValueError("value must be a u256 (0 <= value < 2**256)")
        if value == 0 or norm_src == norm_dst:
            return

        def _load_map_for(addr: str) -> dict:
            db.execute(
                """
                INSERT INTO token_ownership (ETH_ADDRESS, OWNERSHIP)
                VALUES (?, ?) ON CONFLICT(ETH_ADDRESS) DO NOTHING
                """,
                (addr, "{}"),
            )
            row = db.execute(
                "SELECT OWNERSHIP FROM token_ownership WHERE ETH_ADDRESS = ? LIMIT 1",
                (addr,),
            ).fetchone()
            raw = "{}" if row is None or row[0] is None else row[0]
            try:
                m = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                m = {}
            return m if isinstance(m, dict) else {}

        def _store_map_for(addr: str, m: dict) -> None:
            db.execute(
                "UPDATE token_ownership SET OWNERSHIP = ? WHERE ETH_ADDRESS = ?",
                (json.dumps(m, separators=(",", ":")), addr),
            )

        def _get_balance(m: dict) -> int:
            return Tables._hex_u256_to_int(m.get(norm_asset))

        def _set_balance(m: dict, amount: int) -> None:
            if amount < 0 or amount >= (1 << 256):
                raise OverflowError("u256 overflow/underflow")
            m[norm_asset] = Web3.to_hex(amount).lower()

            src_map = _load_map_for(norm_src)
            dst_map = _load_map_for(norm_dst)

            src_bal = _get_balance(src_map)
            if src_bal < value:
                raise ValueError("insufficient balance")

            dst_bal = _get_balance(dst_map)
            new_src = src_bal - value
            new_dst = dst_bal + value
            if new_dst >= (1 << 256):
                raise OverflowError("u256 overflow")

            _set_balance(src_map, new_src)
            _set_balance(dst_map, new_dst)

            _store_map_for(norm_src, src_map)
            _store_map_for(norm_dst, dst_map)
