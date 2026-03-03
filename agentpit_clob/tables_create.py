from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3  # pip install web3
import json
import sqlite3

from .parse import normalize_eth_address, hex_u256_to_int
from .tables_read import TablesRead
from .table_utils import TableUtils


class TablesCreate:
    @staticmethod
    def create_trades_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                taker_order_id TEXT,
                maker_orders TEXT,
                market TEXT,
                asset_id TEXT,
                price INTEGER,
                trade_size INTEGER,
                remaining_size INTEGER,
                side TEXT,
                status TEXT,
                match_time INTEGER,
                transaction_hash TEXT,
                bucket_index INTEGER,
                fee_rate_bps INTEGER
            )
            """
        )

    @staticmethod
    def create_orders_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                API_KEY TEXT,
                price INTEGER,
                post_only INTEGER,
                order_type TEXT,
                salt INTEGER,
                maker TEXT,
                taker TEXT,
                signer TEXT,
                tokenId TEXT,
                maker_amount INTEGER,
                taker_amount INTEGER,
                expiration INTEGER,
                nonce INTEGER,
                fee_rate_bps INTEGER,
                side TEXT,
                signature_type TEXT,
                order_json TEXT,
                status TEXT DEFAULT 'live',
                remaining_amount INTEGER,
                created_at INTEGER,
                order_id TEXT PRIMARY KEY
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_price_side ON orders(price, side)"
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_orders_order_id ON orders(order_id)")
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_orders_order_type_status_expiration
                ON orders(order_type, status, expiration)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_orders_status_expiration
                ON orders(status, expiration)
            """
        )

    @staticmethod
    def create_token_ownership_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS token_ownership (
                ETH_ADDRESS TEXT PRIMARY KEY,
                OWNERSHIP TEXT NOT NULL
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_token_ownership_eth_address ON token_ownership(ETH_ADDRESS)"
        )

    @staticmethod
    def create_keys_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS keys (
                API_KEY TEXT PRIMARY KEY,
                ETH_PRIVATE_KEY TEXT NOT NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_keys_api_key ON keys(API_KEY)")

    @staticmethod
    def create_all_tables(db: sqlite3.Connection) -> None:
        TablesCreate.create_orders_table(db)
        TablesCreate.create_trades_table(db)
        TablesCreate.create_token_ownership_table(db)
        TablesCreate.create_keys_table(db)

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
    def mint(
        db: sqlite3.Connection, eth_address: str, asset_address: str, value: int
    ) -> None:
        norm_eth: str | None = normalize_eth_address(eth_address)
        norm_asset: str | None = normalize_eth_address(asset_address)
        if norm_eth is None or norm_asset is None:
            raise ValueError("Invalid eth_address or asset_address")

        if not isinstance(value, int):
            raise TypeError("value must be int")
        if value < 0 or value >= (1 << 256):
            raise ValueError("value must be a u256 (0 <= value < 2**256)")
        if value == 0:
            return

        db.execute("BEGIN IMMEDIATE")
        try:
            TableUtils.ensure_ownership_row(db, norm_eth)
            ownership_map = TableUtils.load_ownership_map(db, norm_eth)

            current = 0
            if norm_asset in ownership_map:
                current = hex_u256_to_int(ownership_map[norm_asset])

            new_value = current + value
            if new_value >= (1 << 256):
                raise OverflowError("u256 overflow")

            ownership_map[norm_asset] = Web3.to_hex(new_value).lower()

            TableUtils.store_ownership_map(db, norm_eth, ownership_map)
            db.commit()
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def transfer(
        db: sqlite3.Connection,
        src_address: str,
        destination_address: str,
        value: int,
        asset_address: str,
    ) -> None:
        norm_src: str | None = normalize_eth_address(src_address)
        norm_dst: str | None = normalize_eth_address(destination_address)
        norm_asset: str | None = normalize_eth_address(asset_address)
        if norm_src is None or norm_dst is None or norm_asset is None:
            raise ValueError("Invalid src_address, destination_address, or asset_address")

        if not isinstance(value, int):
            raise TypeError("value must be int")
        if value < 0 or value >= (1 << 256):
            raise ValueError("value must be a u256 (0 <= value < 2**256)")
        if value == 0 or norm_src == norm_dst:
            return

        db.execute("BEGIN IMMEDIATE")
        try:
            TableUtils.ensure_ownership_row(db, norm_src)
            TableUtils.ensure_ownership_row(db, norm_dst)
            src_map = TableUtils.load_ownership_map(db, norm_src)
            dst_map = TableUtils.load_ownership_map(db, norm_dst)

            raw_src_bal = src_map.get(norm_asset)
            src_bal = 0 if raw_src_bal is None else hex_u256_to_int(raw_src_bal)

            if src_bal < value:
                raise ValueError(f"Insufficient balance: {src_bal} < {value}")

            raw_dst_bal = dst_map.get(norm_asset)
            dst_bal = 0 if raw_dst_bal is None else hex_u256_to_int(raw_dst_bal)

            new_src = src_bal - value
            new_dst = dst_bal + value
            if new_dst >= (1 << 256):
                raise OverflowError("u256 overflow")

            src_map[norm_asset] = Web3.to_hex(new_src).lower()
            dst_map[norm_asset] = Web3.to_hex(new_dst).lower()

            TableUtils.store_ownership_map(db, norm_src, src_map)
            TableUtils.store_ownership_map(db, norm_dst, dst_map)
            db.commit()
        except Exception:
            db.rollback()
            raise
