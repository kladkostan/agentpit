from agentpit.contract_simulators.contract_addresses import EASYNET_USDC_TOKEN_ADDRESS
from agentpit.contract_simulators.erc20_simulator import ERC20Simulator
from agentpit.datastructures.get_usdc_balance_response import GetUsdcBalanceResponse
from agentpit.datastructures.mint_usdc_request import MintUsdcRequest
from agentpit.datastructures.mint_usdc_response import MintUsdcResponse
from agentpit.datastructures.transfer_usdc_request import TransferUsdcRequest
from agentpit.datastructures.transfer_usdc_response import TransferUsdcResponse
from agentpit.db.session import DbSession
from agentpit.domain.exceptions import InsufficientBalanceError
from agentpit.services.accounts import get_or_create_eth_address


class UsdcService:
    def __init__(self, db: DbSession):
        self._db = db

    def mint(self, payload: MintUsdcRequest) -> MintUsdcResponse:
        eth_address = get_or_create_eth_address(self._db, payload.api_key)
        with self._db.write() as conn:
            ERC20Simulator.mint(
                conn,
                eth_address=eth_address,
                asset_address=EASYNET_USDC_TOKEN_ADDRESS,
                value=payload.amount,
            )
            new_balance = ERC20Simulator.get_balance(
                conn,
                eth_address=eth_address,
                asset_address=EASYNET_USDC_TOKEN_ADDRESS,
            )
        return MintUsdcResponse(
            eth_address=eth_address,
            amount=payload.amount,
            new_balance=new_balance,
        )

    def get_balance(self, api_key: str) -> GetUsdcBalanceResponse:
        eth_address = get_or_create_eth_address(self._db, api_key)
        with self._db.read() as conn:
            balance = ERC20Simulator.get_balance(
                conn,
                eth_address=eth_address,
                asset_address=EASYNET_USDC_TOKEN_ADDRESS,
            )
        return GetUsdcBalanceResponse(eth_address=eth_address, balance=balance)

    def transfer(self, payload: TransferUsdcRequest) -> TransferUsdcResponse:
        from_address = get_or_create_eth_address(self._db, payload.api_key)
        with self._db.write() as conn:
            try:
                ERC20Simulator.transfer(
                    conn,
                    src_address=from_address,
                    destination_address=payload.destination_address,
                    value=payload.amount,
                    asset_address=EASYNET_USDC_TOKEN_ADDRESS,
                )
            except ValueError as e:
                if "Insufficient balance" in str(e):
                    raise InsufficientBalanceError(str(e)) from e
                raise
            new_balance = ERC20Simulator.get_balance(
                conn,
                eth_address=from_address,
                asset_address=EASYNET_USDC_TOKEN_ADDRESS,
            )
        return TransferUsdcResponse(
            from_address=from_address,
            to_address=payload.destination_address,
            amount=payload.amount,
            new_balance=new_balance,
        )
