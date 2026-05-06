from web3 import Web3

from agentpit.contract_simulators.contract_addresses import EASYNET_USDC_TOKEN_ADDRESS
from agentpit.contract_simulators.erc20_simulator import ERC20Simulator
from agentpit.datastructures.market_state import MarketState
from agentpit.datastructures.position_response import PositionResponse
from agentpit.datastructures.redeem_position_request import RedeemPositionRequest
from agentpit.datastructures.redeem_position_response import RedeemPositionResponse
from agentpit.datastructures.split_position_request import SplitPositionRequest
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_utils import TableUtils
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import (
    InsufficientBalanceError,
    MarketNotFoundError,
    MarketStateError,
)
from agentpit.services.accounts import get_or_create_eth_address
from agentpit.utils.parse import hex_u256_to_int, normalize_eth_address


class PositionService:
    """Burns USDC for outcome tokens (split), the inverse (merge), and post-resolution payout (redeem)."""

    def __init__(self, db: DbSession):
        self._db = db

    def split(self, market_id: int, payload: SplitPositionRequest) -> PositionResponse:
        eth_address = get_or_create_eth_address(self._db, payload.api_key)
        collateral_amount = payload.amount

        with self._db.write() as conn:
            market = TableRead.read_market(conn, market_id)
            if market is None:
                raise MarketNotFoundError(market_id)

            try:
                ERC20Simulator.burn(
                    conn,
                    eth_address=eth_address,
                    asset_address=EASYNET_USDC_TOKEN_ADDRESS,
                    value=collateral_amount,
                )
            except ValueError as e:
                if "Insufficient balance" in str(e):
                    raise InsufficientBalanceError(f"Insufficient USDC balance: {e}") from e
                raise

            norm_address = normalize_eth_address(eth_address)
            TableUtils.ensure_erc1155_ownership_row(conn, norm_address)
            ownership_map = TableUtils.load_erc1155_ownership_map(conn, norm_address)

            token_balances: dict[str, int] = {}
            for token_id, _label in market.erc1155_tokens:
                current = hex_u256_to_int(ownership_map.get(token_id, "0x0"))
                new_balance = current + payload.amount
                ownership_map[token_id] = Web3.to_hex(new_balance).lower()
                token_balances[token_id] = new_balance

            TableUtils.store_erc1155_ownership_map(conn, norm_address, ownership_map)
            TableWrite.log_transaction(
                conn,
                api_key=payload.api_key,
                transaction_type="SPLIT",
                market_id=market_id,
                details={"amount": payload.amount, "collateral_burned": collateral_amount},
            )

        return PositionResponse(
            market_id=market_id,
            amount=payload.amount,
            collateral_amount=collateral_amount,
            token_balances=token_balances,
        )

    def merge(self, market_id: int, payload: SplitPositionRequest) -> PositionResponse:
        eth_address = get_or_create_eth_address(self._db, payload.api_key)
        collateral_amount = payload.amount

        with self._db.write() as conn:
            market = TableRead.read_market(conn, market_id)
            if market is None:
                raise MarketNotFoundError(market_id)

            norm_address = normalize_eth_address(eth_address)
            TableUtils.ensure_erc1155_ownership_row(conn, norm_address)
            ownership_map = TableUtils.load_erc1155_ownership_map(conn, norm_address)

            for token_id, _label in market.erc1155_tokens:
                balance = hex_u256_to_int(ownership_map.get(token_id, "0x0"))
                if balance < payload.amount:
                    raise InsufficientBalanceError(
                        f"Insufficient balance of token {token_id}: have {balance}, need {payload.amount}"
                    )

            token_balances: dict[str, int] = {}
            for token_id, _label in market.erc1155_tokens:
                current = hex_u256_to_int(ownership_map.get(token_id, "0x0"))
                new_balance = current - payload.amount
                ownership_map[token_id] = Web3.to_hex(new_balance).lower()
                token_balances[token_id] = new_balance

            TableUtils.store_erc1155_ownership_map(conn, norm_address, ownership_map)

            ERC20Simulator.mint(
                conn,
                eth_address=eth_address,
                asset_address=EASYNET_USDC_TOKEN_ADDRESS,
                value=collateral_amount,
            )

            TableWrite.log_transaction(
                conn,
                api_key=payload.api_key,
                transaction_type="MERGE",
                market_id=market_id,
                details={"amount": payload.amount, "collateral_minted": collateral_amount},
            )

        return PositionResponse(
            market_id=market_id,
            amount=payload.amount,
            collateral_amount=collateral_amount,
            token_balances=token_balances,
        )

    def redeem(self, market_id: int, payload: RedeemPositionRequest) -> RedeemPositionResponse:
        eth_address = get_or_create_eth_address(self._db, payload.api_key)

        with self._db.write() as conn:
            market = TableRead.read_market(conn, market_id)
            if market is None:
                raise MarketNotFoundError(market_id)
            if market.market_state != MarketState.RESOLVED:
                raise MarketStateError("Market is not resolved yet")
            if market.resolved_outcome is None:
                raise MarketStateError("Market has no resolved outcome")

            norm_address = normalize_eth_address(eth_address)
            TableUtils.ensure_erc1155_ownership_row(conn, norm_address)
            ownership_map = TableUtils.load_erc1155_ownership_map(conn, norm_address)

            payout_usdc = 0
            tokens_redeemed: dict[str, int] = {}
            winning_token_id = market.erc1155_tokens[market.resolved_outcome][0]

            for token_id, _label in market.erc1155_tokens:
                balance = hex_u256_to_int(ownership_map.get(token_id, "0x0"))
                if balance > 0:
                    tokens_redeemed[token_id] = balance
                    if token_id == winning_token_id:
                        payout_usdc += balance
                    ownership_map[token_id] = "0x0"

            TableUtils.store_erc1155_ownership_map(conn, norm_address, ownership_map)

            if payout_usdc > 0:
                ERC20Simulator.mint(
                    conn,
                    eth_address=eth_address,
                    asset_address=EASYNET_USDC_TOKEN_ADDRESS,
                    value=payout_usdc,
                )

            TableWrite.log_transaction(
                conn,
                api_key=payload.api_key,
                transaction_type="REDEEM",
                market_id=market_id,
                details={"payout_usdc": payout_usdc, "tokens_redeemed": tokens_redeemed},
            )

        return RedeemPositionResponse(
            market_id=market_id,
            payout_usdc=payout_usdc,
            tokens_redeemed=tokens_redeemed,
        )
