"""In-process Liquidity Engine — one tick rests a pegged, non-crossing book."""
import logging
from decimal import Decimal

from agentpit.config import Settings
from agentpit.datastructures.place_order_request import PlaceOrderRequest
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.liquidity import price_oracle
from agentpit.liquidity.ladder import MICRO, build_ladder
from agentpit.onchain.admin import OnchainAdmin
from agentpit.services.order_service import OrderService

log = logging.getLogger(__name__)


class LiquidityEngine:
    def __init__(
        self, db: DbSession, onchain: OnchainAdmin, settings: Settings,
        house_users: list[User],
    ):
        self._db = db
        self._onchain = onchain
        self._cfg = settings
        self._house = house_users
        self._order = OrderService(db, onchain)
        self._last_mid: dict[int, int] = {}

    def tick(self) -> dict:
        with self._db.read() as conn:
            markets = TableRead.list_active_synced_markets(conn)
        mids = price_oracle.fetch_mids_for_markets(markets)
        quoted = 0
        for m in markets:
            mid = mids.get(m.market_id)
            if mid is None or not self._moved(m.market_id, mid):
                continue
            try:
                self._quote_market(m, mid)
                self._last_mid[m.market_id] = mid
                quoted += 1
            except Exception:
                log.exception("quoting market %s failed", m.market_id)
        return {"markets": len(markets), "quoted": quoted}

    def _moved(self, market_id: int, mid: int) -> bool:
        prev = self._last_mid.get(market_id)
        return prev is None or abs(mid - prev) >= self._cfg.liquidity_requote_threshold_micro

    def _makers_for(self, market_id: int) -> list[User]:
        if not self._house:
            return []
        n = min(self._cfg.liquidity_makers_per_market, len(self._house))
        start = (market_id * n) % len(self._house)
        rotated = self._house[start:] + self._house[:start]
        return rotated[:n]

    def _quote_market(self, market, mid: int) -> None:
        yes_token = market.erc1155_tokens[0][0]
        cond = market.condition_id.value
        size_per_side = self._cfg.liquidity_split_per_market_usdc * MICRO
        makers = self._makers_for(market.market_id)
        # Pass 1: ensure inventory + cancel EVERY participating maker's stale
        # quotes BEFORE placing any fresh ones, so a fresh maker cannot cross a
        # not-yet-requoted maker's stale order when the mid has moved.
        for u in makers:
            self._ensure_inventory(u, market)
            self._order.cancel_market_orders(u, market=cond, asset_id=None)
        # Gap from agentpit's own touch (only non-engine orders remain now) so
        # the engine never acts as a taker against a real resting order either.
        best_bid, best_ask = self._order._best_bid_ask(yes_token)
        # Pass 2: place fresh, non-crossing ladders, all pegged to the same mid.
        for u in makers:
            rungs = build_ladder(
                mid,
                rungs_per_side=self._cfg.liquidity_ladder_rungs_per_side,
                wall_fraction=self._cfg.liquidity_wall_fraction,
                size_per_side_micro=size_per_side,
                best_bid_micro=best_bid,
                best_ask_micro=best_ask,
            )
            for r in rungs:
                payload = PlaceOrderRequest(
                    token_id=yes_token,
                    side=r.side,
                    price=Decimal(r.price_micro) / MICRO,
                    size=Decimal(r.size_micro) / MICRO,
                    order_type="GTC",
                )
                resp = self._order.place_order(u, payload)
                if resp.tradeIDs:
                    log.error(
                        "liquidity quote unexpectedly filled (market=%s side=%s price=%s)",
                        market.market_id, r.side, r.price_micro,
                    )

    def _ensure_inventory(self, user: User, market) -> None:
        yes_token_int = int(market.erc1155_tokens[0][0])
        target = self._cfg.liquidity_split_per_market_usdc * MICRO
        held = self._onchain.ctf_balance(user.eth_address, yes_token_int)
        if held >= target:
            return
        condition_bytes = bytes.fromhex(market.condition_id.value[2:])
        self._onchain.user_split_position(user.eth_key, condition_bytes, target)
