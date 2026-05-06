import sqlite3

from agentpit.contract_simulators.contract_addresses import EASYNET_USDC_TOKEN_ADDRESS
from agentpit.contract_simulators.erc20_simulator import ERC20Simulator
from agentpit.datastructures.portfolio_response import PortfolioResponse, Position
from agentpit.datastructures.transaction_history_response import TransactionHistoryResponse
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_utils import TableUtils
from agentpit.services.accounts import get_or_create_eth_address
from agentpit.utils.parse import hex_u256_to_int, normalize_eth_address


class PortfolioService:
    def __init__(self, db: DbSession):
        self._db = db

    def get_portfolio(self, api_key: str) -> PortfolioResponse:
        eth_address = get_or_create_eth_address(self._db, api_key)
        norm_address = normalize_eth_address(eth_address)

        with self._db.read() as conn:
            usdc_balance = ERC20Simulator.get_balance(
                conn,
                eth_address=eth_address,
                asset_address=EASYNET_USDC_TOKEN_ADDRESS,
            )

            try:
                ownership_map = TableUtils.load_erc1155_ownership_map(conn, norm_address)
            except sqlite3.OperationalError:
                ownership_map = {}

            positions: list[Position] = []
            if ownership_map:
                # No joinable token->market table exists, so scan markets and
                # filter by token ids the user actually owns.
                all_markets, _ = TableRead.list_markets(conn, limit=10000)
                for market in all_markets:
                    for idx, (token_id, label) in enumerate(market.erc1155_tokens):
                        if token_id not in ownership_map:
                            continue
                        balance = hex_u256_to_int(ownership_map[token_id])
                        if balance <= 0:
                            continue
                        positions.append(
                            Position(
                                market_id=market.market_id,
                                question=market.question,
                                token_id=token_id,
                                outcome_label=label,
                                outcome_index=idx,
                                balance=balance,
                            )
                        )

        return PortfolioResponse(
            eth_address=eth_address,
            usdc_balance=usdc_balance,
            positions=positions,
        )

    def get_transaction_history(self, api_key: str) -> TransactionHistoryResponse:
        eth_address = get_or_create_eth_address(self._db, api_key)
        with self._db.read() as conn:
            transactions = TableRead.get_transaction_history(conn, api_key)
        return TransactionHistoryResponse(
            eth_address=eth_address,
            transactions=transactions,
        )
