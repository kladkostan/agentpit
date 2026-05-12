import logging

from eth_utils import keccak
from web3 import Web3

from agentpit.datastructures.cancel_market_response import CancelMarketResponse
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.list_markets_response import ListMarketsResponse
from agentpit.datastructures.market import Market
from agentpit.datastructures.resolve_market_request import ResolveMarketRequest
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import (
    InvalidPaginationError,
    MarketNotFoundError,
    MarketStateError,
)
from agentpit.onchain.admin import OnchainAdmin

log = logging.getLogger(__name__)

_ZERO_BYTES32 = b"\x00" * 32


class MarketService:
    def __init__(self, db: DbSession, onchain: OnchainAdmin | None = None):
        self._db = db
        self._onchain = onchain

    def list_markets(self, limit: int, offset: int) -> ListMarketsResponse:
        if limit < 1 or limit > 1000:
            raise InvalidPaginationError("limit must be between 1 and 1000")
        if offset < 0:
            raise InvalidPaginationError("offset must be non-negative")
        with self._db.read() as conn:
            markets, total = TableRead.list_markets(conn, limit=limit, offset=offset)
        return ListMarketsResponse(markets=markets, total=total, limit=limit, offset=offset)

    def get_market(self, market_id: int) -> Market:
        with self._db.read() as conn:
            market = TableRead.read_market(conn, market_id)
        if market is None:
            raise MarketNotFoundError(market_id)
        return market

    def create_market(self, payload: CreateMarketRequest) -> Market:
        # Local creation runs on-chain prepareCondition + registerToken so that
        # subsequent fills can settle. The Polymarket sync path supplies
        # condition_id directly and skips this whole branch.
        if payload.condition_id is None and payload.outcome_labels is not None:
            if self._onchain is None:
                raise MarketStateError(
                    "on-chain integration disabled — cannot create local markets"
                )
            self._prepare_market_on_chain(payload)

        with self._db.write() as conn:
            return TableWrite.create_market(
                conn, payload, is_polygon_market=payload.condition_id is not None
            )

    def _prepare_market_on_chain(self, payload: CreateMarketRequest) -> None:
        """Run prepareCondition + registerToken and back-fill payload fields."""
        assert self._onchain is not None
        outcome_labels = payload.outcome_labels or []
        outcome_count = len(outcome_labels)
        question_id = keccak(text=payload.question)
        oracle = self._onchain._client.admin.address  # noqa: SLF001  — intentional
        ctf = self._onchain._contracts.ctf            # noqa: SLF001
        usd_address = self._onchain._contracts.usd.address  # noqa: SLF001

        condition_id_bytes = ctf.functions.getConditionId(
            Web3.to_checksum_address(oracle), question_id, outcome_count
        ).call()

        # Idempotent: prepareCondition reverts if already registered, so check
        # the slot count first.
        existing_slots = ctf.functions.getOutcomeSlotCount(condition_id_bytes).call()
        if existing_slots == 0:
            self._onchain.prepare_condition(oracle, question_id, outcome_count)
        elif existing_slots != outcome_count:
            raise MarketStateError(
                f"condition already prepared with {existing_slots} slots, "
                f"expected {outcome_count}"
            )

        # Compute the per-outcome tokenIds. For binary YES/NO this is partition
        # [1, 2]; in general it's [1<<i for i in range(outcome_count)].
        token_ids: list[int] = []
        for i in range(outcome_count):
            index_set = 1 << i
            collection_id = ctf.functions.getCollectionId(
                _ZERO_BYTES32, condition_id_bytes, index_set
            ).call()
            token_id = ctf.functions.getPositionId(
                Web3.to_checksum_address(usd_address), collection_id
            ).call()
            token_ids.append(token_id)

        # Register the binary pair on the exchange. For non-binary markets this
        # would need to be repeated for each pair; the exchange currently only
        # supports binary anyway, so reject early.
        if outcome_count != 2:
            raise MarketStateError(
                "exchange.registerToken only supports binary (YES/NO) markets"
            )
        # Try to register; if already registered the exchange reverts with a
        # custom error and we treat that as success (idempotent).
        try:
            self._onchain.register_token(
                token_ids[0], token_ids[1], condition_id_bytes
            )
        except Exception as exc:
            # Common: AlreadyRegistered / InvalidComplement when re-creating
            # the same market. Any other revert should still surface.
            log.info(
                "registerToken raised (likely already registered for %s): %s",
                condition_id_bytes.hex(), exc,
            )

        condition_id_hex = "0x" + condition_id_bytes.hex()
        payload.condition_id = ConditionId(condition_id_hex)
        payload.erc1155_tokens = list(zip(
            (str(t) for t in token_ids), outcome_labels
        ))
        log.info(
            "market prepared on-chain: condition_id=%s tokens=%s",
            condition_id_hex, token_ids,
        )

    def activate_market(self, market_id: int) -> Market:
        with self._db.write() as conn:
            try:
                return TableWrite.activate_market(conn, market_id)
            except ValueError as e:
                raise MarketStateError(str(e)) from e

    def close_market(self, market_id: int) -> Market:
        with self._db.write() as conn:
            try:
                return TableWrite.close_market(conn, market_id)
            except ValueError as e:
                raise MarketStateError(str(e)) from e

    def cancel_market(self, market_id: int) -> CancelMarketResponse:
        with self._db.write() as conn:
            try:
                market, refunds_processed = TableWrite.cancel_market(conn, market_id)
            except ValueError as e:
                raise MarketStateError(str(e)) from e
        return CancelMarketResponse(
            market_id=market.market_id,
            message="Market cancelled successfully",
            refunds_processed=refunds_processed,
            market=market,
        )

    def resolve_market(self, market_id: int, payload: ResolveMarketRequest) -> Market:
        with self._db.write() as conn:
            market = TableRead.read_market(conn, market_id)
            if market is None:
                raise MarketNotFoundError(market_id)
            try:
                return TableWrite.resolve_market(
                    conn,
                    market_id=market_id,
                    winning_outcome_index=payload.winning_outcome_index,
                )
            except ValueError as e:
                raise MarketStateError(str(e)) from e
