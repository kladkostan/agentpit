from agentpit_clob.contract_simulators.erc20_simulator import ERC20Simulator

USDC_TOKEN_ADDRESS: str = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"

class Polymarket:
    def splitInDBUSDCTokenIntoEIP155TokenForMarket(self, owner_address: str, market_id: int, usdc_amount: int) -> None
        if self.market_id != market_id:
            raise ValueError("market_id does not match this market")
        if len(self.erc155_tokens) != 2:
            raise ValueError("market must have exactly 2 erc155 tokens to split USDC token into them")

        owner_usdc_holding = ERC20Simulator.get_balance(self.db, owner_address, USDC_TOKEN_ADDRESS)

