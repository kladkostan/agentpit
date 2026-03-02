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
            ownership_map = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return 0

        if not isinstance(ownership_map, dict):
            return 0

        norm_asset = Tables._normalize_eth_address(asset_address)
        if norm_asset is None:
            return 0

        # ownership_map is expected to be: { "<asset_eth_address_hex>": "<u256_hex>" }
        if norm_asset in ownership_map:
            return Tables._hex_u256_to_int(ownership_map[norm_asset])

        for k, v in ownership_map.items():
            nk = Tables._normalize_eth_address(k) if isinstance(k, str) else None
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
    def get_private_key_for_api_key(db: sqlite3.Connection, api_key: str) -> LocalAccount:
        row = db.execute(
            "SELECT ETH_PRIVATE_KEY FROM keys WHERE API_KEY = ? LIMIT 1",
            (api_key,),
        ).fetchone()

        existing_key = None if row is None else Tables._parse_32b_hex_private_key(row[0])
        if existing_key is not None:
            return Account.from_key(existing_key)

        # Missing/invalid: generate, persist, return.
        acct: LocalAccount = Account.create()
        key_hex: str = Web3.to_hex(acct.key)

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
    def get_eth_address_for_api_keys(db: sqlite3.Connection, api_key: str) -> str:
        acct = Tables.get_private_key_for_api_key(db, api_key)
        return acct.address

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
            VALUES (?, ?)
            ON CONFLICT(ETH_ADDRESS) DO NOTHING
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
                VALUES (?, ?)
                ON CONFLICT(ETH_ADDRESS) DO NOTHING
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
