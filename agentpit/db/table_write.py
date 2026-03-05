import json
import sqlite3

from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState
from agentpit.utils.condition_id import compute_condition_id


class TableWrite:
    @staticmethod
    def create_market(
        db: sqlite3.Connection,
        question: str,
        description: str,
        erc155_tokens: list,
    ) -> Market:
        # Compute condition_id from question and number of outcomes
        condition_id = compute_condition_id(question, len(erc155_tokens))
        condition_id_hex = "0x" + condition_id.hex()

        erc155_tokens_json = json.dumps(erc155_tokens, separators=(",", ":"))

        with db:
            row = db.execute(
                "SELECT COALESCE(MAX(MARKET_ID), 0) + 1 FROM markets"
            ).fetchone()
            next_market_id = int(row[0])

            db.execute(
                """
                INSERT INTO markets (MARKET_ID, CONDITION_ID, QUESTION, DESCRIPTION, ERC155_TOKENS)
                VALUES (?, ?, ?, ?, ?)
                """,
                (next_market_id, condition_id_hex, question, description, erc155_tokens_json),
            )

        return Market(
            question=question,
            market_id=next_market_id,
            condition_id=condition_id_hex,
            description=description,
            erc155_tokens=erc155_tokens,
            market_state=MarketState.DRAFT,
        )

    @staticmethod
    def resolve_market(
        db: sqlite3.Connection,
        market_id: int,
        winning_outcome_index: int,
    ) -> Market:
        """Resolve a market with a winning outcome."""
        # First, read the market to validate
        from agentpit.db.table_read import TableRead
        market = TableRead.read_market(db, market_id)
        if market is None:
            raise ValueError(f"Market {market_id} not found")

        if market.market_state == "RESOLVED":
            raise ValueError(f"Market {market_id} is already resolved")

        # Validate winning outcome index
        if winning_outcome_index < 0 or winning_outcome_index >= len(market.erc155_tokens):
            raise ValueError(
                f"Invalid winning outcome index {winning_outcome_index}. "
                f"Market has {len(market.erc155_tokens)} outcomes (indices 0-{len(market.erc155_tokens)-1})"
            )

        # Update the market state and resolved outcome
        db.execute(
            """
            UPDATE markets
            SET market_state = 'RESOLVED',
                resolved_outcome = ?
            WHERE market_id = ?
            """,
            (winning_outcome_index, market_id),
        )
        db.commit()

        # Return the updated market
        return TableRead.read_market(db, market_id)

    @staticmethod
    def activate_market(db: sqlite3.Connection, market_id: int) -> Market:
        """Activate a market, transitioning it from DRAFT to ACTIVE."""
        from agentpit.db.table_read import TableRead
        market = TableRead.read_market(db, market_id)
        if market is None:
            raise ValueError(f"Market {market_id} not found")

        if market.market_state != "DRAFT":
            raise ValueError(f"Market {market_id} is not in DRAFT state (current: {market.market_state})")

        db.execute(
            """
            UPDATE markets
            SET market_state = 'ACTIVE'
            WHERE market_id = ?
            """,
            (market_id,),
        )
        db.commit()

        return TableRead.read_market(db, market_id)

    @staticmethod
    def close_market(db: sqlite3.Connection, market_id: int) -> Market:
        """Close a market, transitioning it from ACTIVE to CLOSED."""
        from agentpit.db.table_read import TableRead
        market = TableRead.read_market(db, market_id)
        if market is None:
            raise ValueError(f"Market {market_id} not found")

        if market.market_state != "ACTIVE":
            raise ValueError(f"Market {market_id} is not in ACTIVE state (current: {market.market_state})")

        db.execute(
            """
            UPDATE markets
            SET market_state = 'CLOSED'
            WHERE market_id = ?
            """,
            (market_id,),
        )
        db.commit()

        return TableRead.read_market(db, market_id)

    @staticmethod
    def cancel_market(db: sqlite3.Connection, market_id: int) -> tuple[Market, int]:
        """
        Cancel a market, transitioning it to CANCELLED state.
        Returns the market and the number of users who had positions refunded.
        """
        from agentpit.db.table_read import TableRead
        from agentpit.db.table_utils import TableUtils
        from agentpit.contract_simulators.erc20_simulator import ERC20Simulator
        from agentpit.contract_simulators.contract_addresses import EASYNET_USDC_TOKEN_ADDRESS
        from agentpit.utils.parse import normalize_eth_address, hex_u256_to_int
        from web3 import Web3

        market = TableRead.read_market(db, market_id)
        if market is None:
            raise ValueError(f"Market {market_id} not found")

        if market.market_state in ["RESOLVED", "CANCELLED"]:
            raise ValueError(f"Market {market_id} is already {market.market_state}")

        # Get all token IDs for this market
        token_ids = [token_id for token_id, _label in market.erc155_tokens]

        # Find all users who hold tokens for this market and refund them
        refunds_processed = 0
        cursor = db.execute("SELECT ETH_ADDRESS FROM erc1155_ownership")

        for (eth_address,) in cursor.fetchall():
            norm_address = normalize_eth_address(eth_address)
            ownership_map = TableUtils.load_erc155_ownership_map(db, norm_address)

            # Calculate how many complete sets this user has
            min_balance = None
            for token_id in token_ids:
                balance = hex_u256_to_int(ownership_map.get(token_id, "0x0"))
                if min_balance is None or balance < min_balance:
                    min_balance = balance

            # If user has complete sets, refund them and burn the tokens
            if min_balance and min_balance > 0:
                # Burn all tokens for this market
                for token_id in token_ids:
                    current = hex_u256_to_int(ownership_map.get(token_id, "0x0"))
                    new_balance = current - min_balance
                    ownership_map[token_id] = Web3.to_hex(new_balance).lower()

                # Save updated ownership
                TableUtils.store_erc155_ownership_map(db, norm_address, ownership_map)

                # Refund USDC (1 USDC per complete set)
                ERC20Simulator.mint(
                    db,
                    eth_address=eth_address,
                    asset_address=EASYNET_USDC_TOKEN_ADDRESS,
                    value=min_balance,
                )

                refunds_processed += 1

        # Update market state to CANCELLED
        db.execute(
            """
            UPDATE markets
            SET market_state = 'CANCELLED'
            WHERE market_id = ?
            """,
            (market_id,),
        )
        db.commit()

        return TableRead.read_market(db, market_id), refunds_processed

