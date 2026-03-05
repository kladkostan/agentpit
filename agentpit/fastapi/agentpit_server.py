# agentpit/fastapi/agentpit_server.py
import os
import sqlite3
from fastapi import FastAPI, HTTPException

from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.mint_usdc_request import MintUsdcRequest
from agentpit.datastructures.mint_usdc_response import MintUsdcResponse
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

    def shutdown(self) -> None:
        if hasattr(self, "_db") and self._db is not None:
            self._db.close()
            self._db = None
        print("AgentPitServer is shutting down...")

