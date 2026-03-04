import sqlite3

from agentpit.common import check_state
from agentpit.contract_simulators.erc20_simulator import ERC20Simulator
from agentpit.db.table_read import TableRead
from pydantic import ConfigDict, validate_call

USDC_TOKEN_ADDRESS: str = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
MARKET_TREASURY_ADDRESS: str = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"

_STRICT = ConfigDict(strict=True)


class PredictionMarket:
    @staticmethod
    @validate_call(config=_STRICT)
    def splitInDBUSDCTokenIntoEIP155Tokens(
        db: sqlite3.Connection,
        owner_address: str,
        market_id: int,
        usdc_amount: int,
    ) -> None:

        check_state(usdc_amount > 0, "usdc_amount must be positive")

        owner_usdc_holding = ERC20Simulator.get_balance(db, owner_address, USDC_TOKEN_ADDRESS)
        check_state(owner_usdc_holding >= usdc_amount, "Not enough USDC balance to split into market tokens")

        ERC20Simulator.transfer(db, owner_address, MARKET_TREASURY_ADDRESS, usdc_amount, USDC_TOKEN_ADDRESS)

        _market = TableRead.read_market(db, market_id)
