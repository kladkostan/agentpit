from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3  # pip install web3
import json
import sqlite3


class Tables:
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
        Tables.create_orders_table(db)
        Tables.create_trades_table(db)
        Tables.create_token_ownership_table(db)
        Tables.create_keys_table(db)

    @staticmethod
    def _normalize_eth_address(addr: str) -> str | None:
        if not isinstance(addr, str):
            return None
        a = addr.strip().lower()
        if not a:
            return None
        if not a.startswith("0x"):
            a = "0x" + a
        # Strict: 20-byte address => 40 hex chars after 0x
        if len(a) != 42:
            return None
        try:
            int(a[2:], 16)
        except ValueError:
            return None
        return a

    @staticmethod
    def _hex_u256_to_int(value: object) -> int:
        if not isinstance(value, str):
            return 0
        s = value.strip()
        if not s:
            return 0

        # Web3.to_int expects either an int-like value or a hexstr with 0x prefix.
        if not s.startswith("0x") and not s.startswith("0X"):
            s = "0x" + s

        try:
            n = Web3.to_int(hexstr=s)
        except (TypeError, ValueError):
            return 0

        if n < 0 or n >= (1 << 256):
            return 0
        return n

    @staticmethod
    def get_asset_ownership(
        db: sqlite3.Connection, eth_address: str, asset_address: str
    ) -> int:
        norm_eth = Tables._normalize_eth_address(eth_address)
        if norm_eth is None:
            return 0

        row = db.execute(
            "SELECT OWNERSHIP FROM token_ownership WHERE ETH_ADDRESS = ? LIMIT 1",
            (norm_eth,),
        ).fetchone()
        if row is None or row[0] is None:
            return 0

        try:
            ownership_map: object = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return 0

        if not isinstance(ownership_map, dict):
            return 0

        # At this point ownership_map should be dict[str, str]
        ownership_map_typed: dict[str, str] = {
            k: v
            for k, v in ownership_map.items()
            if isinstance(k, str) and isinstance(v, str)
        }

        norm_asset = Tables._normalize_eth_address(asset_address)
        if norm_asset is None:
            return 0

        # ownership_map is expected to be: { "<asset_eth_address_hex>": "<u256_hex>" }
        if norm_asset in ownership_map_typed:
            return Tables._hex_u256_to_int(ownership_map_typed[norm_asset])

        for k, v in ownership_map_typed.items():
            nk = Tables._normalize_eth_address(k)
            if nk == norm_asset:
                return Tables._hex_u256_to_int(v)

        return 0

    @staticmethod
    def _parse_32b_hex_private_key(value: object) -> bytes | None:
        if not isinstance(value, str):
            return None
        s = value.strip()
        if not s:
            return None
        if not s.startswith(("0x", "0X")):
            s = "0x" + s
        try:
            b = Web3.to_bytes(hexstr=s)
        except (TypeError, ValueError):
            return None
        return b if len(b) == 32 else None

    @staticmethod
    def get_private_key_for_api_key(
        db: sqlite3.Connection, api_key: str
    ) -> LocalAccount:
        row = db.execute(
            "SELECT ETH_PRIVATE_KEY FROM keys WHERE API_KEY = ? LIMIT 1",
            (api_key,),
        ).fetchone()

        existing_key: bytes | None = (
            None if row is None else Tables._parse_32b_hex_private_key(row[0])
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
        acct: LocalAccount = Tables.get_private_key_for_api_key(db, api_key)
        return acct.address

