"""In-process Liquidity Engine — one tick rests a pegged, non-crossing book."""
import logging
from decimal import Decimal

from agentpit.config import Settings
from agentpit.datastructures.place_order_request import PlaceOrderRequest
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.liquidity import price_oracle
from agentpit.liquidity.ladder import MICRO, TICK, build_ladder
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
        quoted = 0
        for m in markets:
            bid, ask = price_oracle.fetch_bid_ask_micro(m.polymarket_yes_token_id)
            if bid is None or ask is None or bid >= ask:
                continue
            mid = (bid + ask) // 2
            if not self._moved(m.market_id, mid):
                continue
            try:
                self._quote_market(m, bid, ask)
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

    def _quote_market(self, market, p_bid: int, p_ask: int) -> None:
        yes_token = market.erc1155_tokens[0][0]
        cond = market.condition_id.value
        size_per_side = self._cfg.liquidity_split_per_market_usdc * MICRO
        makers = self._makers_for(market.market_id)
        # Pass 1: ensure inventory + cancel every participating maker's stale quotes.
        for u in makers:
            self._ensure_inventory(u, market)
            self._order.cancel_market_orders(u, market=cond, asset_id=None)
        # Anchors = Polymarket touch, clamped against agentpit's own residual touch
        # so the engine never crosses a real-user order.
        own_bid, own_ask = self._order._best_bid_ask(yes_token)
        bid_anchor, ask_anchor = p_bid, p_ask
        if own_ask is not None:
            bid_anchor = min(bid_anchor, own_ask - TICK)
        if own_bid is not None:
            ask_anchor = max(ask_anchor, own_bid + TICK)
        if bid_anchor >= ask_anchor:
            log.warning("market %s anchors crossed (bid=%s ask=%s) — skipping quote",
                        market.market_id, bid_anchor, ask_anchor)
            return
        # Pass 2: place fresh non-crossing ladders anchored to the executable touch.
        for u in makers:
            rungs = build_ladder(
                bid_anchor, ask_anchor,
                rungs_per_side=self._cfg.liquidity_ladder_rungs_per_side,
                wall_fraction=self._cfg.liquidity_wall_fraction,
                size_per_side_micro=size_per_side,
            )
            for r in rungs:
                payload = PlaceOrderRequest(
                    token_id=yes_token, side=r.side,
                    price=Decimal(r.price_micro) / MICRO,
                    size=Decimal(r.size_micro) / MICRO,
                    order_type="GTC",
                )
                resp = self._order.place_order(u, payload)
                if resp.tradeIDs:
                    log.error("liquidity quote unexpectedly filled (market=%s side=%s price=%s)",
                              market.market_id, r.side, r.price_micro)

    def _ensure_inventory(self, user: User, market) -> None:
        yes_token_int = int(market.erc1155_tokens[0][0])
        target = self._cfg.liquidity_split_per_market_usdc * MICRO
        held = self._onchain.ctf_balance(user.eth_address, yes_token_int)
        if held >= target:
            return
        condition_bytes = bytes.fromhex(market.condition_id.value[2:])
        self._onchain.user_split_position(user.eth_key, condition_bytes, target)
