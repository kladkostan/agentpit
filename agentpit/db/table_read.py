import json
import uuid
from dataclasses import dataclass
import psycopg
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from agentpit.utils.parse import parse_32b_hex_private_key
from agentpit.datastructures.event import Event
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState
from agentpit.datastructures.user import User
from ..datastructures.condition_id import ConditionId


@dataclass(frozen=True)
class TradedAccount:
    user_id: str
    eth_address: str
    handle: str | None


_MARKET_COLS = (
    "MARKET_ID, POLYMARKET_ID, POLYMARKET_CONDITION_ID, CONDITION_ID, "
    "QUESTION, DESCRIPTION, SLUG, "
    "START_DATE, END_DATE, ERC1155_TOKENS, "
    "COALESCE(MARKET_STATE, 'DRAFT') as MARKET_STATE, "
    "RESOLVED_OUTCOME, "
    "EVENT_ID, OUTCOME_LABEL, ICON_URL, "
    "POLYMARKET_YES_TOKEN_ID, POLYMARKET_NO_TOKEN_ID, "
    "COALESCE(FULLY_REDEEMED, FALSE) as FULLY_REDEEMED"
)


def _row_to_market(row) -> Market:
    erc1155_tokens_json = row["ERC1155_TOKENS"]
    erc1155_tokens = json.loads(erc1155_tokens_json) if erc1155_tokens_json else []
    return Market(
        question=row["QUESTION"],
        market_id=row["MARKET_ID"],
        polymarket_id=row["POLYMARKET_ID"],
        polymarket_condition_id=row["POLYMARKET_CONDITION_ID"],
        polymarket_yes_token_id=row["POLYMARKET_YES_TOKEN_ID"],
        polymarket_no_token_id=row["POLYMARKET_NO_TOKEN_ID"],
        condition_id=ConditionId(row["CONDITION_ID"]),
        description=row["DESCRIPTION"],
        slug=row["SLUG"],
        start_date=row["START_DATE"],
        end_date=row["END_DATE"],
        erc1155_tokens=erc1155_tokens,
        market_state=MarketState(row["MARKET_STATE"]),
        resolved_outcome=row["RESOLVED_OUTCOME"],
        event_id=row["EVENT_ID"],
        outcome_label=row["OUTCOME_LABEL"],
        icon_url=row["ICON_URL"],
        fully_redeemed=row["FULLY_REDEEMED"],
    )


class TableRead:
    @staticmethod
    def read_condition_id_by_polymarket_id(
        db: psycopg.Connection, polymarket_id: int
    ) -> int | None:
        """Return MARKET_ID for a Polymarket id, or None if not found."""
        row = db.execute(
            "SELECT CONDITION_ID FROM markets WHERE POLYMARKET_ID = %s LIMIT 1",
            (polymarket_id,),
        ).fetchone()
        return ConditionId(str(row["CONDITION_ID"])) if row is not None else None

    @staticmethod
    def market_exists_by_polymarket_id(
        db: psycopg.Connection, polymarket_id: int
    ) -> bool:
        """Return True if a market row exists for the given Polymarket id."""
        row = db.execute(
            "SELECT 1 FROM markets WHERE POLYMARKET_ID = %s LIMIT 1",
            (polymarket_id,),
        ).fetchone()
        return row is not None

    @staticmethod
    def get_market_status_by_condition_id(
        db: psycopg.Connection, condition_id: str
    ) -> tuple[MarketState, int | None] | None:
        """
        Fetch the market state and resolved outcome by CONDITION_ID.

        Returns:
            Tuple of (MarketState, resolved_outcome) if found, otherwise None.
        """
        row = db.execute(
            "SELECT COALESCE(MARKET_STATE, 'DRAFT') as MARKET_STATE, RESOLVED_OUTCOME FROM markets WHERE CONDITION_ID = %s LIMIT 1",
            (condition_id,),
        ).fetchone()

        if row is None:
            return None

        return MarketState(row["MARKET_STATE"]), row["RESOLVED_OUTCOME"]

    @staticmethod
    def get_market_state(
        db: psycopg.Connection, condition_id: ConditionId
    ) -> MarketState | None:
        """
        Fetch the market state by CONDITION_ID.

        Returns:
            MarketState if found, otherwise None.
        """
        row = db.execute(
            "SELECT COALESCE(MARKET_STATE, 'DRAFT') as MARKET_STATE FROM markets WHERE CONDITION_ID = %s LIMIT 1",
            (condition_id.value,),
        ).fetchone()

        if row is None:
            return None

        return MarketState(row["MARKET_STATE"])

    @staticmethod
    def get_private_key_for_api_key(
        db: psycopg.Connection, api_key: str
    ) -> LocalAccount | None:
        """Return the eth account for an API key, or None if no user matches.

        Read-only — never inserts. Anonymous user creation is gone now that auth
        is required: a request with an unknown api_key resolves to None.
        """
        row = db.execute(
            "SELECT ETH_PRIVATE_KEY FROM users WHERE API_KEY = %s LIMIT 1",
            (api_key,),
        ).fetchone()
        if row is None:
            return None
        existing_key = parse_32b_hex_private_key(row["ETH_PRIVATE_KEY"])
        return Account.from_key(existing_key)

    @staticmethod
    def get_eth_address_for_api_key(db: psycopg.Connection, api_key: str) -> str | None:
        """Return the eth address for an API key, or None if no user matches."""
        row = db.execute(
            "SELECT ETH_ADDRESS FROM users WHERE API_KEY = %s LIMIT 1",
            (api_key,),
        ).fetchone()
        return row["ETH_ADDRESS"] if row else None

    @staticmethod
    def get_user_id_by_api_key(db: psycopg.Connection, api_key: str) -> str | None:
        row = db.execute(
            "SELECT USER_ID FROM users WHERE API_KEY = %s LIMIT 1", (api_key,)
        ).fetchone()
        return row["USER_ID"] if row else None

    @staticmethod
    def get_agent_by_id(db: psycopg.Connection, agent_id: str) -> dict | None:
        """
        Fetch an agent by AGENT_ID.
        Returns a dict with agent_id, personality_id, state, history, todo or None.
        """
        row = db.execute(
            "SELECT PERSONALITY, STATE, HISTORY, TODO FROM agents WHERE AGENT_ID = %s LIMIT 1",
            (agent_id,),
        ).fetchone()

        if row is None:
            return None

        return {
            "agent_id": agent_id,
            "personality_id": row["PERSONALITY"],
            "state": json.loads(row["STATE"]),
            "history": json.loads(row["HISTORY"]),
            "todo": json.loads(row["TODO"]),
        }

    _USER_COLS = (
        "USER_ID, EMAIL, HANDLE, ETH_ADDRESS, ETH_PRIVATE_KEY, "
        "API_KEY, ONBOARDED_AT, CREATED_AT, IS_BOT"
    )

    @staticmethod
    def _row_to_user(row) -> "User":
        existing_key = parse_32b_hex_private_key(row["ETH_PRIVATE_KEY"])
        acct = Account.from_key(existing_key)
        return User(
            user_id=row["USER_ID"],
            email=row["EMAIL"],
            eth_key=acct,
            eth_address=row["ETH_ADDRESS"],
            api_key=row["API_KEY"],
            handle=row["HANDLE"],
            onboarded_at=row["ONBOARDED_AT"],
            created_at=row["CREATED_AT"] if row["CREATED_AT"] is not None else 0,
            is_bot=bool(row["IS_BOT"]),
        )

    @staticmethod
    def get_user_by_userid(db: psycopg.Connection, user_id: str) -> "User | None":
        row = db.execute(
            f"SELECT {TableRead._USER_COLS} FROM users WHERE USER_ID = %s LIMIT 1",
            (user_id,),
        ).fetchone()
        return TableRead._row_to_user(row) if row else None

    @staticmethod
    def get_user_by_api_key(db: psycopg.Connection, api_key: str) -> "User | None":
        row = db.execute(
            f"SELECT {TableRead._USER_COLS} FROM users WHERE API_KEY = %s LIMIT 1",
            (api_key,),
        ).fetchone()
        return TableRead._row_to_user(row) if row else None

    @staticmethod
    def get_idempotency_order_id(
        db: psycopg.Connection, api_key: str, client_order_id: str
    ) -> "str | None":
        row = db.execute(
            "SELECT ORDER_ID FROM idempotency_keys "
            "WHERE API_KEY = %s AND CLIENT_ORDER_ID = %s",
            (api_key, client_order_id),
        ).fetchone()
        return row["ORDER_ID"] if row else None

    @staticmethod
    def get_user_by_email(db: psycopg.Connection, email: str) -> "User | None":
        row = db.execute(
            f"SELECT {TableRead._USER_COLS} FROM users WHERE EMAIL = %s LIMIT 1",
            (email,),
        ).fetchone()
        return TableRead._row_to_user(row) if row else None

    @staticmethod
    def handle_taken(db: psycopg.Connection, handle: str) -> bool:
        """Whether a handle is already claimed.

        `HANDLE TEXT UNIQUE` is the real guarantee; this is what lets
        registration pick a different name instead of surfacing a constraint
        violation as a 500.
        """
        row = db.execute(
            "SELECT 1 FROM users WHERE HANDLE = %s", (handle,)
        ).fetchone()
        return row is not None

    @staticmethod
    def get_user_by_eth_address(db: psycopg.Connection, eth_address: str) -> "User | None":
        row = db.execute(
            f"SELECT {TableRead._USER_COLS} FROM users WHERE ETH_ADDRESS = %s LIMIT 1",
            (eth_address,),
        ).fetchone()
        return TableRead._row_to_user(row) if row else None

    @staticmethod
    def get_password_hash_by_email(db: psycopg.Connection, email: str) -> str | None:
        """Used by login — returns the bcrypt hash so the service can verify."""
        row = db.execute(
            "SELECT PASSWORD_HASH FROM users WHERE EMAIL = %s LIMIT 1",
            (email,),
        ).fetchone()
        return row["PASSWORD_HASH"] if row else None

    @staticmethod
    def get_password_hash_by_userid(db: psycopg.Connection, user_id: str) -> str | None:
        row = db.execute(
            "SELECT PASSWORD_HASH FROM users WHERE USER_ID = %s LIMIT 1",
            (user_id,),
        ).fetchone()
        return row["PASSWORD_HASH"] if row else None

    @staticmethod
    def get_last_topup_at(db: psycopg.Connection, user_id: str) -> int | None:
        row = db.execute(
            "SELECT LAST_TOPUP_AT FROM users WHERE USER_ID = %s", (user_id,)
        ).fetchone()
        return row["LAST_TOPUP_AT"] if row else None

    @staticmethod
    def get_total_deposited(
        db: psycopg.Connection, user_id: str, default_raw: int
    ) -> int:
        """Raw apUSD this account has been handed, grant included.

        NULL means the row predates the column. It reads as `default_raw` --
        the signup grant -- because a backfill migration could only have
        written the same number, and doing it at the read keeps the two
        production accounts and the house correct without one.
        """
        row = db.execute(
            "SELECT TOTAL_DEPOSITED FROM users WHERE USER_ID = %s", (user_id,)
        ).fetchone()
        if row is None or row["TOTAL_DEPOSITED"] is None:
            return default_raw
        return int(row["TOTAL_DEPOSITED"])

    @staticmethod
    def get_deployment_id(db: psycopg.Connection, user_id: str) -> str | None:
        """Which chain deployment this account's figures were recorded against.

        NULL means the row predates the column; the caller records the current
        identity without resetting, because it has no evidence a wipe happened.
        """
        row = db.execute(
            "SELECT DEPLOYMENT_ID FROM users WHERE USER_ID = %s", (user_id,)
        ).fetchone()
        return row["DEPLOYMENT_ID"] if row else None

    @staticmethod
    def list_traded_accounts(db: psycopg.Connection) -> "list[TradedAccount]":
        """Every non-house account with at least one non-failed trade, taker
        or maker.

        Having traded is the membership rule: it keeps every registered
        address off a public board by default, and an account that never
        traded has nothing to rank. The house is excluded because it is the
        counterparty to nearly every trade rather than a competitor. A
        `FAILED` trade doesn't count -- it never settled, matching every
        other trade reader in the codebase (account_service.py,
        order_service.py).

        A previous version of this query joined `users` to a `UNION ALL`
        over the two api-key columns. That fixed a worse nested-loop plan
        (measured at 1318ms) but still scanned `trades` in full on every
        call -- and `trades` is dominated by the liquidity mirror's
        synthetic tape, a row per WSS last-trade event across ~1000 books
        with no retention, so the scan grows without bound in a quantity
        that has nothing to do with how many accounts have traded.

        This drives from `users` instead (tens of rows, not millions) and
        asks per user whether a matching trade exists, so each user resolves
        to an index probe on `idx_trades_taker_api_key` /
        `idx_trades_maker_api_key` that stops at the first hit rather than a
        scan of the whole table. No `DISTINCT` is needed: `users` is the only
        table in `FROM`, so a self-matched trade (taker == maker) can only
        make one of the two `EXISTS` clauses true for that user once, not
        twice. Measured locally with `EXPLAIN (ANALYZE, TIMING OFF)` against
        300k synthetic tape rows + 2k real trades across 40 accounts: the old
        form 60.2ms (`Hash Join` over two `Seq Scan`s of `trades`), this form
        0.06ms (`Index Scan` per user on `idx_trades_taker_api_key` /
        `idx_trades_maker_api_key`, second `EXISTS` short-circuited by the
        first on every row in this sample).
        """
        rows = db.execute(
            """
            SELECT u.USER_ID, u.ETH_ADDRESS, u.HANDLE
            FROM users u
            WHERE u.IS_BOT = 0
              AND (
                EXISTS (
                    SELECT 1 FROM trades t
                    WHERE t.TAKER_API_KEY = u.API_KEY AND t.STATUS != 'FAILED'
                )
                OR EXISTS (
                    SELECT 1 FROM trades t
                    WHERE t.MAKER_API_KEY = u.API_KEY AND t.STATUS != 'FAILED'
                )
              )
            ORDER BY u.USER_ID
            """
        ).fetchall()
        return [
            TradedAccount(
                user_id=r["USER_ID"],
                eth_address=r["ETH_ADDRESS"],
                handle=r["HANDLE"],
            )
            for r in rows
        ]

    @staticmethod
    def count_trades_by_user(db: psycopg.Connection) -> "dict[str, int]":
        """user_id -> number of non-failed trades it took part in, either side.

        Drives from `users` for the same reason as `list_traded_accounts`:
        `trades` is dominated by the liquidity mirror's unbounded synthetic
        tape, and a query with no predicate on it re-scans that tape in full
        on every call regardless of how many accounts have actually traded.
        Pushing `IS_BOT = 0` into a `UNION ALL` join still left the plan
        linear in tape size (measured 167ms -> 32ms, better but not
        index-driven).

        This form correlates a `LATERAL` subquery per user instead, so each
        user resolves to an index probe rather than a share of a full-table
        scan. `COUNT(DISTINCT x.TRADE_ID)` -- not `COUNT(*)` -- is still
        required: the `UNION ALL` inside the lateral emits one row per
        api-key column, so a trade where this user is both taker and maker
        appears twice within that user's own subquery and must be
        collapsed back to one. Measured locally the same way as
        `list_traded_accounts`: the old form 58.6ms (`Hash Join` over two
        `Seq Scan`s of `trades`), this form 1.4ms (`Nested Loop` driven by
        `users`, `Index Scan` on both api-key indexes per user).
        """
        rows = db.execute(
            """
            SELECT u.USER_ID AS UID, COUNT(DISTINCT x.TRADE_ID) AS N
            FROM users u
            JOIN LATERAL (
                SELECT TRADE_ID FROM trades
                WHERE TAKER_API_KEY = u.API_KEY AND STATUS != 'FAILED'
                UNION ALL
                SELECT TRADE_ID FROM trades
                WHERE MAKER_API_KEY = u.API_KEY AND STATUS != 'FAILED'
            ) x ON true
            WHERE u.IS_BOT = 0
            GROUP BY u.USER_ID
            """
        ).fetchall()
        return {r["UID"]: int(r["N"]) for r in rows}

    @staticmethod
    def latest_account_snapshots(
        db: psycopg.Connection,
    ) -> "dict[str, tuple[int, int]]":
        """user_id -> (capital_raw, deposited_raw) from each account's newest row."""
        rows = db.execute(
            """
            SELECT DISTINCT ON (USER_ID) USER_ID, CAPITAL_RAW, DEPOSITED_RAW
            FROM account_snapshots
            ORDER BY USER_ID, T DESC, SNAPSHOT_ID DESC
            """
        ).fetchall()
        return {
            r["USER_ID"]: (int(r["CAPITAL_RAW"]), int(r["DEPOSITED_RAW"]))
            for r in rows
        }

    @staticmethod
    def list_account_snapshots(
        db: psycopg.Connection, user_id: str, limit: int
    ) -> "list[tuple[int, int, int]]":
        """The newest `limit` snapshots for one account, oldest first.

        `ORDER BY T DESC LIMIT n` is what `idx_account_snapshots_user_t`
        drives; the reversal into chronological order happens here so callers
        get a curve rather than a stack. Bounded on purpose: retention keeps
        30 days, which at the 5-minute cadence is 8,640 rows nobody wants to
        serialise.
        """
        rows = db.execute(
            """
            SELECT T, CAPITAL_RAW, DEPOSITED_RAW
            FROM account_snapshots
            WHERE USER_ID = %s
            ORDER BY T DESC, SNAPSHOT_ID DESC
            LIMIT %s
            """,
            (user_id, limit),
        ).fetchall()
        return [
            (int(r["T"]), int(r["CAPITAL_RAW"]), int(r["DEPOSITED_RAW"]))
            for r in reversed(rows)
        ]

    @staticmethod
    def read_market(db: psycopg.Connection, market_id: int) -> "Market | None":
        row = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets WHERE MARKET_ID = %s",
            (market_id,),
        ).fetchone()
        return _row_to_market(row) if row else None

    @staticmethod
    def read_market_by_condition_id(
        db: psycopg.Connection, condition_id: ConditionId
    ) -> "Market | None":
        row = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets WHERE CONDITION_ID = %s",
            (condition_id.value,),
        ).fetchone()
        return _row_to_market(row) if row else None

    @staticmethod
    def list_all_markets(db: psycopg.Connection) -> "list[Market]":
        cur = db.execute(f"SELECT {_MARKET_COLS} FROM markets ORDER BY MARKET_ID")
        return [_row_to_market(row) for row in cur.fetchall()]

    @staticmethod
    def count_active_markets(db: psycopg.Connection) -> int:
        """How many markets are ACTIVE, platform-wide.

        This is the same predicate the UI calls "live", reduced. `to_gamma_market`
        sets `active = (state == ACTIVE)` and `closed = (state in CLOSED, RESOLVED,
        CANCELLED)`; the UI reads a market as live when it is active and not
        closed, and since ACTIVE is in neither closed set that collapses to the
        single comparison below. If either mapping changes, this must follow, or
        the headline number stops agreeing with the grid it labels.
        """
        row = db.execute(
            "SELECT COUNT(*) as CNT FROM markets WHERE MARKET_STATE = %s",
            (MarketState.ACTIVE.value,),
        ).fetchone()
        return int(row["CNT"]) if row else 0

    @staticmethod
    def list_markets(
        db: psycopg.Connection, limit: int = 100, offset: int = 0
    ) -> "tuple[list[Market], int]":
        total = db.execute("SELECT COUNT(*) as CNT FROM markets").fetchone()["CNT"]
        cur = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            "ORDER BY MARKET_ID DESC LIMIT %s OFFSET %s",
            (limit, offset),
        )
        markets = [_row_to_market(row) for row in cur.fetchall()]
        return markets, total

    @staticmethod
    def list_markets_with_user_activity(
        db: psycopg.Connection, api_key: str
    ) -> "list[Market]":
        """Markets where `api_key` has any trade or split/merge transaction —
        the only markets where the user can hold a CTF balance (you only acquire
        outcome tokens via a fill or a split). Lets list_positions scan just
        these (usually a handful) on-chain instead of every market, which is
        O(market count) sequential on-chain reads."""
        cur = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets WHERE CONDITION_ID IN "
            "(SELECT MARKET FROM trades "
            " WHERE TAKER_API_KEY = %s OR MAKER_API_KEY = %s) "
            "OR MARKET_ID IN (SELECT MARKET_ID FROM transactions WHERE API_KEY = %s)",
            (api_key, api_key, api_key),
        )
        return [_row_to_market(row) for row in cur.fetchall()]

    _EVENT_COLS = (
        "EVENT_ID, SLUG, TITLE, DESCRIPTION, ICON_URL, CATEGORY, "
        "START_DATE, END_DATE, POLYMARKET_EVENT_ID, VOLUME_24HR, VOLUME"
    )

    @staticmethod
    def _row_to_event(row) -> "Event":
        return Event(
            event_id=row["EVENT_ID"],
            slug=row["SLUG"],
            title=row["TITLE"],
            description=row["DESCRIPTION"] or "",
            icon_url=row["ICON_URL"],
            category=row["CATEGORY"],
            start_date=row["START_DATE"],
            end_date=row["END_DATE"],
            polymarket_event_id=row["POLYMARKET_EVENT_ID"],
            volume_24hr=row["VOLUME_24HR"],
            volume=row["VOLUME"],
        )

    @staticmethod
    def get_event_by_id(db: psycopg.Connection, event_id: int) -> "Event | None":
        row = db.execute(
            f"SELECT {TableRead._EVENT_COLS} FROM events WHERE EVENT_ID = %s LIMIT 1",
            (event_id,),
        ).fetchone()
        return TableRead._row_to_event(row) if row else None

    @staticmethod
    def get_event_by_slug(db: psycopg.Connection, slug: str) -> "Event | None":
        row = db.execute(
            f"SELECT {TableRead._EVENT_COLS} FROM events WHERE SLUG = %s LIMIT 1",
            (slug,),
        ).fetchone()
        return TableRead._row_to_event(row) if row else None

    @staticmethod
    def get_event_by_polymarket_event_id(
        db: psycopg.Connection, polymarket_event_id: str
    ) -> "Event | None":
        row = db.execute(
            f"SELECT {TableRead._EVENT_COLS} FROM events "
            "WHERE POLYMARKET_EVENT_ID = %s LIMIT 1",
            (polymarket_event_id,),
        ).fetchone()
        return TableRead._row_to_event(row) if row else None

    @staticmethod
    def list_markets_by_event_id(db: psycopg.Connection, event_id: int) -> "list[Market]":
        cur = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            "WHERE EVENT_ID = %s ORDER BY MARKET_ID",
            (event_id,),
        )
        return [_row_to_market(row) for row in cur.fetchall()]

    @staticmethod
    def list_events_with_markets(
        db: psycopg.Connection,
        limit: int = 100,
        offset: int = 0,
        category: str | None = None,
    ) -> "tuple[list[tuple[Event, list[Market]]], int]":
        """Return events ranked by upstream 24h volume, each paired with its
        child markets.

        Used by the home page: every market belongs to an event, so this is
        the primary listing query. Events with a captured upstream
        ``VOLUME_24HR`` rank first (descending); events never synced from
        upstream (NULL volume — orphan singletons, not-yet-refreshed rows) fall
        to the bottom, ordered newest-first as a stable tiebreak. One query for
        the event page + one for all member markets (bucketed in Python) — no
        N+1.

        When ``category`` is given (blank/whitespace counts as absent) the page
        is restricted to that category case-insensitively, so a case drift
        between the label the UI sends and the label stored can't silently
        return an empty page. ``total`` reflects the same filter.
        """
        where = ""
        params: list[object] = []
        normalized_category = category.strip() if category else None
        if normalized_category:
            where = " WHERE LOWER(CATEGORY) = LOWER(%s)"
            params.append(normalized_category)

        total = db.execute(
            f"SELECT COUNT(*) as CNT FROM events{where}",
            tuple(params),
        ).fetchone()["CNT"]
        events_cur = db.execute(
            f"SELECT {TableRead._EVENT_COLS} FROM events{where} "
            "ORDER BY VOLUME_24HR DESC NULLS LAST, EVENT_ID DESC LIMIT %s OFFSET %s",
            tuple(params + [limit, offset]),
        )
        events = [TableRead._row_to_event(r) for r in events_cur.fetchall()]
        if not events:
            return [], total

        ids = [ev.event_id for ev in events]
        placeholders = ",".join(["%s"] * len(ids))
        markets_cur = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            f"WHERE EVENT_ID IN ({placeholders}) ORDER BY EVENT_ID, MARKET_ID",
            ids,
        )
        by_event: dict[int, list[Market]] = {eid: [] for eid in ids}
        for row in markets_cur.fetchall():
            market = _row_to_market(row)
            assert market.event_id is not None  # guaranteed by WHERE clause
            by_event[market.event_id].append(market)
        return [(ev, by_event[ev.event_id]) for ev in events], total

    @staticmethod
    def list_markets_filtered(
        db: psycopg.Connection,
        *,
        limit: int = 100,
        offset: int = 0,
        market_id: int | None = None,
        slug: str | None = None,
        condition_ids: list[str] | None = None,
        clob_token_ids: list[str] | None = None,
        polymarket_condition_id: str | None = None,
    ) -> "list[Market]":
        clauses: list[str] = []
        params: list = []
        if market_id is not None:
            clauses.append("MARKET_ID = %s")
            params.append(market_id)
        if slug is not None:
            clauses.append("SLUG = %s")
            params.append(slug)
        if condition_ids:
            placeholders = ",".join("%s" for _ in condition_ids)
            clauses.append(f"CONDITION_ID IN ({placeholders})")
            params.extend(condition_ids)
        if polymarket_condition_id is not None:
            clauses.append("POLYMARKET_CONDITION_ID = %s")
            params.append(polymarket_condition_id)
        if clob_token_ids:
            # Match markets whose ERC1155_TOKENS JSON contains any given token id.
            # Quote-anchored, wildcards escaped (see resolve.resolve_by_token_id).
            ors = []
            for token_id in clob_token_ids:
                escaped = (
                    token_id.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                ors.append("ERC1155_TOKENS LIKE %s ESCAPE '\\'")
                params.append(f'%"{escaped}"%')
            clauses.append("(" + " OR ".join(ors) + ")")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets {where} "
            "ORDER BY MARKET_ID DESC LIMIT %s OFFSET %s",
            (*params, limit, offset),
        )
        return [_row_to_market(row) for row in cur.fetchall()]

    @staticmethod
    def list_event_categories(db: psycopg.Connection) -> "list[str]":
        """Every distinct, non-blank event category, case-insensitively sorted.

        Postgres rejects ``SELECT DISTINCT ... ORDER BY <expr>`` when the
        expression is not in the select list, so the DISTINCT happens in a
        subquery. ``COLLATE "C"`` is the explicit tiebreak that keeps the order
        total (and "Sports" before "sports") whatever the server's lc_collate.
        """
        cur = db.execute(
            """
            SELECT c FROM (
                SELECT DISTINCT CATEGORY AS c
                FROM events
                WHERE CATEGORY IS NOT NULL AND TRIM(CATEGORY) <> ''
            ) s
            ORDER BY LOWER(c) ASC, c COLLATE "C" ASC
            """
        )
        return [str(row["c"]) for row in cur.fetchall()]

    @staticmethod
    def list_orphan_markets(db: psycopg.Connection) -> "list[Market]":
        """Markets with no EVENT_ID — used by the auto-wrap singleton helper."""
        cur = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            "WHERE EVENT_ID IS NULL ORDER BY MARKET_ID"
        )
        return [_row_to_market(row) for row in cur.fetchall()]

    @staticmethod
    def list_bot_users(db: psycopg.Connection) -> "list[User]":
        """Every house/bot account — used by the liquidity engine on startup."""
        rows = db.execute(
            f"SELECT {TableRead._USER_COLS} FROM users WHERE IS_BOT = 1 "
            "ORDER BY CREATED_AT, USER_ID"
        ).fetchall()
        return [TableRead._row_to_user(r) for r in rows]

    @staticmethod
    def list_active_synced_markets(db: psycopg.Connection) -> "list[Market]":
        """Markets the liquidity engine should make liquidity for.

        Criteria: MARKET_STATE = 'ACTIVE' AND POLYMARKET_CONDITION_ID IS NOT NULL.
        """
        rows = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            "WHERE MARKET_STATE = 'ACTIVE' AND POLYMARKET_CONDITION_ID IS NOT NULL "
            "ORDER BY MARKET_ID"
        ).fetchall()
        return [_row_to_market(row) for row in rows]

    @staticmethod
    def book_tops_for_tokens(
        db: psycopg.Connection, token_ids: "list[str]"
    ) -> "dict[str, tuple[int | None, int | None]]":
        """Best bid / best ask (scaled price ints) per token from the live book.

        One aggregate query over `orders` for every token in `token_ids`, so a
        page of markets costs a single round-trip. Tokens with no resting orders
        are absent from the result; a present token may still be None on a side
        that has no orders.
        """
        if not token_ids:
            return {}
        rows = db.execute(
            "SELECT TOKEN_ID, "
            "MAX(PRICE) FILTER (WHERE SIDE = 'BUY')  AS BEST_BID, "
            "MIN(PRICE) FILTER (WHERE SIDE = 'SELL') AS BEST_ASK "
            "FROM orders WHERE STATUS = 'live' AND TOKEN_ID = ANY(%s) "
            "GROUP BY TOKEN_ID",
            (list(token_ids),),
        ).fetchall()
        out: "dict[str, tuple[int | None, int | None]]" = {}
        for r in rows:
            bid, ask = r["BEST_BID"], r["BEST_ASK"]
            out[r["TOKEN_ID"]] = (
                int(bid) if bid is not None else None,
                int(ask) if ask is not None else None,
            )
        return out

    @staticmethod
    def last_trade_prices_for_tokens(
        db: psycopg.Connection, token_ids: "list[str]"
    ) -> "dict[str, int]":
        """Most-recent non-failed trade price (scaled int) per token, batched."""
        if not token_ids:
            return {}
        rows = db.execute(
            "SELECT DISTINCT ON (ASSET_ID) ASSET_ID, PRICE FROM trades "
            "WHERE STATUS != 'FAILED' AND ASSET_ID = ANY(%s) "
            "ORDER BY ASSET_ID, MATCH_TIME DESC",
            (list(token_ids),),
        ).fetchall()
        return {r["ASSET_ID"]: int(r["PRICE"]) for r in rows}

    @staticmethod
    def list_unresolved_ended_markets(
        db: psycopg.Connection, now: int
    ) -> "list[Market]":
        """Resolution candidates: not RESOLVED/CANCELLED and past END_DATE.

        Bounds the resolution mirror to markets that could plausibly be settled
        upstream, instead of every unresolved market.
        """
        rows = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            "WHERE MARKET_STATE NOT IN ('RESOLVED', 'CANCELLED') "
            "AND END_DATE IS NOT NULL AND END_DATE < %s "
            "ORDER BY MARKET_ID",
            (now,),
        ).fetchall()
        return [_row_to_market(row) for row in rows]

    @staticmethod
    def list_resolved_unredeemed_markets(
        db: psycopg.Connection,
    ) -> "list[Market]":
        """Auto-redeem candidates: RESOLVED and not yet fully redeemed."""
        rows = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            "WHERE MARKET_STATE = 'RESOLVED' "
            "AND COALESCE(FULLY_REDEEMED, FALSE) = FALSE "
            "ORDER BY MARKET_ID"
        ).fetchall()
        return [_row_to_market(row) for row in rows]

    @staticmethod
    def list_participant_api_keys_for_market(
        db: psycopg.Connection, market_id: int, token_ids: "list[str]"
    ) -> "set[str]":
        """Distinct api_keys that traded the market's tokens or split/merged it.

        Scopes the auto-redeem holder scan to real participants (including the
        house/mirror bot account, which appears as a trade maker).
        """
        keys: set[str] = set()
        if token_ids:
            placeholders = ",".join("%s" for _ in token_ids)
            rows = db.execute(
                f"SELECT TAKER_API_KEY, MAKER_API_KEY FROM trades "
                f"WHERE ASSET_ID IN ({placeholders})",
                token_ids,
            ).fetchall()
            for r in rows:
                if r["TAKER_API_KEY"]:
                    keys.add(r["TAKER_API_KEY"])
                if r["MAKER_API_KEY"]:
                    keys.add(r["MAKER_API_KEY"])
        rows = db.execute(
            "SELECT DISTINCT API_KEY FROM transactions "
            "WHERE MARKET_ID = %s AND TRANSACTION_TYPE IN ('SPLIT', 'MERGE')",
            (market_id,),
        ).fetchall()
        for r in rows:
            if r["API_KEY"]:
                keys.add(r["API_KEY"])
        return keys

    @staticmethod
    def list_live_order_levels(
        db: psycopg.Connection, api_key: str, token_ids: list[str]
    ) -> list[dict]:
        """The mirror account's live orders on the given tokens — the
        'current' side of the reconciler diff."""
        if not token_ids:
            return []
        placeholders = ",".join("%s" for _ in token_ids)
        return db.execute(
            "SELECT ORDER_ID, TOKEN_ID, SIDE, PRICE, REMAINING_AMOUNT FROM orders "
            f"WHERE API_KEY = %s AND STATUS = 'live' AND TOKEN_ID IN ({placeholders})",
            [api_key, *token_ids],
        ).fetchall()

    @staticmethod
    def foreign_touch(
        db: psycopg.Connection, own_api_key: str, token_id: str
    ) -> tuple[int | None, int | None]:
        """(best_bid, best_ask) among OTHER owners' live orders on one token.
        The reconciler uses this to budget placements that would cross a real
        user's order (an intentional fill — spec §7)."""
        rows = db.execute(
            "SELECT SIDE, MAX(PRICE) AS MX, MIN(PRICE) AS MN FROM orders "
            "WHERE TOKEN_ID = %s AND STATUS = 'live' AND API_KEY != %s "
            "GROUP BY SIDE",
            (token_id, own_api_key),
        ).fetchall()
        bid = ask = None
        for r in rows:
            if r["SIDE"] == "BUY":
                bid = int(r["MX"])
            elif r["SIDE"] == "SELL":
                ask = int(r["MN"])
        return bid, ask

    @staticmethod
    def list_trades_for_api_key(
        db: psycopg.Connection,
        api_key: str,
        *,
        market: str | None = None,
        asset_id: str | None = None,
        trade_id: str | None = None,
        before: int | None = None,
        after: int | None = None,
    ) -> list[dict]:
        """Trades where the user is taker OR maker, newest first."""
        clauses = ["(TAKER_API_KEY = %s OR MAKER_API_KEY = %s)"]
        params: list = [api_key, api_key]
        if market is not None:
            clauses.append("MARKET = %s"); params.append(market)
        if asset_id is not None:
            clauses.append("ASSET_ID = %s"); params.append(asset_id)
        if trade_id is not None:
            clauses.append("TRADE_ID = %s"); params.append(trade_id)
        if before is not None:
            clauses.append("MATCH_TIME < %s"); params.append(before)
        if after is not None:
            clauses.append("MATCH_TIME > %s"); params.append(after)
        cur = db.execute(
            "SELECT TRADE_ID, TAKER_ORDER_ID, MAKER_ORDERS, MARKET, ASSET_ID, "
            "PRICE, TRADE_SIZE, SIDE, STATUS, MATCH_TIME, TRANSACTION_HASH, "
            "BUCKET_INDEX, FEE_RATE_BPS, TAKER_API_KEY, MAKER_API_KEY "
            f"FROM trades WHERE {' AND '.join(clauses)} ORDER BY MATCH_TIME DESC",
            params,
        )
        # Keep the case-insensitive dict rows — a plain dict(r) would lower-case
        # the keys and break the upper-case access in TradeService.
        return list(cur.fetchall())

    @staticmethod
    def get_transaction_history(db: psycopg.Connection, api_key: str) -> list:
        """
        Fetch the transaction history for a given API key.
        """
        cursor = db.execute(
            """
            SELECT TRANSACTION_ID, TIMESTAMP, TRANSACTION_TYPE, MARKET_ID, DETAILS
            FROM transactions
            WHERE API_KEY = %s
            ORDER BY TIMESTAMP DESC
            """,
            (api_key,),
        )
        transactions = []
        for row in cursor.fetchall():
            transactions.append(
                {
                    "transaction_id": row["TRANSACTION_ID"],
                    "timestamp": row["TIMESTAMP"],
                    "transaction_type": row["TRANSACTION_TYPE"],
                    "market_id": row["MARKET_ID"],
                    "details": json.loads(row["DETAILS"]) if row["DETAILS"] else {},
                }
            )
        return transactions
