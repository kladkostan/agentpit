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
from agentpit.liquidity.replica import MICRO, BookReplica, to_micro
from agentpit.onchain.admin import OnchainAdmin
from agentpit.services.order_service import OrderService

log = logging.getLogger(__name__)


def _ref_of(m) -> "MarketRef | None":
    """Build a MarketRef from a Market, or None if it can't be mirrored (no
    upstream token, or not binary)."""
    if m is None or not m.polymarket_yes_token_id or len(m.erc1155_tokens) < 2:
        return None
    return MarketRef(
        market_id=m.market_id,
        condition_id=m.condition_id.value,
        yes_token=m.erc1155_tokens[0][0],
        no_token=m.erc1155_tokens[1][0],
        pm_yes_token=m.polymarket_yes_token_id,
    )


def _load_refs(
    db: DbSession,
    excluded_categories: "list[str] | None" = None,
    excluded_tags: "list[str] | None" = None,
) -> list[MarketRef]:
    with db.read() as conn:
        markets = TableRead.list_active_synced_markets(
            conn,
            excluded_categories=excluded_categories,
            excluded_tags=excluded_tags,
        )
    return [r for r in (_ref_of(m) for m in markets) if r is not None]


def cold_seed(priority: float, interval: float, now: float) -> float:
    """Initial `last_cold` for an asset, placed in the queue by priority.

    Without an offset every market is due for its first cold sweep the moment
    the process starts, and a boot would place the whole deep book for every
    market at once. So the first sweeps are spread across one interval — but
    WHERE in that interval a market lands is a decision, and it used to be a
    hash of the asset id, which is to say a coin toss.

    `priority` is 1.0 for the market that should deepen first and 0.0 for the
    one that can wait a full interval; the mirror derives it from 24h volume,
    so the books a person is most likely to open fill in first. The offset is
    a fraction of the interval rather than `% int(interval)`, so this is
    well-defined for any positive interval — including sub-second ones, where
    the integer modulo raised `ZeroDivisionError`, and ones in `[1, 2)`, where
    it collapsed to a constant 0 and defeated the stagger.
    """
    if interval <= 0:
        return now
    return now - max(0.0, min(1.0, priority)) * interval


def cold_due(last_cold: float, interval: float, now: float) -> bool:
    """Are this market's deep levels due for a sweep? `interval <= 0` disables
    the cold tier entirely, so every pass stays hot."""
    return interval > 0 and now - last_cold >= interval


class MirrorEngine:
    def __init__(self, db: DbSession, onchain: OnchainAdmin,
                 settings: Settings, user: User):
        self._db = db
        self._onchain = onchain
        self._cfg = settings
        self._user = user
        self._order = OrderService(db, onchain)
        self.state = MirrorState([])
        # asset -> [0,1] priority for its FIRST cold sweep; rebuilt whenever
        # the target set is reloaded, so a market that climbs the volume
        # ranking moves up the queue the next time it is seeded.
        self._cold_priority: "dict[str, float]" = {}
        self._resubscribe = asyncio.Event()
        self._pending_cancel: list[MarketRef] = []

    # ---- feed side -------------------------------------------------------

    async def run_feed(self) -> None:
        while True:
            try:
                assets = list(self.state.replicas)
                self._resubscribe.clear()
                if not assets:
                    await self._wait_resubscribe(self._cfg.mirror_target_refresh_seconds)
                    continue
                await self._seed_books(assets)
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
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mirror feed cycle failed — retrying")
                await asyncio.sleep(2.0)

    async def _seed_books(self, assets: list[str]) -> None:
        """REST-seed book snapshots for `assets` into the shared feed state,
        marking each fresh book dirty for the reconciler. Used for the initial
        seed on every (re)subscribe."""
        if not assets:
            return
        books = await asyncio.to_thread(feed.fetch_books_rest, assets)
        for b in books:
            self.state.handle_event({**b, "event_type": "book"})

    async def fill_markets(self, market_ids: list[int]) -> int:
        """Immediately seed + reconcile the given markets (off-thread), so a
        freshly-synced market is liquid at once instead of waiting for the
        discovery loop to reach it.

        Couples market sync to the liquidity fill — what makes fast-rotating
        windows (live for only ~5 min) tradeable the moment they sync. Runs
        entirely in one worker thread (DB read, REST book fetch, order
        placement), so the event loop / API stay responsive. Self-contained:
        builds its own replicas/snapshots and does not touch the live feed
        state, which independently maintains the markets thereafter. Returns the
        number of orders placed.
        """
        if not market_ids:
            return 0

        def _work() -> int:
            with self._db.read() as conn:
                refs = [
                    ref
                    for ref in (
                        _ref_of(TableRead.read_market(conn, mid))
                        for mid in market_ids
                    )
                    if ref is not None
                ]
            if not refs:
                return 0
            by_asset = {
                b.get("asset_id"): b
                for b in feed.fetch_books_rest([r.pm_yes_token for r in refs])
            }
            placed = 0
            for ref in refs:
                book = by_asset.get(ref.pm_yes_token)
                if book is None:
                    continue  # upstream window not (yet) tradeable — nothing to mirror
                rep = BookReplica(ref.pm_yes_token)
                rep.apply_book({**book, "event_type": "book"})
                snap = rep.snapshot()
                if snap is None:
                    continue
                stats = reconcile_market(
                    self._db, self._order, self._onchain, self._user, ref, snap,
                    self._cfg)
                placed += stats["placed"]
                if stats["placed"] or stats["cancelled"]:
                    log.info("fill market %s: %s", ref.market_id, stats)
            return placed

        return await asyncio.to_thread(_work)

    async def _wait_resubscribe(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._resubscribe.wait(), timeout)
        except TimeoutError:
            pass

    # ---- reconcile side --------------------------------------------------

    async def run_reconciler(self) -> None:
        last_run: dict[str, float] = {}
        last_cold: dict[str, float] = {}
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
                    interval = self._cfg.mirror_cold_interval_seconds
                    if asset not in last_cold:
                        last_cold[asset] = cold_seed(
                            # Unknown asset (seen by the feed before the next
                            # target reload) goes to the back rather than the
                            # front: a market nobody ranked is not urgent.
                            self._cold_priority.get(asset, 0.0), interval, now
                        )
                    cold = cold_due(last_cold[asset], interval, now)
                    if cold:
                        last_cold[asset] = now
                    last_run[asset] = now
                    stats = await asyncio.to_thread(
                        reconcile_market, self._db, self._order, self._onchain,
                        self._user, ref, snap, self._cfg, cold=cold)
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
        refs = await asyncio.to_thread(
            _load_refs, self._db, self._cfg.excluded_categories,
            self._cfg.excluded_tags,
        )
        # `_load_refs` returns them busiest first, and that order is the whole
        # point: it becomes each market's place in the cold-sweep queue.
        n = max(1, len(refs))
        self._cold_priority = {
            r.pm_yes_token: 1.0 - i / n for i, r in enumerate(refs)
        }
        added, removed = self.state.set_targets(refs)
        # An excluded market leaves the target set exactly as a resolved one
        # does, so `removed` carries it into the cancel pass below and the
        # orders it already has are withdrawn — the catalogue and the book stop
        # showing it in the same pass.
        if added or removed:
            # Signal BEFORE any fallible work — a lost signal would leave new
            # markets unsubscribed until the next unrelated target change.
            self._resubscribe.set()
        self._pending_cancel.extend(removed)
        if not self._pending_cancel:
            return
        still_pending: list[MarketRef] = []
        for ref in self._pending_cancel:
            try:
                await asyncio.to_thread(
                    self._order.cancel_market_orders, self._user,
                    ref.condition_id, None)
                log.info("market %s left the active set — mirror orders cancelled",
                         ref.market_id)
            except Exception:
                log.exception("cancel for removed market %s failed — will retry",
                              ref.market_id)
                still_pending.append(ref)
        self._pending_cancel = still_pending

    async def _drain_tape(self) -> None:
        if not self._cfg.mirror_tape_enabled:
            self.state.trades.clear()
            return
        for _ in range(200):
            if not self.state.trades:
                break
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
                    or side not in ("BUY", "SELL") or ts_s <= 0 \
                    or not (0 < price < MICRO):
                continue
            def _write(ref=ref, price=price, size=size, side=side, ts_s=ts_s):
                with self._db.write() as conn:
                    tape.insert_mirrored_trade(
                        conn, condition_id=ref.condition_id,
                        local_token_id=ref.yes_token, price_micro=price,
                        size_micro=size, side=side, match_time_s=ts_s)
            try:
                await asyncio.to_thread(_write)
            except Exception:
                log.exception("mirror tape write failed (market=%s) — dropping event",
                              ref.market_id)
