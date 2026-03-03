from web3 import Web3  # pip install web3
import json
import sqlite3

from agentpit_clob.tables_create import TablesCreate


class ERC20Simulator:
    @staticmethod
    def mint(
        db: sqlite3.Connection, eth_address: str, asset_address: str, value: int
    ) -> None:
        norm_eth: str | None = TablesCreate._normalize_eth_address(eth_address)
        norm_asset: str | None = TablesCreate._normalize_eth_address(asset_address)
        if norm_eth is None or norm_asset is None:
            raise ValueError("Invalid eth_address or asset_address")

        if not isinstance(value, int):
            raise TypeError("value must be int")
        if value < 0 or value >= (1 << 256):
            raise ValueError("value must be a u256 (0 <= value < 2**256)")
        if value == 0:
            return


        db.execute(
            """
            INSERT INTO token_ownership (ETH_ADDRESS, OWNERSHIP)
            VALUES (?, ?)
            ON CONFLICT(ETH_ADDRESS) DO NOTHING
            """,
            (norm_eth, "{}"),
        )

        row = db.execute(
            "SELECT OWNERSHIP FROM token_ownership WHERE ETH_ADDRESS = ? LIMIT 1",
            (norm_eth,),
        ).fetchone()
        ownership_json: str = "{}" if row is None or row[0] is None else row[0]

        try:
            ownership_map_obj: object = json.loads(ownership_json)
        except (TypeError, json.JSONDecodeError):
            ownership_map_obj = {}

        ownership_map: dict[str, str] = (
            ownership_map_obj if isinstance(ownership_map_obj, dict) else {}
        )
        # Drop any non-str keys/values defensively.
        ownership_map = {
            k: v
            for k, v in ownership_map.items()
            if isinstance(k, str) and isinstance(v, str)
        }

        current: int = TablesCreate._hex_u256_to_int(ownership_map.get(norm_asset))
        new_value: int = current + value
        if new_value >= (1 << 256):
            raise OverflowError("u256 overflow")

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


        norm_src: str | None = TablesCreate._normalize_eth_address(src_address)
        norm_dst: str | None = TablesCreate._normalize_eth_address(destination_address)
        norm_asset: str | None = TablesCreate._normalize_eth_address(asset_address)
        if norm_src is None or norm_dst is None or norm_asset is None:
            raise ValueError("Invalid src_address, destination_address, or asset_address")

        if not isinstance(value, int):
            raise TypeError("value must be int")
        if value < 0 or value >= (1 << 256):
            raise ValueError("value must be a u256 (0 <= value < 2**256)")
        if value == 0 or norm_src == norm_dst:
            return

        _ensure_row(norm_src)
        _ensure_row(norm_dst)

        src_map: dict[str, str] = _load_map(norm_src)
        dst_map: dict[str, str] = _load_map(norm_dst)

        src_bal: int = TablesCreate._hex_u256_to_int(src_map.get(norm_asset))
        if src_bal < value:
            raise ValueError("insufficient balance")

        dst_bal: int = TablesCreate._hex_u256_to_int(dst_map.get(norm_asset))

        new_src: int = src_bal - value
        new_dst: int = dst_bal + value
        if new_dst >= (1 << 256):
            raise OverflowError("u256 overflow")

        src_map[norm_asset] = Web3.to_hex(new_src).lower()
        dst_map[norm_asset] = Web3.to_hex(new_dst).lower()

        _store_map(norm_src, src_map)
        _store_map(norm_dst, dst_map)


