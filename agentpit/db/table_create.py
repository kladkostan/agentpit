# Assumptions : aLL database methods will be called holding a global lock
import sqlite3

from agentpit.datastructures.market_state import MarketState


class TableCreate:
    @staticmethod
    def create_trades_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                TRADE_ID TEXT PRIMARY KEY,
                TAKER_ORDER_ID TEXT,
                MAKER_ORDERS TEXT,
                MARKET TEXT,
                ASSET_ID TEXT,
                PRICE INTEGER,
                TRADE_SIZE INTEGER,
                REMAINING_SIZE INTEGER,
                SIDE TEXT,
                STATUS TEXT,
                MATCH_TIME INTEGER,
                TRANSACTION_HASH TEXT,
                BUCKET_INDEX INTEGER,
                FEE_RATE_BPS INTEGER
            )
            """
        )

    @staticmethod
    def create_orders_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                API_KEY TEXT,
                PRICE INTEGER,
                POST_ONLY INTEGER,
                ORDER_TYPE TEXT,
                SALT INTEGER,
                MAKER TEXT,
                TAKER TEXT,
                SIGNER TEXT,
                TOKEN_ID TEXT,
                MAKER_AMOUNT INTEGER,
                TAKER_AMOUNT INTEGER,
                EXPIRATION INTEGER,
                NONCE INTEGER,
                FEE_RATE_BPS INTEGER,
                SIDE TEXT,
                SIGNATURE_TYPE TEXT,
                SIGNATURE TEXT,
                ORDER_JSON TEXT,
                STATUS TEXT DEFAULT 'live',
                REMAINING_AMOUNT INTEGER,
                CREATED_AT INTEGER,
                ORDER_ID TEXT PRIMARY KEY
            )
            """
        )
        # additive: pre-existing dev DBs may not have SIGNATURE
        cols = {row[1] for row in db.execute("PRAGMA table_info(orders)").fetchall()}
        if "SIGNATURE" not in cols:
            db.execute("ALTER TABLE orders ADD COLUMN SIGNATURE TEXT")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_price_side ON orders(PRICE, SIDE)"
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_orders_order_type_status_expiration
                ON orders(ORDER_TYPE, STATUS, EXPIRATION)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_orders_status_expiration
                ON orders(STATUS, EXPIRATION)
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_orders_api_key ON orders(API_KEY)")

    @staticmethod
    def create_users_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                USER_ID         TEXT PRIMARY KEY,
                EMAIL           TEXT NOT NULL UNIQUE,
                PASSWORD_HASH   TEXT NOT NULL,
                HANDLE          TEXT UNIQUE,
                ETH_ADDRESS     TEXT NOT NULL UNIQUE,
                ETH_PRIVATE_KEY TEXT NOT NULL UNIQUE,
                API_KEY         TEXT NOT NULL UNIQUE,
                ONBOARDED_AT    INTEGER,
                CREATED_AT      INTEGER NOT NULL
            )
            """
        )
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(EMAIL)")
        TableCreate._migrate_users_table(db)

    @staticmethod
    def _migrate_users_table(db: sqlite3.Connection) -> None:
        """Idempotent additive migration for the users table.

        Pre-auth versions of the schema only had USER_ID, API_KEY, ETH_PRIVATE_KEY.
        Add the new columns if they're missing so existing dev DBs keep working.
        New columns marked NOT NULL in the canonical schema are added as nullable
        here because SQLite cannot add NOT NULL columns without a default.
        """
        existing = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        additions = [
            ("EMAIL", "TEXT"),
            ("PASSWORD_HASH", "TEXT"),
            ("HANDLE", "TEXT"),
            ("ETH_ADDRESS", "TEXT"),
            ("ONBOARDED_AT", "INTEGER"),
            ("CREATED_AT", "INTEGER"),
        ]
        for col, col_type in additions:
            if col not in existing:
                db.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")


    @staticmethod
    def create_markets_table(db: sqlite3.Connection) -> None:
        allowed_states = ", ".join(f"'{s.value}'" for s in MarketState)
        db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS markets (
                MARKET_ID INTEGER PRIMARY KEY,
                CONDITION_ID TEXT NOT NULL UNIQUE, -- u256 hex string
                POLYMARKET_ID INTEGER,      -- optional source market id from Polymarket
                POLYMARKET_CONDITION_ID TEXT, -- upstream conditionId for resolution mirror
                EVENT_ID INTEGER,           -- optional parent event grouping markets
                OUTCOME_LABEL TEXT,         -- short label shown inside an event (e.g. "France")
                ICON_URL TEXT,              -- optional icon for the outcome row (flag, logo, etc.)
                QUESTION TEXT NOT NULL,     -- question string used to compute condition_id
                SLUG TEXT NOT NULL,                  -- optional URL-safe identifier
                DESCRIPTION TEXT NOT NULL,  -- human-readable description
                ERC1155_TOKENS TEXT NOT NULL, -- JSON array of [tokenId, label] pairs
                START_DATE INTEGER NOT NULL, -- unix timestamp
                END_DATE INTEGER,   -- unix timestamp
                RESOLVED_OUTCOME INTEGER, -- index of the winning outcome
                MARKET_STATE TEXT NOT NULL DEFAULT '{MarketState.DRAFT.value}'
                    CHECK (MARKET_STATE IN ({allowed_states}))
            )
            """
        )
        cols = {row[1] for row in db.execute("PRAGMA table_info(markets)").fetchall()}
        if "POLYMARKET_CONDITION_ID" not in cols:
            db.execute("ALTER TABLE markets ADD COLUMN POLYMARKET_CONDITION_ID TEXT")
        if "EVENT_ID" not in cols:
            db.execute("ALTER TABLE markets ADD COLUMN EVENT_ID INTEGER")
        if "OUTCOME_LABEL" not in cols:
            db.execute("ALTER TABLE markets ADD COLUMN OUTCOME_LABEL TEXT")
        if "ICON_URL" not in cols:
            db.execute("ALTER TABLE markets ADD COLUMN ICON_URL TEXT")
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_markets_condition_id ON markets(CONDITION_ID)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_markets_polymarket_condition_id "
            "ON markets(POLYMARKET_CONDITION_ID)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_markets_event_id ON markets(EVENT_ID)"
        )

    @staticmethod
    def create_events_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                EVENT_ID INTEGER PRIMARY KEY AUTOINCREMENT,
                SLUG TEXT NOT NULL UNIQUE,
                TITLE TEXT NOT NULL,
                DESCRIPTION TEXT NOT NULL DEFAULT '',
                ICON_URL TEXT,
                CATEGORY TEXT,
                START_DATE INTEGER,
                END_DATE INTEGER,
                POLYMARKET_EVENT_ID TEXT
            )
            """
        )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_slug ON events(SLUG)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_polymarket_event_id "
            "ON events(POLYMARKET_EVENT_ID)"
        )

    @staticmethod
    def create_transactions_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                TRANSACTION_ID INTEGER PRIMARY KEY AUTOINCREMENT,
                TIMESTAMP DATETIME DEFAULT CURRENT_TIMESTAMP,
                API_KEY TEXT NOT NULL,
                TRANSACTION_TYPE TEXT NOT NULL,
                MARKET_ID INTEGER,
                DETAILS TEXT
            )
            """
        )

    @staticmethod
    def create_agents_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                AGENT_ID TEXT PRIMARY KEY,
                PERSONALITY TEXT NOT NULL,
                STATE TEXT NOT NULL DEFAULT '{}',
                HISTORY TEXT NOT NULL DEFAULT '[]',
                TODO TEXT NOT NULL DEFAULT '[]'
            )
            """
        )

    @staticmethod
    def create_personalities_table(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS personalities (
                PERSONALITY_ID TEXT PRIMARY KEY,
                PERSONALITY_TITLE TEXT NOT NULL,
                PERSONALITY_SPEC TEXT NOT NULL
            )
            """
        )

    @staticmethod
    def create_all_tables(db: sqlite3.Connection) -> None:
        # errors propagate; no exception handling here
        TableCreate.create_orders_table(db)
        TableCreate.create_trades_table(db)
        TableCreate.create_users_table(db)
        TableCreate.create_agents_table(db)
        TableCreate.create_personalities_table(db)
        TableCreate.create_events_table(db)
        TableCreate.create_markets_table(db)
        TableCreate.create_transactions_table(db)
