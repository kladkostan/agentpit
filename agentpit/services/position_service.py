from agentpit.datastructures.market_state import MarketState
from agentpit.datastructures.position_response import PositionResponse
from agentpit.datastructures.redeem_position_response import RedeemPositionResponse
from agentpit.datastructures.split_position_request import (
    MergePositionRequest,
    SplitPositionRequest,
)
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.domain.exceptions import (
    InsufficientBalanceError,
    MarketNotFoundError,
    MarketStateError,
)
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.user_wallet import send_user_tx
from agentpit.utils.parse import hex2bytes

_ZERO_BYTES32 = b"\x00" * 32


class PositionService:
    """User-signed split / merge / redeem against the on-chain CTF contract."""

    def __init__(self, db: DbSession, onchain: OnchainAdmin | None):
        self._db = db
        self._onchain = onchain

    def split(
        self, user: User, market_id: int, payload: SplitPositionRequest
    ) -> PositionResponse:
        market = self._require_market(market_id)
        if self._onchain is None:
            raise MarketStateError("on-chain integration disabled")
        condition_id = hex2bytes(market.condition_id.value)
        bal = self._onchain.usd_balance(user.eth_address)
        if bal < payload.amount:
            raise InsufficientBalanceError(f"need {payload.amount}, have {bal}")
        self._onchain.user_split_position(user.eth_key, condition_id, payload.amount)
        return self._snapshot(user, market, locked=payload.amount)

    def merge(
        self, user: User, market_id: int, payload: MergePositionRequest
    ) -> PositionResponse:
        market = self._require_market(market_id)
        if self._onchain is None:
            raise MarketStateError("on-chain integration disabled")
        condition_id = hex2bytes(market.condition_id.value)
        for token_id, _label in market.erc1155_tokens:
            bal = self._onchain.ctf_balance(user.eth_address, int(token_id))
            if bal < payload.amount:
                raise InsufficientBalanceError(
                    f"need {payload.amount} of token {token_id}, have {bal}"
                )
        usd_address = self._onchain._contracts.usd.address  # noqa: SLF001
        partition = [1 << i for i in range(len(market.erc1155_tokens))]
        fn = self._onchain._contracts.ctf.functions.mergePositions(
            usd_address, _ZERO_BYTES32, condition_id, partition, payload.amount
        )
        send_user_tx(self._onchain._client, user.eth_key, fn)  # noqa: SLF001
        return self._snapshot(user, market, unlocked=payload.amount)

    def redeem(self, user: User, market_id: int) -> RedeemPositionResponse:
        market = self._require_market(market_id)
        if market.market_state != MarketState.RESOLVED:
            raise MarketStateError("market not resolved yet")
        if self._onchain is None:
            raise MarketStateError("on-chain integration disabled")
        condition_id = hex2bytes(market.condition_id.value)
        usd_address = self._onchain._contracts.usd.address  # noqa: SLF001
        partition = [1 << i for i in range(len(market.erc1155_tokens))]
        fn = self._onchain._contracts.ctf.functions.redeemPositions(
            usd_address, _ZERO_BYTES32, condition_id, partition
        )
        pre_balance = self._onchain.usd_balance(user.eth_address)
        send_user_tx(self._onchain._client, user.eth_key, fn)  # noqa: SLF001
        new_balance = self._onchain.usd_balance(user.eth_address)
        return RedeemPositionResponse(
            market_id=market.market_id,
            collateral_amount=new_balance - pre_balance,
            new_usdc_balance=new_balance,
        )

    # --- helpers --------------------------------------------------------

    def _require_market(self, market_id: int):
        with self._db.read() as conn:
            market = TableRead.read_market(conn, market_id)
        if market is None:
            raise MarketNotFoundError(market_id)
        if market.condition_id is None:
            raise MarketStateError("market has no on-chain condition_id")
        return market

    def _snapshot(self, user: User, market, *, locked: int = 0, unlocked: int = 0):
        assert self._onchain is not None
        balances = {}
        for token_id, _label in market.erc1155_tokens:
            balances[token_id] = self._onchain.ctf_balance(
                user.eth_address, int(token_id)
            )
        return PositionResponse(
            market_id=market.market_id,
            amount=locked or unlocked,
            collateral_amount=locked,
            token_balances=balances,
        )
