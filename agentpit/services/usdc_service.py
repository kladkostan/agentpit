from agentpit.datastructures.get_usdc_balance_response import GetUsdcBalanceResponse
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.onchain.admin import OnchainAdmin


class UsdcService:
    """Read-only on-chain apUSD balance lookups for the current user."""

    def __init__(self, db: DbSession, onchain: OnchainAdmin):
        self._db = db
        self._onchain = onchain

    def get_balance(self, user: User) -> GetUsdcBalanceResponse:
        balance = self._onchain.usd_balance(user.eth_address)
        return GetUsdcBalanceResponse(eth_address=user.eth_address, balance=balance)
