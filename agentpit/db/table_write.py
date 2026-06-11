import json
import time as _time
import uuid
import psycopg
from web3 import Web3
from eth_account import Account
from eth_account.signers.local import LocalAccount

from agentpit.common import check_state
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.event import Event
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState


class TableWrite:
    @staticmethod
    def create_user(
        db: psycopg.Connection,
        email: str,
        password_hash: str,
        handle: str | None = None,
    ) -> tuple[str, LocalAccount, str]:
        """Create a new user with an auto-generated eth keypair.

        Returns (user_id, eth_account, api_key). The caller is responsible for
        running on-chain onboarding (faucet drip + approvals) and then calling
        :func:`mark_user_onboarded` once those txns confirm.
        """
        acct: LocalAccount = Account.create()
        key_hex: str = Web3.to_hex(acct.key)
        user_id: str = str(uuid.uuid4())
        api_key: str = str(uuid.uuid4())
        created_at = int(_time.time())

        db.execute(
            """
            INSERT INTO users (
                USER_ID, EMAIL, PASSWORD_HASH, HANDLE,
                ETH_ADDRESS, ETH_PRIVATE_KEY, API_KEY,
                ONBOARDED_AT, CREATED_AT
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s)
            """,
            (
                user_id,
                email,
                password_hash,
                handle,
                acct.address,
                key_hex,
                api_key,
                created_at,
            ),
        )
        return user_id, acct, api_key

    @staticmethod
    def mark_user_onboarded(db: psycopg.Connection, user_id: str) -> None:
        db.execute(
            "UPDATE users SET ONBOARDED_AT = %s WHERE USER_ID = %s",
            (int(_time.time()), user_id),
        )

    @staticmethod
    def update_user_handle(db: psycopg.Connection, user_id: str, handle: str) -> bool:
        cur = db.execute(
            "UPDATE users SET HANDLE = %s WHERE USER_ID = %s",
            (handle, user_id),
        )
        return cur.rowcount > 0

    @staticmethod
    def update_user_password_hash(
        db: psycopg.Connection, user_id: str, password_hash: str
    ) -> bool:
        cur = db.execute(
            "UPDATE users SET PASSWORD_HASH = %s WHERE USER_ID = %s",
            (password_hash, user_id),
        )
        return cur.rowcount > 0

    @staticmethod
    def mark_user_as_bot(db: psycopg.Connection, api_key: str) -> bool:
        cur = db.execute("UPDATE users SET IS_BOT = 1 WHERE API_KEY = %s", (api_key,))
        return cur.rowcount > 0

    @staticmethod
    def mark_user_as_bot_by_eth_address(
        db: psycopg.Connection, eth_address: str
    ) -> bool:
        cur = db.execute(
            "UPDATE users SET IS_BOT = 1 WHERE LOWER(ETH_ADDRESS) = LOWER(%s)",
            (eth_address,),
        )
        return cur.rowcount > 0

    @staticmethod
    def create_personality(
        db: psycopg.Connection,
        personality_id: str,
        title: str,
        beliefs: str,
        methods: str,
        needs: str,
    ) -> str:
        spec = json.dumps(
            {"beliefs": beliefs, "methods": methods, "needs": needs},
            separators=(",", ":"),
        )
        db.execute(
            """
            INSERT INTO personalities (PERSONALITY_ID, PERSONALITY_TITLE, PERSONALITY_SPEC)
            VALUES (%s, %s, %s)
            """,
            (personality_id, title, spec),
        )
        return personality_id

    @staticmethod
    def create_agent(
        db: psycopg.Connection, agent_id: str, personality_id: str
    ) -> None:
        db.execute(
            """
            INSERT INTO agents (AGENT_ID, PERSONALITY)
            VALUES (%s, %s)
            """,
            (agent_id, personality_id),
        )

    @staticmethod
    def upsert_event(
        db: psycopg.Connection,
        *,
        slug: str,
        title: str,
        description: str = "",
        icon_url: str | None = None,
        category: str | None = None,
        start_date: int | None = None,
        end_date: int | None = None,
        polymarket_event_id: str | None = None,
    ) -> Event:
        """Insert an event or update it if SLUG already exists.

        Used by both the seeder and the Polymarket sync to be idempotent.
        """
        existing = db.execute(
            "SELECT EVENT_ID FROM events WHERE SLUG = %s LIMIT 1", (slug,)
        ).fetchone()
        if existing is not None:
            event_id = int(existing["EVENT_ID"])
            db.execute(
                """
                UPDATE events
                SET TITLE = %s, DESCRIPTION = %s, ICON_URL = %s, CATEGORY = %s,
                    START_DATE = %s, END_DATE = %s, POLYMARKET_EVENT_ID = %s
                WHERE EVENT_ID = %s
                """,
                (
                    title,
                    description,
                    icon_url,
                    category,
                    start_date,
                    end_date,
                    polymarket_event_id,
                    event_id,
                ),
            )
        else:
            row = db.execute(
                """
                INSERT INTO events (SLUG, TITLE, DESCRIPTION, ICON_URL, CATEGORY,
                                    START_DATE, END_DATE, POLYMARKET_EVENT_ID)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING EVENT_ID
                """,
                (
                    slug,
                    title,
                    description,
                    icon_url,
                    category,
                    start_date,
                    end_date,
                    polymarket_event_id,
                ),
            ).fetchone()
            event_id = int(row["EVENT_ID"])
        return Event(
            event_id=event_id,
            slug=slug,
            title=title,
            description=description,
            icon_url=icon_url,
            category=category,
            start_date=start_date,
            end_date=end_date,
            polymarket_event_id=polymarket_event_id,
        )

    @staticmethod
    def update_event_volume(
        db: psycopg.Connection, event_id: int, volume_24hr: float | None
    ) -> None:
        """Refresh an event's captured upstream 24h volume.

        No-op when ``volume_24hr`` is None, so a degraded sync pass (e.g. a
        recurring window with no series metadata, whose own 24h volume is null)
        never clobbers a previously-captured good value. Called on every bind
        pass so the figure tracks the latest sync.
        """
        if volume_24hr is None:
            return
        db.execute(
            "UPDATE events SET VOLUME_24HR = %s WHERE EVENT_ID = %s",
            (volume_24hr, event_id),
        )

    @staticmethod
    def update_market_polymarket_tokens(
        db: psycopg.Connection,
        *,
        polymarket_id: int,
        yes_token_id: str | None,
        no_token_id: str | None,
    ) -> None:
        """Backfill the upstream Polymarket token-id cross-reference on an
        already-synced market (matched by polymarket_id).

        COALESCE so a None never clobbers an existing id; no-op when both are
        None. Lets the book mirror resolve markets synced before positional
        token capture existed (e.g. Up/Down windows, whose yes/no ids were null).
        """
        if yes_token_id is None and no_token_id is None:
            return
        db.execute(
            """
            UPDATE markets
            SET POLYMARKET_YES_TOKEN_ID = COALESCE(%s, POLYMARKET_YES_TOKEN_ID),
                POLYMARKET_NO_TOKEN_ID  = COALESCE(%s, POLYMARKET_NO_TOKEN_ID)
            WHERE POLYMARKET_ID = %s
            """,
            (yes_token_id, no_token_id, polymarket_id),
        )

    @staticmethod
    def attach_market_to_event(
        db: psycopg.Connection,
        *,
        market_id: int,
        event_id: int,
        outcome_label: str | None = None,
        icon_url: str | None = None,
    ) -> None:
        """Bind an existing market to an event, optionally setting display metadata."""
        db.execute(
            """
            UPDATE markets
            SET EVENT_ID = %s,
                OUTCOME_LABEL = COALESCE(%s, OUTCOME_LABEL),
                ICON_URL      = COALESCE(%s, ICON_URL)
            WHERE MARKET_ID = %s
            """,
            (event_id, outcome_label, icon_url, market_id),
        )

    @staticmethod
    def create_market(
        db: psycopg.Connection, request: CreateMarketRequest, is_polygon_market: bool
    ) -> Market:

        # The local create-market path now sets `request.condition_id` upstream
        # (in MarketService) using the on-chain `getConditionId` view, so by the
        # time we get here the condition_id is always present.
        check_state(
            request.condition_id is not None,
            "request.condition_id must be set before TableWrite.create_market",
        )
        condition_id = request.condition_id

        erc1155_tokens_json = json.dumps(request.erc1155_tokens, separators=(",", ":"))

        # MARKET_ID is a BIGINT IDENTITY column — let Postgres assign it (avoids
        # the old racy MAX(MARKET_ID)+1) and read it back with RETURNING.
        new_market_id = int(
            db.execute(
                """
                INSERT INTO markets (CONDITION_ID,
                                     POLYMARKET_ID,
                                     POLYMARKET_CONDITION_ID,
                                     QUESTION,
                                     DESCRIPTION,
                                     SLUG,
                                     START_DATE,
                                     END_DATE,
                                     ERC1155_TOKENS,
                                     MARKET_STATE,
                                     EVENT_ID,
                                     OUTCOME_LABEL,
                                     ICON_URL,
                                     POLYMARKET_YES_TOKEN_ID,
                                     POLYMARKET_NO_TOKEN_ID)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING MARKET_ID
                """,
                (
                    condition_id.value,
                    request.polymarket_id,
                    request.polymarket_condition_id,
                    request.question,
                    request.description,
                    request.slug,
                    request.start_date,
                    request.end_date,
                    erc1155_tokens_json,
                    request.state,
                    request.event_id,
                    request.outcome_label,
                    request.icon_url,
                    request.polymarket_yes_token_id,
                    request.polymarket_no_token_id,
                ),
            ).fetchone()["MARKET_ID"]
        )

        return Market(
            question=request.question,
            market_id=new_market_id,
            polymarket_id=request.polymarket_id,
            polymarket_condition_id=request.polymarket_condition_id,
            polymarket_yes_token_id=request.polymarket_yes_token_id,
            polymarket_no_token_id=request.polymarket_no_token_id,
            condition_id=condition_id,
            description=request.description,
            slug=request.slug,
            erc1155_tokens=request.erc1155_tokens,
            market_state=MarketState(request.state),
            start_date=request.start_date,
            end_date=request.end_date,
            resolved_outcome=None,
            event_id=request.event_id,
            outcome_label=request.outcome_label,
            icon_url=request.icon_url,
        )

    @staticmethod
    def update_market_state_if_needed(
        db: psycopg.Connection, request: CreateMarketRequest
    ) -> Market:
        # Compute condition_id from question and number of outcomes
        erc1155_tokens_json = json.dumps(request.erc1155_tokens, separators=(",", ":"))

        # Fetch existing market details to preserve state and IDs
        cursor = db.execute(
            "SELECT MARKET_ID, RESOLVED_OUTCOME FROM markets WHERE POLYMARKET_ID = %s",
            (request.polymarket_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(
                f"Market with Polymarket ID {request.polymarket_id} not found"
            )

        market_id = row["MARKET_ID"]
        resolved_outcome = row["RESOLVED_OUTCOME"]

        db.execute(
            """
            UPDATE markets
            SET CONDITION_ID   = %s,
                QUESTION       = %s,
                DESCRIPTION    = %s,
                SLUG           = %s,
                START_DATE     = %s,
                END_DATE       = %s,
                ERC1155_TOKENS = %s,
                MARKET_STATE  = %s
            WHERE POLYMARKET_ID = %s
            """,
            (
                request.condition_id,
                request.question,
                request.description,
                request.slug,
                request.start_date,
                request.end_date,
                erc1155_tokens_json,
                request.state,
                request.polymarket_id,
            ),
        )

        return Market(
            question=request.question,
            market_id=market_id,
            polymarket_id=request.polymarket_id,
            condition_id=request.condition_id,
            description=request.description,
            slug=request.slug,
            erc1155_tokens=request.erc1155_tokens,
            market_state=MarketState(request.state),
            start_date=request.start_date,
            end_date=request.end_date,
            resolved_outcome=resolved_outcome,
        )

    @staticmethod
    def log_transaction(
        db: psycopg.Connection,
        api_key: str,
        transaction_type: str,
        market_id: int | None = None,
        details: dict | None = None,
    ) -> None:
        """
        Log a transaction to the transactions table.

        Args:
            db: Database connection
            api_key: API key of the user performing the transaction
            transaction_type: Type of transaction (e.g., "SPLIT", "MERGE", "REDEEM")
            market_id: Optional market ID
            details: Optional dictionary with transaction details (will be JSON serialized)
        """
        details_json = json.dumps(details) if details else None

        db.execute(
            """
            INSERT INTO transactions (API_KEY, TRANSACTION_TYPE, MARKET_ID, DETAILS)
            VALUES (%s, %s, %s, %s)
            """,
            (api_key, transaction_type, market_id, details_json),
        )

    @staticmethod
    def activate_market(db: psycopg.Connection, market_id: int) -> Market:
        """
        Activate a market, transitioning it from DRAFT to ACTIVE.

        Args:
            db: Database connection
            market_id: Market ID to activate

        Returns:
            Updated Market object

        Raises:
            ValueError: If market not found or not in DRAFT state
        """
        from agentpit.db.table_read import TableRead

        # Get current market
        market = TableRead.read_market(db, market_id)
        if not market:
            raise ValueError(f"Market {market_id} not found")

        # Check state
        if market.market_state != MarketState.DRAFT:
            raise ValueError(
                f"Market {market_id} is not in DRAFT state (current: {market.market_state.value})"
            )

        # Update state
        db.execute(
            "UPDATE markets SET MARKET_STATE = %s WHERE MARKET_ID = %s",
            (MarketState.ACTIVE.value, market_id),
        )

        # Return updated market
        market.market_state = MarketState.ACTIVE
        return market

    @staticmethod
    def close_market(db: psycopg.Connection, market_id: int) -> Market:
        """
        Close a market, transitioning it from ACTIVE to CLOSED.

        Args:
            db: Database connection
            market_id: Market ID to close

        Returns:
            Updated Market object

        Raises:
            ValueError: If market not found or not in ACTIVE state
        """
        from agentpit.db.table_read import TableRead

        # Get current market
        market = TableRead.read_market(db, market_id)
        if not market:
            raise ValueError(f"Market {market_id} not found")

        # Check state
        if market.market_state != MarketState.ACTIVE:
            raise ValueError(
                f"Market {market_id} is not in ACTIVE state (current: {market.market_state.value})"
            )

        # Update state to CLOSED
        db.execute(
            "UPDATE markets SET MARKET_STATE = %s WHERE MARKET_ID = %s",
            (MarketState.CLOSED.value, market_id),
        )

        # Return updated market
        market.market_state = MarketState.CLOSED
        return market

    @staticmethod
    def mark_fully_redeemed(db: psycopg.Connection, market_id: int) -> None:
        """Flag a resolved market as having no remaining redeemable holders."""
        db.execute(
            "UPDATE markets SET FULLY_REDEEMED = TRUE WHERE MARKET_ID = %s",
            (market_id,),
        )

    @staticmethod
    def resolve_market(
        db: psycopg.Connection, market_id: int, winning_outcome_index: int
    ) -> Market:
        """
        Resolve a market by specifying the winning outcome.

        Args:
            db: Database connection
            market_id: Market ID to resolve
            winning_outcome_index: Index of the winning outcome (0-based)

        Returns:
            Updated Market object

        Raises:
            ValueError: If market not found, already resolved, or invalid outcome index
        """
        from agentpit.db.table_read import TableRead

        # Get current market
        market = TableRead.read_market(db, market_id)
        if not market:
            raise ValueError(f"Market {market_id} not found")

        # Check if already resolved
        if market.market_state == MarketState.RESOLVED:
            raise ValueError(f"Market {market_id} is already resolved")

        # Validate outcome index
        if winning_outcome_index < 0 or winning_outcome_index >= len(
            market.erc1155_tokens
        ):
            raise ValueError(
                f"Invalid winning_outcome_index {winning_outcome_index}. "
                f"Market has {len(market.erc1155_tokens)} outcomes (indices 0-{len(market.erc1155_tokens)-1})"
            )

        # Update state and outcome
        db.execute(
            "UPDATE markets SET MARKET_STATE = %s, RESOLVED_OUTCOME = %s WHERE MARKET_ID = %s",
            (MarketState.RESOLVED.value, winning_outcome_index, market_id),
        )

        # Return updated market
        market.market_state = MarketState.RESOLVED
        market.resolved_outcome = winning_outcome_index
        return market

    @staticmethod
    def cancel_market(db: psycopg.Connection, market_id: int) -> tuple[Market, int]:
        """Cancel a market.

        Refund logic is intentionally not implemented here: with on-chain CTF
        positions, users recover their collateral via the standard merge /
        redeem path on the CTF contract directly, not via the backend.
        """
        from agentpit.db.table_read import TableRead

        market = TableRead.read_market(db, market_id)
        if not market:
            raise ValueError(f"Market {market_id} not found")

        if market.market_state == MarketState.RESOLVED:
            raise ValueError(f"Cannot cancel market {market_id}: already resolved")
        if market.market_state == MarketState.CANCELLED:
            raise ValueError(f"Market {market_id} is already cancelled")

        db.execute(
            "UPDATE markets SET MARKET_STATE = %s WHERE MARKET_ID = %s",
            (MarketState.CANCELLED.value, market_id),
        )

        market.market_state = MarketState.CANCELLED
        return market, 0

    @staticmethod
    def update_market_state_to_resolved_if_needed(
        db: psycopg.Connection, condition_id: ConditionId, winning_outcome_index: int
    ) -> Market:
        """
        Idempotently resolves a market. If already resolved or cancelled, does nothing.

        Args:
            db: Database connection
            condition_id: Condition ID of the market to resolve
            winning_outcome_index: Index of the winning outcome

        Returns:
            Updated Market object
        """
        from agentpit.db.table_read import TableRead

        # Get current market
        market = TableRead.read_market_by_condition_id(db, condition_id)
        if not market:
            raise ValueError(f"Market with condition_id {condition_id} not found")

        if (
            market.market_state == MarketState.RESOLVED
            or market.market_state == MarketState.CANCELLED
        ):
            return market

        # Validate outcome index
        if winning_outcome_index < 0 or winning_outcome_index >= len(
            market.erc1155_tokens
        ):
            raise ValueError(
                f"Invalid winning_outcome_index {winning_outcome_index}. "
                f"Market has {len(market.erc1155_tokens)} outcomes"
            )

        db.execute(
            "UPDATE markets SET MARKET_STATE = %s, RESOLVED_OUTCOME = %s WHERE CONDITION_ID = %s",
            (
                MarketState.RESOLVED.value,
                winning_outcome_index,
                market.condition_id.value,
            ),
        )

        market.market_state = MarketState.RESOLVED
        market.resolved_outcome = winning_outcome_index
        return market

    @staticmethod
    def purge_cancelled_orders(db: psycopg.Connection, before_ts: int) -> int:
        """Delete cancelled orders created before `before_ts`. Cancelled orders
        are resting quotes replaced before matching, so nothing references them;
        this caps table growth from fast re-quoting. Returns rows removed."""
        cur = db.execute(
            "DELETE FROM orders WHERE STATUS = 'cancelled' AND CREATED_AT < %s",
            (before_ts,),
        )
        return cur.rowcount
