# Assumptions : aLL database methods will be called holding a global lock
import sqlite3

from agentpit.datastructures.market_state import MarketState


class TableCreate:
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
        db.execute("CREATE INDEX IF NOT EXISTS idx_orders_api_key ON orders(API_KEY)")

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

    @staticmethod
    def create_erc1155_token_ownership_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS erc1155_token_ownership (
                ETH_ADDRESS TEXT PRIMARY KEY,
                OWNERSHIP TEXT NOT NULL
            )
            """
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

    @staticmethod
    def create_markets_table(db: sqlite3.Connection) -> None:
        allowed_states = ", ".join(f"'{s.value}'" for s in MarketState)
        db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS markets (
                MARKET_ID INTEGER PRIMARY KEY,
                CONDITION_ID TEXT NOT NULL UNIQUE, -- u256 hex string
                POLYMARKET_ID INTEGER,      -- optional source market id from Polymarket
                QUESTION TEXT NOT NULL,     -- question string used to compute condition_id
                SLUG TEXT NOT NULL,                  -- optional URL-safe identifier
                DESCRIPTION TEXT NOT NULL,  -- human-readable description
                erc1155_TOKENS TEXT NOT NULL, -- JSON array of [tokenId, label] pairs
                START_DATE INTEGER NOT NULL, -- unix timestamp
                END_DATE INTEGER,   -- unix timestamp
                RESOLVED_OUTCOME INTEGER, -- index of the winning outcome
                MARKET_STATE TEXT NOT NULL DEFAULT '{MarketState.DRAFT.value}'
                    CHECK (MARKET_STATE IN ({allowed_states}))
            )
            """
        )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_markets_condition_id ON markets(CONDITION_ID)"
        )

    @staticmethod
    def create_transactions_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                api_key TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                market_id INTEGER,
                details TEXT
            )
            """
        )

    @staticmethod
    def create_all_tables(db: sqlite3.Connection) -> None:
        # errors propagate; no exception handling here
        TableCreate.create_orders_table(db)
        TableCreate.create_trades_table(db)
        TableCreate.create_erc20_token_ownership_table(db)
        TableCreate.create_erc1155_token_ownership_table(db)
        TableCreate.create_keys_table(db)
        TableCreate.create_markets_table(db)
        TableCreate.create_transactions_table(db)
