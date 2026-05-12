from agentpit.datastructures.portfolio_response import PortfolioResponse, Position
from agentpit.datastructures.transaction_history_response import TransactionHistoryResponse
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.onchain.admin import OnchainAdmin


class PortfolioService:
    """Reads on-chain balances and joins them with the local markets table."""

    def __init__(self, db: DbSession, onchain: OnchainAdmin | None):
        self._db = db
        self._onchain = onchain

    def get_portfolio(self, user: User) -> PortfolioResponse:
        usdc_balance = 0
        positions: list[Position] = []
        with self._db.read() as conn:
            all_markets, _ = TableRead.list_markets(conn, limit=10000)

        if self._onchain is not None:
            usdc_balance = self._onchain.usd_balance(user.eth_address)
            for market in all_markets:
                for idx, (token_id, label) in enumerate(market.erc1155_tokens):
                    bal = self._onchain.ctf_balance(user.eth_address, int(token_id))
                    if bal <= 0:
                        continue
                    positions.append(
                        Position(
                            market_id=market.market_id,
                            question=market.question,
                            token_id=token_id,
                            outcome_label=label,
                            outcome_index=idx,
                            balance=bal,
                        )
                    )
        return PortfolioResponse(
            eth_address=user.eth_address,
            usdc_balance=usdc_balance,
            positions=positions,
        )

    def get_transaction_history(self, user: User) -> TransactionHistoryResponse:
        with self._db.read() as conn:
            transactions = TableRead.get_transaction_history(conn, user.api_key)
        return TransactionHistoryResponse(
            eth_address=user.eth_address,
            transactions=transactions,
        )
