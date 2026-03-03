import json
import sqlite3
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from .parse import normalize_eth_address, hex_u256_to_int, parse_32b_hex_private_key

class TablesRead:
    @staticmethod
    def get_asset_ownership(
        db: sqlite3.Connection, eth_address: str, asset_address: str
    ) -> int:
        norm_eth = normalize_eth_address(eth_address)
        if norm_eth is None:
            return 0

        row = db.execute(
            "SELECT OWNERSHIP FROM token_ownership WHERE ETH_ADDRESS = ? LIMIT 1",
            (norm_eth,),
        ).fetchone()

        if row is None or row[0] is None:
            return 0

        try:
            ownership_map = json.loads(row[0])
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Corrupted OWNERSHIP JSON for {norm_eth}: {row[0]}"
            ) from e

        if not isinstance(ownership_map, dict):
            raise ValueError(f"Corrupted OWNERSHIP data (not dict) for {norm_eth}")

        norm_asset = normalize_eth_address(asset_address)
        if norm_asset is None:
            return 0

        # Exact match preferred
        if norm_asset in ownership_map:
            return hex_u256_to_int(ownership_map[norm_asset])

        # Fallback for case-insensitivity (though stored keys should be canonical)
        for k, v in ownership_map.items():
            if not isinstance(k, str):
                continue
            nk = normalize_eth_address(k)
            if nk == norm_asset:
                return hex_u256_to_int(v)

        return 0

    @staticmethod
    def get_private_key_for_api_key(
        db: sqlite3.Connection, api_key: str
    ) -> LocalAccount:
        row = db.execute(
            "SELECT ETH_PRIVATE_KEY FROM keys WHERE API_KEY = ? LIMIT 1",
            (api_key,),
        ).fetchone()

        existing_key: bytes | None = (
            None if row is None else parse_32b_hex_private_key(row[0])
        )
        if existing_key is not None:
            return Account.from_key(existing_key)

        # Missing/invalid: generate, persist, return (atomic).
        acct: LocalAccount = Account.create()
        key_hex: str = Web3.to_hex(acct.key)

        with db:
            db.execute(
                """
                INSERT INTO keys (API_KEY, ETH_PRIVATE_KEY)
                VALUES (?, ?)
                ON CONFLICT(API_KEY) DO UPDATE SET ETH_PRIVATE_KEY = excluded.ETH_PRIVATE_KEY
                """,
                (api_key, key_hex),
            )

        return acct

    @staticmethod
    def get_eth_address_for_api_key(db: sqlite3.Connection, api_key: str) -> str:
        acct = TablesRead.get_private_key_for_api_key(db, api_key)
        return acct.address

    @staticmethod
    def _ensure_row(db: sqlite3.Connection, addr: str) -> None:
        db.execute(
            """
            INSERT INTO token_ownership (ETH_ADDRESS, OWNERSHIP)
            VALUES (?, ?)
            ON CONFLICT(ETH_ADDRESS) DO NOTHING
            """,
            (addr, "{}"),
        )

    @staticmethod
    def _load_map(db: sqlite3.Connection, addr: str) -> dict[str, str]:
        row = db.execute(
            "SELECT OWNERSHIP FROM token_ownership WHERE ETH_ADDRESS = ? LIMIT 1",
            (addr,),
        ).fetchone()
        raw: str = "{}" if row is None or row[0] is None else row[0]
        try:
            m_obj: object = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            m_obj = {}

        if not isinstance(m_obj, dict):
            return {}

        return {
            k: v
            for k, v in m_obj.items()
            if isinstance(k, str) and isinstance(v, str)
        }

    @staticmethod
    def _store_map(db: sqlite3.Connection, addr: str, m: dict[str, str]) -> None:
        db.execute(
            "UPDATE token_ownership SET OWNERSHIP = ? WHERE ETH_ADDRESS = ?",
            (json.dumps(m, separators=(",", ":")), addr),
        )
