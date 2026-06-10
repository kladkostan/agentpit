# agentpit/liquidity/mirror.py
"""MirrorEngine — glue between the WSS feed, the reconciler, and the tape.

Two lifespan tasks (siblings of polymarket_sync / snapshot):
  run_feed       — REST-seeds replicas, then holds sharded WSS connections.
  run_reconciler — drains dirty markets (coalesced per-market) and the trade
                   queue; refreshes the target market set; cancels orders on
                   the ACTIVE→gone edge (resolution/cancellation).
Blocking work (DB/chain/REST) runs via asyncio.to_thread.
"""
import asyncio
import logging

from agentpit.config import Settings
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.liquidity import feed, tape
from agentpit.liquidity.feed import MarketRef, MirrorState
from agentpit.liquidity.reconciler import reconcile_market
from agentpit.liquidity.replica import to_micro
from agentpit.onchain.admin import OnchainAdmin
from agentpit.services.order_service import OrderService

log = logging.getLogger(__name__)


def _load_refs(db: DbSession) -> list[MarketRef]:
    with db.read() as conn:
        markets = TableRead.list_active_synced_markets(conn)
    refs = []
    for m in markets:
        if not m.polymarket_yes_token_id or len(m.erc1155_tokens) < 2:
            continue
        refs.append(MarketRef(
            market_id=m.market_id,
            condition_id=m.condition_id.value,
            yes_token=m.erc1155_tokens[0][0],
            no_token=m.erc1155_tokens[1][0],
            pm_yes_token=m.polymarket_yes_token_id,
        ))
    return refs


class MirrorEngine:
    def __init__(self, db: DbSession, onchain: OnchainAdmin,
                 settings: Settings, user: User):
        self._db = db
        self._onchain = onchain
        self._cfg = settings
        self._user = user
        self._order = OrderService(db, onchain)
        self.state = MirrorState([])
        self._resubscribe = asyncio.Event()

    # ---- feed side -------------------------------------------------------

    async def run_feed(self) -> None:
        while True:
            assets = list(self.state.replicas)
            self._resubscribe.clear()
            if not assets:
                await self._wait_resubscribe(self._cfg.mirror_target_refresh_seconds)
                continue
            books = await asyncio.to_thread(feed.fetch_books_rest, assets)
            for b in books:
                self.state.handle_event({**b, "event_type": "book"})
            conns = [
                asyncio.create_task(feed.run_connection(
                    self.state, shard_assets,
                    watchdog_seconds=self._cfg.mirror_watchdog_seconds))
                for shard_assets in feed.shard(
                    assets, self._cfg.mirror_assets_per_connection)
            ]
            try:
                await self._resubscribe.wait()   # target set changed — rebuild
            finally:
                for t in conns:
                    t.cancel()
                for t in conns:
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass

    async def _wait_resubscribe(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._resubscribe.wait(), timeout)
        except TimeoutError:
            pass

    # ---- reconcile side --------------------------------------------------

    async def run_reconciler(self) -> None:
        last_run: dict[str, float] = {}
        last_refresh = 0.0
        while True:
            try:
                now = asyncio.get_running_loop().time()
                if now - last_refresh >= self._cfg.mirror_target_refresh_seconds:
                    last_refresh = now
                    await self._refresh_targets()
                await self._drain_tape()
                ready = [
                    a for a in list(self.state.dirty)
                    if now - last_run.get(a, 0.0)
                    >= self._cfg.mirror_reconcile_min_interval_seconds
                ]
                for asset in ready:
                    self.state.dirty.discard(asset)
                    ref = self.state.by_asset.get(asset)
                    rep = self.state.replicas.get(asset)
                    snap = rep.snapshot() if rep is not None else None
                    if ref is None or snap is None:
                        continue
                    last_run[asset] = now
                    stats = await asyncio.to_thread(
                        reconcile_market, self._db, self._order, self._onchain,
                        self._user, ref, snap, self._cfg)
                    if stats["deferred"] or stats["failed"]:
                        # Incomplete cycle — converge on a later pass even if
                        # no new upstream event arrives.
                        self.state.dirty.add(asset)
                    if stats["placed"] or stats["cancelled"]:
                        log.info("mirror market %s: %s", ref.market_id, stats)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mirror reconcile cycle failed")
            await asyncio.sleep(
                self._cfg.mirror_reconcile_min_interval_seconds
                if self.state.dirty or self.state.trades
                else self._cfg.liquidity_interval_seconds)

    async def _refresh_targets(self) -> None:
        refs = await asyncio.to_thread(_load_refs, self._db)
        added, removed = self.state.set_targets(refs)
        for ref in removed:    # resolution/cancel edge: pull our orders
            log.info("market %s left the active set — cancelling mirror orders",
                     ref.market_id)
            await asyncio.to_thread(
                self._order.cancel_market_orders, self._user,
                ref.condition_id, None)
        if added or removed:
            self._resubscribe.set()

    async def _drain_tape(self) -> None:
        if not self._cfg.mirror_tape_enabled:
            self.state.trades.clear()
            return
        while self.state.trades:
            ev = self.state.trades.popleft()
            ref = self.state.by_asset.get(ev.get("asset_id"))
            price = to_micro(ev.get("price"))
            size = to_micro(ev.get("size"))
            side = ev.get("side")
            try:
                ts_s = int(ev.get("timestamp", "0")) // 1000   # WSS gives ms
            except (TypeError, ValueError):
                ts_s = 0
            if ref is None or price is None or size is None or size <= 0 \
                    or side not in ("BUY", "SELL") or ts_s <= 0:
                continue
            def _write(ref=ref, price=price, size=size, side=side, ts_s=ts_s):
                with self._db.write() as conn:
                    tape.insert_mirrored_trade(
                        conn, condition_id=ref.condition_id,
                        local_token_id=ref.yes_token, price_micro=price,
                        size_micro=size, side=side, match_time_s=ts_s)
            await asyncio.to_thread(_write)
