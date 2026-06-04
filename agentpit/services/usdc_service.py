from agentpit.datastructures.balance_allowance import BalanceAllowanceResponse
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.domain.exceptions import MarketStateError
from agentpit.onchain.admin import OnchainAdmin


class UsdcService:
    """Read-only on-chain balance lookups for the current user."""

    def __init__(self, db: DbSession, onchain: OnchainAdmin):
        self._db = db
        self._onchain = onchain

    def get_balance_allowance(
        self, user: User, asset_type: str, token_id: str | None
    ) -> BalanceAllowanceResponse:
        if asset_type == "CONDITIONAL":
            if not token_id:
                raise MarketStateError("token_id required for CONDITIONAL")
            bal = self._onchain.ctf_balance(user.eth_address, int(token_id))
        else:  # COLLATERAL
            bal = self._onchain.usd_balance(user.eth_address)
        return BalanceAllowanceResponse(balance=str(bal))
