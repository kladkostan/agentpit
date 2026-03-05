# agentpit/fastapi/agentpit_server.py
import os
import sqlite3
from fastapi import FastAPI, HTTPException

from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.mint_usdc_request import MintUsdcRequest
from agentpit.datastructures.mint_usdc_response import MintUsdcResponse
from agentpit.datastructures.get_usdc_balance_response import GetUsdcBalanceResponse
from agentpit.datastructures.transfer_usdc_request import TransferUsdcRequest
from agentpit.datastructures.transfer_usdc_response import TransferUsdcResponse
from agentpit.datastructures.list_markets_response import ListMarketsResponse
from agentpit.db.table_create import TableCreate
from agentpit.db.table_write import TableWrite
from agentpit.db.table_read import TableRead
from agentpit.datastructures.market import Market
from agentpit.contract_simulators.erc20_simulator import ERC20Simulator
from agentpit.contract_simulators.contract_addresses import EASYNET_USDC_TOKEN_ADDRESS

class AgentPitServer(FastAPI):
    def __init__(self, *args, db_path: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
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
            question=payload.question,
            description=payload.description,
            erc155_tokens=payload.erc155_tokens,
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

    def shutdown(self) -> None:
        if hasattr(self, "_db") and self._db is not None:
            self._db.close()
            self._db = None
        print("AgentPitServer is shutting down...")

