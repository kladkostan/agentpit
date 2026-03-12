import sqlite3
import json
import uuid
from web3 import Web3
from eth_account import Account
from eth_account.signers.local import LocalAccount

from agentpit.common import check_state
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState
from agentpit.utils.condition_id import compute_condition_id


class TableWrite:
    @staticmethod
    def create_user(db: sqlite3.Connection, user_id: str) -> str:
        acct: LocalAccount = Account.create()
        key_hex: str = Web3.to_hex(acct.key)
        api_key: str = str(uuid.uuid4())

        db.execute(
            """
            INSERT INTO users (USER_ID, API_KEY, ETH_PRIVATE_KEY)
            VALUES (?, ?, ?)
            """,
            (user_id, api_key, key_hex),
        )
        return api_key

    @staticmethod
    def create_personality(
        db: sqlite3.Connection, personality_id: str, title: str, beliefs: str, methods: str, needs: str
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
    def create_market(
            db : sqlite3.Connection,
            request: CreateMarketRequest, is_polygon_market: bool
    ) -> Market:

        if not is_polygon_market:
            condition_id = compute_condition_id(request.question, len(request.erc1155_tokens))
        else:
            check_state(request.condition_id is not None)
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
                                 QUESTION,
                                 DESCRIPTION,
                                 SLUG,
                                 START_DATE,
                                 END_DATE,
                                 ERC1155_TOKENS,
                                 MARKET_STATE)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                next_market_id,
                condition_id.value,
                request.polymarket_id,
                request.question,
                request.description,
                request.slug,
                request.start_date,
                request.end_date,
                erc1155_tokens_json,
                request.state
            ),
        )

        return Market(
            question=request.question,
            market_id=next_market_id,
            polymarket_id=request.polymarket_id,
            condition_id=condition_id,
            description=request.description,
            slug=request.slug,
            erc1155_tokens=request.erc1155_tokens,
            market_state=MarketState(request.state),
            start_date=request.start_date,
            end_date=request.end_date,
            resolved_outcome=None
        )

    @staticmethod
    def update_market_state_if_needed(
            db: sqlite3.Connection,
            request: CreateMarketRequest
    ) -> Market:
        # Compute condition_id from question and number of outcomes
        erc1155_tokens_json = json.dumps(request.erc1155_tokens, separators=(",", ":"))

        # Fetch existing market details to preserve state and IDs
        cursor = db.execute(
            "SELECT MARKET_ID, RESOLVED_OUTCOME FROM markets WHERE POLYMARKET_ID = ?",
            (request.polymarket_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Market with Polymarket ID {request.polymarket_id} not found")

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
                request.polymarket_id
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
            resolved_outcome=resolved_outcome
        )

    @staticmethod
    def log_transaction(
            db: sqlite3.Connection,
            api_key: str,
            transaction_type: str,
            market_id: int | None = None,
            details: dict | None = None
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
            (api_key, transaction_type, market_id, details_json)
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
            raise ValueError(f"Market {market_id} is not in DRAFT state (current: {market.market_state.value})")

        # Update state
        db.execute(
            "UPDATE markets SET MARKET_STATE = ? WHERE MARKET_ID = ?",
            (MarketState.ACTIVE.value, market_id)
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
            raise ValueError(f"Market {market_id} is not in ACTIVE state (current: {market.market_state.value})")

        # Update state to CLOSED
        db.execute(
            "UPDATE markets SET MARKET_STATE = ? WHERE MARKET_ID = ?",
            (MarketState.CLOSED.value, market_id)
        )

        # Return updated market
        market.market_state = MarketState.CLOSED
        return market

    @staticmethod
    def resolve_market(
            db: sqlite3.Connection,
            market_id: int,
            winning_outcome_index: int
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
        if winning_outcome_index < 0 or winning_outcome_index >= len(market.erc1155_tokens):
            raise ValueError(
                f"Invalid winning_outcome_index {winning_outcome_index}. "
                f"Market has {len(market.erc1155_tokens)} outcomes (indices 0-{len(market.erc1155_tokens)-1})"
            )

        # Update state and outcome
        db.execute(
            "UPDATE markets SET MARKET_STATE = ?, RESOLVED_OUTCOME = ? WHERE MARKET_ID = ?",
            (MarketState.RESOLVED.value, winning_outcome_index, market_id)
        )

        # Return updated market
        market.market_state = MarketState.RESOLVED
        market.resolved_outcome = winning_outcome_index
        return market

    @staticmethod
    def cancel_market(db: sqlite3.Connection, market_id: int) -> tuple[Market, int]:
        """
        Cancel a market and refund all users who hold complete sets.

        Args:
            db: Database connection
            market_id: Market ID to cancel

        Returns:
            Tuple of (updated Market object, number of refunds processed)

        Raises:
            ValueError: If market not found or already resolved/cancelled
        """
        from agentpit.db.table_read import TableRead
        from agentpit.contract_simulators.erc20_simulator import ERC20Simulator
        from agentpit.contract_simulators.contract_addresses import EASYNET_USDC_TOKEN_ADDRESS
        from agentpit.db.table_utils import TableUtils
        from agentpit.utils.parse import normalize_eth_address, hex_u256_to_int
        from web3 import Web3

        # Get current market
        market = TableRead.read_market(db, market_id)
        if not market:
            raise ValueError(f"Market {market_id} not found")

        # Check state - cannot cancel if already resolved or cancelled
        if market.market_state == MarketState.RESOLVED:
            raise ValueError(f"Cannot cancel market {market_id}: already resolved")
        if market.market_state == MarketState.CANCELLED:
            raise ValueError(f"Market {market_id} is already cancelled")

        # Get all users with positions in this market
        # We need to scan all ERC1155 ownership records
        cursor = db.execute("SELECT ETH_ADDRESS, OWNERSHIP FROM erc1155_token_ownership")

        refunds_processed = 0
        token_ids = [token_id for token_id, _ in market.erc1155_tokens]

        for row in cursor.fetchall():
            eth_address, ownership_json = row
            if not ownership_json:
                continue

            ownership_map = json.loads(ownership_json)

            # Check if user has complete sets for this market
            # A complete set means having at least 1 of each outcome token
            min_complete_sets = None
            for token_id in token_ids:
                if token_id not in ownership_map:
                    min_complete_sets = 0
                    break
                balance = hex_u256_to_int(ownership_map[token_id])
                if min_complete_sets is None:
                    min_complete_sets = balance
                else:
                    min_complete_sets = min(min_complete_sets, balance)

            if min_complete_sets and min_complete_sets > 0:
                # Refund complete sets
                # Burn all the tokens
                for token_id in token_ids:
                    current_balance = hex_u256_to_int(ownership_map[token_id])
                    new_balance = current_balance - min_complete_sets
                    ownership_map[token_id] = Web3.to_hex(new_balance).lower()

                # Update ownership map
                TableUtils.store_erc1155_ownership_map(db, eth_address, ownership_map)

                # Mint USDC refund
                ERC20Simulator.mint(
                    db,
                    eth_address=eth_address,
                    asset_address=EASYNET_USDC_TOKEN_ADDRESS,
                    value=min_complete_sets,
                )

                refunds_processed += 1

        # Update market state to CANCELLED
        db.execute(
            "UPDATE markets SET MARKET_STATE = ? WHERE MARKET_ID = ?",
            (MarketState.CANCELLED.value, market_id)
        )

        # Return updated market
        market.market_state = MarketState.CANCELLED
        return market, refunds_processed

    @staticmethod
    def update_market_state_to_resolved_if_needed(
            db: sqlite3.Connection,
            condition_id: ConditionId,
            winning_outcome_index: int
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

        if market.market_state == MarketState.RESOLVED or market.market_state == MarketState.CANCELLED:
            return market

        # Validate outcome index
        if winning_outcome_index < 0 or winning_outcome_index >= len(market.erc1155_tokens):
            raise ValueError(
                f"Invalid winning_outcome_index {winning_outcome_index}. "
                f"Market has {len(market.erc1155_tokens)} outcomes"
            )

        db.execute(
            "UPDATE markets SET MARKET_STATE = ?, RESOLVED_OUTCOME = ? WHERE CONDITION_ID = ?",
            (MarketState.RESOLVED.value, winning_outcome_index, market.condition_id.value)
        )

        market.market_state = MarketState.RESOLVED
        market.resolved_outcome = winning_outcome_index
        return market
