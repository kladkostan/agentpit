# Assumptions : aLL database methods will be called holding a global lock
import sqlite3


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
    def create_erc20_token_ownership_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS erc20_token_ownership (
                ETH_ADDRESS TEXT PRIMARY KEY,
                OWNERSHIP TEXT NOT NULL
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_erc20_token_ownership_eth_address "
            "ON erc20_token_ownership(ETH_ADDRESS)"
        )

    @staticmethod
    def create_erc155_token_ownership_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS erc155_token_ownership (
                ETH_ADDRESS TEXT PRIMARY KEY,
                OWNERSHIP TEXT NOT NULL
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_erc155_token_ownership_eth_address "
            "ON erc155_token_ownership(ETH_ADDRESS)"
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
        TablesCreate.create_erc20_token_ownership_table(db)
        # If/when you want ERC155, remember to call:
        # TablesCreate.create_erc155_token_ownership_table(db)
        TablesCreate.create_keys_table(db)


