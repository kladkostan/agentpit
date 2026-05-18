import sqlite3
import json
import time as _time
import uuid
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
        db: sqlite3.Connection,
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
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
    def mark_user_onboarded(db: sqlite3.Connection, user_id: str) -> None:
        db.execute(
            "UPDATE users SET ONBOARDED_AT = ? WHERE USER_ID = ?",
            (int(_time.time()), user_id),
        )

    @staticmethod
    def mark_user_as_bot(db: sqlite3.Connection, api_key: str) -> bool:
        cur = db.execute("UPDATE users SET IS_BOT = 1 WHERE API_KEY = ?", (api_key,))
        return cur.rowcount > 0

    @staticmethod
    def mark_user_as_bot_by_eth_address(
        db: sqlite3.Connection, eth_address: str
    ) -> bool:
        cur = db.execute(
            "UPDATE users SET IS_BOT = 1 WHERE LOWER(ETH_ADDRESS) = LOWER(?)",
            (eth_address,),
        )
        return cur.rowcount > 0

    @staticmethod
    def create_personality(
        db: sqlite3.Connection,
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
            VALUES (?, ?, ?)
            """,
            (personality_id, title, spec),
        )
        return personality_id

    @staticmethod
    def create_agent(
        db: sqlite3.Connection, agent_id: str, personality_id: str
    ) -> None:
        db.execute(
            """
            INSERT INTO agents (AGENT_ID, PERSONALITY)
            VALUES (?, ?)
            """,
            (agent_id, personality_id),
        )

    @staticmethod
    def upsert_event(
        db: sqlite3.Connection,
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
            "SELECT EVENT_ID FROM events WHERE SLUG = ? LIMIT 1", (slug,)
        ).fetchone()
        if existing is not None:
            event_id = int(existing[0])
            db.execute(
                """
                UPDATE events
                SET TITLE = ?, DESCRIPTION = ?, ICON_URL = ?, CATEGORY = ?,
                    START_DATE = ?, END_DATE = ?, POLYMARKET_EVENT_ID = ?
                WHERE EVENT_ID = ?
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
            cur = db.execute(
                """
                INSERT INTO events (SLUG, TITLE, DESCRIPTION, ICON_URL, CATEGORY,
                                    START_DATE, END_DATE, POLYMARKET_EVENT_ID)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            )
            event_id = int(cur.lastrowid or 0)
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
    def attach_market_to_event(
        db: sqlite3.Connection,
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
            SET EVENT_ID = ?,
                OUTCOME_LABEL = COALESCE(?, OUTCOME_LABEL),
                ICON_URL      = COALESCE(?, ICON_URL)
            WHERE MARKET_ID = ?
            """,
            (event_id, outcome_label, icon_url, market_id),
        )

    @staticmethod
    def create_market(
        db: sqlite3.Connection, request: CreateMarketRequest, is_polygon_market: bool
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

        row = db.execute(
            "SELECT COALESCE(MAX(MARKET_ID), 0) + 1 FROM markets"
        ).fetchone()
        next_market_id = int(row[0])

        db.execute(
            """
            INSERT INTO markets (MARKET_ID,
                                 CONDITION_ID,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                next_market_id,
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
        )

        return Market(
            question=request.question,
            market_id=next_market_id,
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
        db: sqlite3.Connection, request: CreateMarketRequest
    ) -> Market:
        # Compute condition_id from question and number of outcomes
        erc1155_tokens_json = json.dumps(request.erc1155_tokens, separators=(",", ":"))

        # Fetch existing market details to preserve state and IDs
        cursor = db.execute(
            "SELECT MARKET_ID, RESOLVED_OUTCOME FROM markets WHERE POLYMARKET_ID = ?",
            (request.polymarket_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(
                f"Market with Polymarket ID {request.polymarket_id} not found"
            )

        market_id, resolved_outcome = row

        db.execute(
            """
            UPDATE markets
            SET CONDITION_ID   = ?,
                QUESTION       = ?,
                DESCRIPTION    = ?,
                SLUG           = ?,
                START_DATE     = ?,
                END_DATE       = ?,
                ERC1155_TOKENS = ?,
                MARKET_STATE  = ?
            WHERE POLYMARKET_ID = ?
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
        db: sqlite3.Connection,
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
            VALUES (?, ?, ?, ?)
            """,
            (api_key, transaction_type, market_id, details_json),
        )

    @staticmethod
    def activate_market(db: sqlite3.Connection, market_id: int) -> Market:
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
            "UPDATE markets SET MARKET_STATE = ? WHERE MARKET_ID = ?",
            (MarketState.ACTIVE.value, market_id),
        )

        # Return updated market
        market.market_state = MarketState.ACTIVE
        return market

    @staticmethod
    def close_market(db: sqlite3.Connection, market_id: int) -> Market:
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
            "UPDATE markets SET MARKET_STATE = ? WHERE MARKET_ID = ?",
            (MarketState.CLOSED.value, market_id),
        )

        # Return updated market
        market.market_state = MarketState.CLOSED
        return market

    @staticmethod
    def resolve_market(
        db: sqlite3.Connection, market_id: int, winning_outcome_index: int
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
            "UPDATE markets SET MARKET_STATE = ?, RESOLVED_OUTCOME = ? WHERE MARKET_ID = ?",
            (MarketState.RESOLVED.value, winning_outcome_index, market_id),
        )

        # Return updated market
        market.market_state = MarketState.RESOLVED
        market.resolved_outcome = winning_outcome_index
        return market

    @staticmethod
    def cancel_market(db: sqlite3.Connection, market_id: int) -> tuple[Market, int]:
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
            "UPDATE markets SET MARKET_STATE = ? WHERE MARKET_ID = ?",
            (MarketState.CANCELLED.value, market_id),
        )

        market.market_state = MarketState.CANCELLED
        return market, 0

    @staticmethod
    def update_market_state_to_resolved_if_needed(
        db: sqlite3.Connection, condition_id: ConditionId, winning_outcome_index: int
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
            "UPDATE markets SET MARKET_STATE = ?, RESOLVED_OUTCOME = ? WHERE CONDITION_ID = ?",
            (
                MarketState.RESOLVED.value,
                winning_outcome_index,
                market.condition_id.value,
            ),
        )

        market.market_state = MarketState.RESOLVED
        market.resolved_outcome = winning_outcome_index
        return market
