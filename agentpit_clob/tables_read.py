import json
import sqlite3
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from .parse import normalize_eth_address, hex_u256_to_int, parse_32b_hex_private_key


class TablesRead:
    @staticmethod
    def get_erc20_asset_ownership(
        db: sqlite3.Connection, eth_address: str, asset_address: str
    ) -> int:
        # Use ETH address as the row key into erc20_token_ownership
        norm_eth = normalize_eth_address(eth_address)
        norm_asset = normalize_eth_address(asset_address)

        row = db.execute(
            "SELECT OWNERSHIP FROM erc20_token_ownership WHERE ETH_ADDRESS = ? LIMIT 1",
            (norm_eth,),
        ).fetchone()

        if row is None or row[0] is None:
            # Treat "no row" / NULL as "no ownership".
            return 0

        try:
            ownership_map = json.loads(row[0])
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Corrupted OWNERSHIP JSON for {norm_eth}: {row[0]!r}"
            ) from e

        if not isinstance(ownership_map, dict):
            raise ValueError(
                f"Corrupted OWNERSHIP data (not dict) for {norm_eth}: "
                f"{type(ownership_map)}"
            )

        # Exact canonical key
        if norm_asset in ownership_map:
            return hex_u256_to_int(ownership_map[norm_asset])

        # Fallback for older/non-canonical data, but still strict on value
        for k, v in ownership_map.items():
            if not isinstance(k, str):
                raise ValueError(
                    f"Corrupted OWNERSHIP map for {norm_eth}: non-str key {k!r}"
                )
            nk = normalize_eth_address(k)
            if nk == norm_asset:
                return hex_u256_to_int(v)

        return 0

    @staticmethod
    def get_erc155_asset_ownership(
        db: sqlite3.Connection, eth_address: str, asset_address: str
    ) -> int:
        norm_eth = normalize_eth_address(eth_address)
        norm_asset = normalize_eth_address(asset_address)

        row = db.execute(
            "SELECT OWNERSHIP FROM erc155_token_ownership WHERE ETH_ADDRESS = ? LIMIT 1",
            (norm_eth,),
        ).fetchone()

        if row is None or row[0] is None:
            # No row / NULL => no ownership
            return 0

        try:
            ownership_map = json.loads(row[0])
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Corrupted OWNERSHIP JSON for {norm_eth}: {row[0]!r}"
            ) from e

        if not isinstance(ownership_map, dict):
            raise ValueError(
                f"Corrupted OWNERSHIP data (not dict) for {norm_eth}: "
                f"{type(ownership_map)}"
            )

        if norm_asset in ownership_map:
            return hex_u256_to_int(ownership_map[norm_asset])

        for k, v in ownership_map.items():
            if not isinstance(k, str):
                raise ValueError(
                    f"Corrupted OWNERSHIP map for {norm_eth}: non-str key {k!r}"
                )
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
        acct = TablesRead.get_private_key_for_api_key(db, api_key)
        return acct.address
