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
from agentpit.services.event_service import EventService

log = logging.getLogger(__name__)

_ZERO_BYTES32 = b"\x00" * 32


class MarketService:
    def __init__(self, db: DbSession, onchain: OnchainAdmin):
        self._db = db
        self._onchain = onchain

    def list_markets(self, limit: int, offset: int) -> ListMarketsResponse:
        if limit < 1 or limit > 1000:
            raise InvalidPaginationError("limit must be between 1 and 1000")
        if offset < 0:
            raise InvalidPaginationError("offset must be non-negative")
        with self._db.read() as conn:
            markets, total = TableRead.list_markets(conn, limit=limit, offset=offset)
        return ListMarketsResponse(
            markets=markets, total=total, limit=limit, offset=offset
        )

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
            self._prepare_market_on_chain(payload)

        with self._db.write() as conn:
            market = TableWrite.create_market(
                conn, payload, is_polygon_market=payload.condition_id is not None
            )
        # Enforce the "every market belongs to an event" invariant immediately —
        # without this, locally-created orphan markets would be invisible on
        # the home page until the next process restart (which runs the
        # startup auto-wrap).
        if market.event_id is None:
            EventService(self._db).wrap_market_in_singleton_event_if_needed(
                market.market_id
            )
            with self._db.read() as conn:
                refreshed = TableRead.read_market(conn, market.market_id)
                if refreshed is not None:
                    return refreshed
        return market

    def _prepare_market_on_chain(self, payload: CreateMarketRequest) -> None:
        """Run prepareCondition + registerToken and back-fill payload fields."""
        condition_id, erc1155_tokens = prepare_market_on_chain(
            self._onchain, payload.question, payload.outcome_labels or []
        )
        payload.condition_id = condition_id
        payload.erc1155_tokens = erc1155_tokens

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


def prepare_market_on_chain(
    admin: OnchainAdmin, question: str, outcome_labels: list[str]
) -> tuple[ConditionId, list[tuple[str, str]]]:
    """Prepare a binary market on the local CTF + Exchange.

    Runs `prepareCondition` (idempotent), derives the per-outcome ERC-1155
    token IDs, calls `registerToken`, and verifies via `registry()` that
    both tokens persisted. Returns the locally-derived condition id and
    `[(token_id_str, label), ...]` pairs ready to store on the market row.

    Used by both the local-creation flow ([`MarketService.create_market`])
    and the Polymarket sync mirror flow.
    """
    outcome_count = len(outcome_labels)
    if outcome_count != 2:
        raise MarketStateError(
            "exchange.registerToken only supports binary (YES/NO) markets"
        )
    question_id = keccak(text=question)
    oracle = admin._client.admin.address  # noqa: SLF001 — intentional
    ctf = admin._contracts.ctf  # noqa: SLF001
    usd_address = admin._contracts.usd.address  # noqa: SLF001
    exch = admin._contracts.exchange  # noqa: SLF001

    condition_id_bytes = ctf.functions.getConditionId(
        Web3.to_checksum_address(oracle), question_id, outcome_count
    ).call()

    existing_slots = ctf.functions.getOutcomeSlotCount(condition_id_bytes).call()
    if existing_slots == 0:
        admin.prepare_condition(oracle, question_id, outcome_count)
    elif existing_slots != outcome_count:
        raise MarketStateError(
            f"condition already prepared with {existing_slots} slots, "
            f"expected {outcome_count}"
        )

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

    try:
        admin.register_token(token_ids[0], token_ids[1], condition_id_bytes)
    except Exception as exc:
        log.info(
            "registerToken raised for %s: %s — verifying registry state",
            condition_id_bytes.hex(),
            exc,
        )

    comp_a, _ = exch.functions.registry(token_ids[0]).call()
    comp_b, _ = exch.functions.registry(token_ids[1]).call()
    if comp_a == 0 or comp_b == 0:
        raise MarketStateError(
            f"registerToken did not persist for condition "
            f"0x{condition_id_bytes.hex()}: "
            f"registry[{token_ids[0]}].complement={comp_a}, "
            f"registry[{token_ids[1]}].complement={comp_b}"
        )

    condition_id_hex = "0x" + condition_id_bytes.hex()
    erc1155_tokens = list(zip((str(t) for t in token_ids), outcome_labels))
    log.info(
        "market prepared on-chain: condition_id=%s tokens=%s",
        condition_id_hex,
        token_ids,
    )
    return ConditionId(condition_id_hex), erc1155_tokens
