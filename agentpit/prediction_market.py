from pydantic import ConfigDict, validate_call

from agentpit.contract_simulators.contract_addresses import EASYNET_USDC_TOKEN_ADDRESS, EASYNET_MARKET_TREASURY_ADDRESS

_STRICT = ConfigDict(strict=True)


import sqlite3

from agentpit.common import check_state
from agentpit.contract_simulators.erc1155_simulator import ERC115Simulator
from agentpit.contract_simulators.erc20_simulator import ERC20Simulator
from agentpit.db.table_read import TableRead
from pydantic import ConfigDict, validate_call

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

        owner_usdc_holding = ERC20Simulator.get_balance(db, owner_address, EASYNET_USDC_TOKEN_ADDRESS)
        check_state(owner_usdc_holding >= usdc_amount, "Not enough USDC balance to split into market tokens")

        ERC20Simulator.transfer(db, owner_address, EASYNET_MARKET_TREASURY_ADDRESS, usdc_amount, EASYNET_USDC_TOKEN_ADDRESS)

        market = TableRead.read_market(db, market_id)

        check_state(market is not None, "Market not found")

        market_tokens = market.erc155_tokens

        for token_id, _ in market_tokens:
            ERC115Simulator.mint(db, owner_address, token_id, usdc_amount)










