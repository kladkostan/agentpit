# agentpit/fastapi/agentpit_server.py
import os
import sqlite3
from fastapi import FastAPI, HTTPException
from web3 import Web3
import logging

from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.mint_usdc_request import MintUsdcRequest
from agentpit.datastructures.mint_usdc_response import MintUsdcResponse
from agentpit.datastructures.get_usdc_balance_response import GetUsdcBalanceResponse
from agentpit.datastructures.transfer_usdc_request import TransferUsdcRequest
from agentpit.datastructures.transfer_usdc_response import TransferUsdcResponse
from agentpit.datastructures.list_markets_response import ListMarketsResponse
from agentpit.datastructures.split_position_request import SplitPositionRequest
from agentpit.datastructures.position_response import PositionResponse
from agentpit.datastructures.resolve_market_request import ResolveMarketRequest
from agentpit.datastructures.redeem_position_request import RedeemPositionRequest
from agentpit.datastructures.redeem_position_response import RedeemPositionResponse
from agentpit.datastructures.cancel_market_response import CancelMarketResponse
from agentpit.datastructures.portfolio_response import PortfolioResponse, Position
from agentpit.datastructures.transaction_history_response import TransactionHistoryResponse
from agentpit.db.table_create import TableCreate
from agentpit.db.table_write import TableWrite
from agentpit.db.table_read import TableRead
from agentpit.datastructures.market import Market
from agentpit.contract_simulators.erc20_simulator import ERC20Simulator
from agentpit.contract_simulators.erc1155_simulator import ERC1155Simulator
from agentpit.contract_simulators.contract_addresses import EASYNET_USDC_TOKEN_ADDRESS
from agentpit.db.table_utils import TableUtils
from agentpit.utils.parse import normalize_eth_address, hex_u256_to_int

class AgentPitServer(FastAPI):
    def __init__(self, *args, db_path: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        AgentPitServer.configureLogging()
        self._db_path = db_path or os.getenv("AGENTPIT_DB_PATH", ":memory:")
        self._connect_db()
        self.add_api_route("/", self.get_version, methods=["GET"])
        self.add_api_route(
            "/markets",
            self.list_markets,
            methods=["GET"],
            response_model=ListMarketsResponse,
        )
        self.add_api_route(
            "/markets",
            self.create_market,
            methods=["POST"],
            response_model=Market,
        )
        self.add_api_route(
            "/markets/{market_id}",
            self.get_market,
            methods=["GET"],
            response_model=Market,
        )
        self.add_api_route(
            "/mint_usdc",
            self.mint_usdc,
            methods=["POST"],
            response_model=MintUsdcResponse,
        )
        self.add_api_route(
            "/usdc_balance/{api_key}",
            self.get_usdc_balance,
            methods=["GET"],
            response_model=GetUsdcBalanceResponse,
        )
        self.add_api_route(
            "/transfer_usdc",
            self.transfer_usdc,
            methods=["POST"],
            response_model=TransferUsdcResponse,
        )
        self.add_api_route(
            "/markets/{market_id}/split_position",
            self.split_position,
            methods=["POST"],
            response_model=PositionResponse,
        )
        self.add_api_route(
            "/markets/{market_id}/merge_positions",
            self.merge_positions,
            methods=["POST"],
            response_model=PositionResponse,
        )
        self.add_api_route(
            "/markets/{market_id}/resolve",
            self.resolve_market,
            methods=["POST"],
            response_model=Market,
        )
        self.add_api_route(
            "/markets/{market_id}/redeem_position",
            self.redeem_position,
            methods=["POST"],
            response_model=RedeemPositionResponse,
        )
        self.add_api_route(
            "/markets/{market_id}/activate",
            self.activate_market,
            methods=["POST"],
            response_model=Market,
        )
        self.add_api_route(
            "/markets/{market_id}/close",
            self.close_market,
            methods=["POST"],
            response_model=Market,
        )
        self.add_api_route(
            "/markets/{market_id}/cancel",
            self.cancel_market,
            methods=["POST"],
            response_model=CancelMarketResponse,
        )
        self.add_api_route(
            "/portfolio/{api_key}",
            self.get_portfolio,
            methods=["GET"],
            response_model=PortfolioResponse,
        )
        self.add_api_route(
            "/markets/history/{api_key}",
            self.get_transaction_history,
            methods=["GET"],
            response_model=TransactionHistoryResponse,
        )

    def _connect_db(self) -> None:
        self._db = sqlite3.connect(self._db_path, check_same_thread=False)
        TableCreate.create_all_tables(self._db)

    def _ensure_db(self) -> None:
        if not hasattr(self, "_db") or self._db is None:
            self._connect_db()
            return
        try:
            self._db.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            self._connect_db()

    def get_version(self) -> dict[str, str]:
        return {"version": "1.0"}

    def create_market(self, payload: CreateMarketRequest) -> Market:
        self._ensure_db()
        return TableWrite.create_market(
            self._db,
            payload, False
        )

    def list_markets(self, limit: int = 100, offset: int = 0) -> ListMarketsResponse:
        self._ensure_db()
        # Validate pagination parameters
        if limit < 1 or limit > 1000:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset must be non-negative")

        markets, total = TableRead.list_markets(self._db, limit=limit, offset=offset)
        return ListMarketsResponse(
            markets=markets,
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_market(self, market_id: int) -> Market:
        self._ensure_db()
        market = TableRead.read_market(self._db, market_id)
        if market is None:
            raise HTTPException(status_code=404, detail="Market not found")
        return market

    def mint_usdc(self, payload: MintUsdcRequest) -> MintUsdcResponse:
        self._ensure_db()
        # Get the ETH address for this API key
        eth_address = TableRead.get_eth_address_for_api_key(self._db, payload.api_key)

        # Mint USDC to the user's address
        ERC20Simulator.mint(
            self._db,
            eth_address=eth_address,
            asset_address=EASYNET_USDC_TOKEN_ADDRESS,
            value=payload.amount,
        )

        # Get the new balance
        new_balance = ERC20Simulator.get_balance(
            self._db,
            eth_address=eth_address,
            asset_address=EASYNET_USDC_TOKEN_ADDRESS,
        )

        return MintUsdcResponse(
            eth_address=eth_address,
            amount=payload.amount,
            new_balance=new_balance,
        )

    def get_usdc_balance(self, api_key: str) -> GetUsdcBalanceResponse:
        self._ensure_db()
        # Get the ETH address for this API key
        eth_address = TableRead.get_eth_address_for_api_key(self._db, api_key)

        # Get the balance
        balance = ERC20Simulator.get_balance(
            self._db,
            eth_address=eth_address,
            asset_address=EASYNET_USDC_TOKEN_ADDRESS,
        )

        return GetUsdcBalanceResponse(
            eth_address=eth_address,
            balance=balance,
        )

    def transfer_usdc(self, payload: TransferUsdcRequest) -> TransferUsdcResponse:
        self._ensure_db()
        # Get the ETH address for this API key
        from_address = TableRead.get_eth_address_for_api_key(self._db, payload.api_key)

        try:
            # Transfer USDC from user's address to destination
            ERC20Simulator.transfer(
                self._db,
                src_address=from_address,
                destination_address=payload.destination_address,
                value=payload.amount,
                asset_address=EASYNET_USDC_TOKEN_ADDRESS,
            )
        except ValueError as e:
            if "Insufficient balance" in str(e):
                raise HTTPException(status_code=400, detail=str(e))
            raise

        # Get the new balance
        new_balance = ERC20Simulator.get_balance(
            self._db,
            eth_address=from_address,
            asset_address=EASYNET_USDC_TOKEN_ADDRESS,
        )

        return TransferUsdcResponse(
            from_address=from_address,
            to_address=payload.destination_address,
            amount=payload.amount,
            new_balance=new_balance,
        )

    def split_position(self, market_id: int, payload: SplitPositionRequest) -> PositionResponse:
        """
        Split a position into outcome tokens for a market.
        Burns USDC collateral and mints 1 of each outcome token per complete set.
        """
        self._ensure_db()

        # Get market to find outcome tokens
        market = TableRead.read_market(self._db, market_id)
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")

        # Get user's ETH address
        eth_address = TableRead.get_eth_address_for_api_key(self._db, payload.api_key)

        # Calculate collateral needed (1 USDC per complete set)
        collateral_amount = payload.amount

        # Burn USDC collateral
        try:
            ERC20Simulator.burn(
                self._db,
                eth_address=eth_address,
                asset_address=EASYNET_USDC_TOKEN_ADDRESS,
                value=collateral_amount,
            )
        except ValueError as e:
            if "Insufficient balance" in str(e):
                raise HTTPException(status_code=400, detail=f"Insufficient USDC balance: {e}")
            raise

        # Mint outcome tokens (1 of each per set)
        token_balances = {}
        norm_address = normalize_eth_address(eth_address)
        TableUtils.ensure_erc1155_ownership_row(self._db, norm_address)
        ownership_map = TableUtils.load_erc1155_ownership_map(self._db, norm_address)

        for token_id, _label in market.erc1155_tokens:
            # Get current balance
            current = hex_u256_to_int(ownership_map.get(token_id, "0x0"))
            # Add the minted amount
            new_balance = current + payload.amount
            ownership_map[token_id] = Web3.to_hex(new_balance).lower()
            token_balances[token_id] = new_balance

        # Store updated ownership map
        TableUtils.store_erc1155_ownership_map(self._db, norm_address, ownership_map)

        # Log the transaction
        TableWrite.log_transaction(
            self._db,
            api_key=payload.api_key,
            transaction_type="SPLIT",
            market_id=market_id,
            details={
                "amount": payload.amount,
                "collateral_burned": collateral_amount,
            },
        )

        return PositionResponse(
            market_id=market_id,
            amount=payload.amount,
            collateral_amount=collateral_amount,
            token_balances=token_balances,
        )

    def merge_positions(self, market_id: int, payload: SplitPositionRequest) -> PositionResponse:
        """
        Merge complete sets of outcome tokens back to USDC collateral.
        Burns 1 of each outcome token per set and mints USDC.
        """
        self._ensure_db()

        # Get market to find outcome tokens
        market = TableRead.read_market(self._db, market_id)
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")

        # Get user's ETH address
        eth_address = TableRead.get_eth_address_for_api_key(self._db, payload.api_key)

        # Load ownership map
        norm_address = normalize_eth_address(eth_address)
        TableUtils.ensure_erc1155_ownership_row(self._db, norm_address)
        ownership_map = TableUtils.load_erc1155_ownership_map(self._db, norm_address)

        # Check user has enough of each outcome token
        for token_id, _label in market.erc1155_tokens:
            balance = hex_u256_to_int(ownership_map.get(token_id, "0x0"))
            if balance < payload.amount:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient balance of token {token_id}: have {balance}, need {payload.amount}"
                )

        # Burn outcome tokens
        token_balances = {}
        for token_id, _label in market.erc1155_tokens:
            current = hex_u256_to_int(ownership_map.get(token_id, "0x0"))
            new_balance = current - payload.amount
            ownership_map[token_id] = Web3.to_hex(new_balance).lower()
            token_balances[token_id] = new_balance

        # Store updated ownership map
        TableUtils.store_erc1155_ownership_map(self._db, norm_address, ownership_map)

        # Mint USDC collateral (1 USDC per complete set)
        collateral_amount = payload.amount
        ERC20Simulator.mint(
            self._db,
            eth_address=eth_address,
            asset_address=EASYNET_USDC_TOKEN_ADDRESS,
            value=collateral_amount,
        )

        # Log the transaction
        TableWrite.log_transaction(
            self._db,
            api_key=payload.api_key,
            transaction_type="MERGE",
            market_id=market_id,
            details={
                "amount": payload.amount,
                "collateral_minted": collateral_amount,
            },
        )

        return PositionResponse(
            market_id=market_id,
            amount=payload.amount,
            collateral_amount=collateral_amount,
            token_balances=token_balances,
        )

    def resolve_market(self, market_id: int, payload: ResolveMarketRequest) -> Market:
        """
        Resolve a market by specifying the winning outcome.
        After resolution, users can redeem their winning tokens for USDC.
        """
        self._ensure_db()

        # Check if market exists first to return 404 if not found
        market = TableRead.read_market(self._db, market_id)
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")

        try:
            return TableWrite.resolve_market(
                self._db,
                market_id=market_id,
                winning_outcome_index=payload.winning_outcome_index,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    def redeem_position(self, market_id: int, payload: RedeemPositionRequest) -> RedeemPositionResponse:
        """
        Redeem outcome tokens for USDC after a market has been resolved.
        Burns all outcome tokens held by the user.
        Winning tokens are redeemed at 1 USDC per token, losing tokens get nothing.
        """
        self._ensure_db()

        # Get market to check if it's resolved
        market = TableRead.read_market(self._db, market_id)
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")

        if market.market_state != "RESOLVED":
            raise HTTPException(status_code=400, detail="Market is not resolved yet")

        if market.resolved_outcome is None:
            raise HTTPException(status_code=400, detail="Market has no resolved outcome")

        # Get user's ETH address
        eth_address = TableRead.get_eth_address_for_api_key(self._db, payload.api_key)

        # Load user's token balances
        norm_address = normalize_eth_address(eth_address)
        TableUtils.ensure_erc1155_ownership_row(self._db, norm_address)
        ownership_map = TableUtils.load_erc1155_ownership_map(self._db, norm_address)

        # Calculate payout and burn all tokens
        payout_usdc = 0
        tokens_redeemed = {}
        winning_token_id = market.erc1155_tokens[market.resolved_outcome][0]

        for token_id, _label in market.erc1155_tokens:
            balance = hex_u256_to_int(ownership_map.get(token_id, "0x0"))
            if balance > 0:
                tokens_redeemed[token_id] = balance
                # Only winning tokens get USDC payout
                if token_id == winning_token_id:
                    payout_usdc += balance
                # Burn all tokens (set to 0)
                ownership_map[token_id] = "0x0"

        # Store updated ownership map (with all tokens burned)
        TableUtils.store_erc1155_ownership_map(self._db, norm_address, ownership_map)

        # Mint USDC payout to user if they had winning tokens
        if payout_usdc > 0:
            ERC20Simulator.mint(
                self._db,
                eth_address=eth_address,
                asset_address=EASYNET_USDC_TOKEN_ADDRESS,
                value=payout_usdc,
            )

        # Log the transaction
        TableWrite.log_transaction(
            self._db,
            api_key=payload.api_key,
            transaction_type="REDEEM",
            market_id=market_id,
            details={
                "payout_usdc": payout_usdc,
                "tokens_redeemed": tokens_redeemed,
            },
        )

        return RedeemPositionResponse(
            market_id=market_id,
            payout_usdc=payout_usdc,
            tokens_redeemed=tokens_redeemed,
        )

    def activate_market(self, market_id: int) -> Market:
        """Activate a market, transitioning it from DRAFT to ACTIVE."""
        self._ensure_db()
        try:
            return TableWrite.activate_market(self._db, market_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    def close_market(self, market_id: int) -> Market:
        """Close a market, transitioning it from ACTIVE to CLOSED."""
        self._ensure_db()
        try:
            return TableWrite.close_market(self._db, market_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    def cancel_market(self, market_id: int) -> CancelMarketResponse:
        """Cancel a market and refund all users who hold complete sets."""
        self._ensure_db()
        try:
            market, refunds_processed = TableWrite.cancel_market(self._db, market_id)
            return CancelMarketResponse(
                market_id=market.market_id,
                message=f"Market cancelled successfully",
                refunds_processed=refunds_processed,
                market=market,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    def get_portfolio(self, api_key: str) -> PortfolioResponse:
        """
        Get a summary of a user's holdings, including USDC and outcome tokens.
        """
        self._ensure_db()
        eth_address = TableRead.get_eth_address_for_api_key(self._db, api_key)

        # 1. Get USDC Balance
        usdc_balance = ERC20Simulator.get_balance(
            self._db,
            eth_address=eth_address,
            asset_address=EASYNET_USDC_TOKEN_ADDRESS,
        )

        # 2. Get ERC1155 Positions
        positions = []
        norm_address = normalize_eth_address(eth_address)

        # Load user's token map. Handle case where user has no entry yet.
        try:
            ownership_map = TableUtils.load_erc1155_ownership_map(self._db, norm_address)
        except sqlite3.OperationalError: # More specific exception
            ownership_map = {}

        if ownership_map:
            # We have some tokens. We need to match token_ids to markets.
            # For simplicity in this simulation, we scan all markets.
            # In a production DB, we'd have a joinable table for tokens.
            all_markets, _ = TableRead.list_markets(self._db, limit=10000)

            for market in all_markets:
                outcomes = market.erc1155_tokens
                for idx, (token_id, label) in enumerate(outcomes):
                    if token_id in ownership_map:
                        balance = hex_u256_to_int(ownership_map[token_id])
                        if balance > 0:
                            positions.append(Position(
                                market_id=market.market_id,
                                question=market.question,
                                token_id=token_id,
                                outcome_label=label,
                                outcome_index=idx,
                                balance=balance
                            ))

        return PortfolioResponse(
            eth_address=eth_address,
            usdc_balance=usdc_balance,
            positions=positions
        )

    def get_transaction_history(self, api_key: str) -> TransactionHistoryResponse:
        """
        Get a user's transaction history.
        """
        self._ensure_db()
        eth_address = TableRead.get_eth_address_for_api_key(self._db, api_key)
        transactions = TableRead.get_transaction_history(self._db, api_key)
        return TransactionHistoryResponse(
            eth_address=eth_address,
            transactions=transactions,
        )

    def shutdown(self) -> None:
        if hasattr(self, "_db") and self._db is not None:
            self._db.close()
            self._db = None
        print("AgentPitServer is shutting down...")

    @staticmethod
    def configureLogging():
        root = logging.getLogger()
        root.setLevel(logging.INFO)

        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)

        root.handlers.clear()
        root.addHandler(handler)
