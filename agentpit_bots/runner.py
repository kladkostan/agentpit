"""Bot runner: ticks the anchor and noise loops.

Run as: ``python -m agentpit_bots.runner --base http://localhost:8000``

The runner is decomposed so unit tests can call ``run_anchor_tick`` and
``run_noise_tick`` directly without spinning up the time-based loop.
"""
from __future__ import annotations

import argparse
import logging
import random
import time
from dataclasses import dataclass

from agentpit_bots.bot_pool import Bot, BotPool, BotRole
from agentpit_bots.client import AgentpitClient
from agentpit_bots.config import BotConfig, DEFAULT, PRICE_SCALE, SHARES_SCALE
from agentpit_bots.price_oracle import PriceOracle
from agentpit_bots.reconcile import DesiredOrder, LiveOrder, reconcile
from agentpit_bots.strategies.anchor_mm import AnchorMarketMaker
from agentpit_bots.strategies.base import MarketTokens
from agentpit_bots.strategies.noise_trader import NoiseTrader

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _MarketView:
    market_id: int
    yes_local: str
    no_local: str
    yes_outcome_label: str   # e.g. "Yes" — needed for /orders body
    no_outcome_label: str
    poly_yes_token_id: str | None
    poly_no_token_id: str | None


class Runner:
    def __init__(
        self,
        *,
        client,
        oracle,
        cfg: BotConfig,
        bots: list[Bot],
        rng: random.Random | None = None,
    ):
        self._client = client
        self._oracle = oracle
        self._cfg = cfg
        self._bots = bots
        self._rng = rng or random.Random()
        self._anchor_strat = AnchorMarketMaker(cfg)
        self._noise_strat = NoiseTrader(cfg, rng=self._rng)

    # --- public tick entry points --------------------------------------

    def run_anchor_tick(self) -> None:
        markets = self._discover_markets(require_upstream_tokens=True)
        if not markets:
            return
        self._refresh_oracle(markets)
        for bot in self._bots:
            if bot.role != BotRole.ANCHOR:
                continue
            self._anchor_tick_for_bot(bot, markets)

    def run_noise_tick(self) -> None:
        markets = self._discover_markets(require_upstream_tokens=True)
        if not markets:
            return
        self._refresh_oracle(markets)
        for bot in self._bots:
            if bot.role != BotRole.NOISE:
                continue
            market = self._rng.choice(markets)
            self._noise_tick_for_bot(bot, market)

    def run_rebalance_tick(self) -> None:
        """For each ANCHOR bot × market: merge surplus, split if depleted."""
        markets = self._discover_markets(require_upstream_tokens=True)
        if not markets:
            return
        market_by_id = {m.market_id: m for m in markets}
        for bot in self._bots:
            if bot.role != BotRole.ANCHOR:
                continue
            try:
                portfolio = self._client.get_portfolio(token=bot.creds.token)
            except Exception as exc:
                log.warning("portfolio_failed bot=%s err=%s", bot.name, exc)
                continue
            by_market: dict[int, dict[str, int]] = {}
            for pos in portfolio.get("positions", []):
                mid = int(pos.get("market_id", 0))
                if mid not in market_by_id:
                    continue
                tok = str(pos.get("token_id"))
                bal_shares = int(pos.get("balance", 0)) // SHARES_SCALE
                by_market.setdefault(mid, {})[tok] = bal_shares
            splits = merges = 0
            for mid, market in market_by_id.items():
                yes_bal = by_market.get(mid, {}).get(market.yes_local, 0)
                no_bal = by_market.get(mid, {}).get(market.no_local, 0)
                min_bal = min(yes_bal, no_bal)
                if min_bal < self._cfg.mm_quote_size_shares:
                    amount = self._cfg.mm_quote_size_shares
                    try:
                        self._client.split_position(
                            token=bot.creds.token, market_id=mid,
                            amount=amount * SHARES_SCALE,
                        )
                        splits += 1
                        log.info(
                            "rebalance_split bot=%s market=%s shares=%s "
                            "yes_bal=%s no_bal=%s reason=depleted",
                            bot.name, mid, amount, yes_bal, no_bal,
                        )
                    except Exception as exc:
                        log.warning(
                            "split_failed bot=%s market=%s err=%s",
                            bot.name, mid, exc,
                        )
                    continue
                surplus = min_bal - self._cfg.mm_rebalance_floor_shares
                if surplus > 0:
                    try:
                        self._client.merge_positions(
                            token=bot.creds.token, market_id=mid,
                            amount=surplus * SHARES_SCALE,
                        )
                        merges += 1
                        log.info(
                            "rebalance_merge bot=%s market=%s shares=%s "
                            "yes_bal=%s no_bal=%s floor=%s",
                            bot.name, mid, surplus, yes_bal, no_bal,
                            self._cfg.mm_rebalance_floor_shares,
                        )
                    except Exception as exc:
                        log.warning(
                            "merge_failed bot=%s market=%s err=%s",
                            bot.name, mid, exc,
                        )
            log.info(
                "rebalance_summary bot=%s splits=%s merges=%s onchain_txs=%s",
                bot.name, splits, merges, splits + merges,
            )

    def log_drift(self) -> None:
        """Log local vs polymarket mid for every enabled market.

        Local mid = average of best bid + best ask from /orderbook. Skipped
        when one side is empty.
        """
        markets = self._discover_markets(require_upstream_tokens=True)
        if not markets:
            return
        self._refresh_oracle(markets)
        for m in markets:
            poly_mid = self._oracle.midpoint(m.poly_yes_token_id) if m.poly_yes_token_id else None
            if poly_mid is None:
                continue
            try:
                book = self._client.get_orderbook(
                    market_id=m.market_id, outcome=m.yes_outcome_label,
                )
            except Exception:
                continue
            bids = book.get("bids") or []
            asks = book.get("asks") or []
            n_bids, n_asks = len(bids), len(asks)
            if not bids or not asks:
                log.info(
                    "drift market_id=%s local_mid=none poly_mid=%.4f "
                    "bids=%s asks=%s",
                    m.market_id, poly_mid, n_bids, n_asks,
                )
                continue
            local_mid = (int(bids[0]["PRICE"]) + int(asks[0]["PRICE"])) / 2 / PRICE_SCALE
            log.info(
                "drift market_id=%s local_mid=%.4f poly_mid=%.4f drift_cents=%+.2f "
                "bids=%s asks=%s",
                m.market_id, local_mid, poly_mid, (local_mid - poly_mid) * 100,
                n_bids, n_asks,
            )

    # --- per-bot loops -------------------------------------------------

    def _anchor_tick_for_bot(self, bot: Bot, markets: list[_MarketView]) -> None:
        live_orders = self._fetch_live_orders(bot)
        total_cancels = total_creates = quoted_markets = skipped_markets = 0
        for m in markets:
            mid = self._oracle.midpoint(m.poly_yes_token_id) if m.poly_yes_token_id else None
            if mid is None:
                log.info("oracle_stale market_id=%s", m.market_id)
                skipped_markets += 1
                continue
            desired = self._anchor_strat.compute_desired_orders(
                market=MarketTokens(
                    market_id=m.market_id,
                    yes_token_id=m.yes_local,
                    no_token_id=m.no_local,
                ),
                poly_yes_mid=mid,
            )
            if not desired:
                # Self-cross guard kicked in (mid too close to 0 or 1).
                skipped_markets += 1
                continue
            quoted_markets += 1
            live_for_market = [
                lo for lo in live_orders
                if lo.token_id in (m.yes_local, m.no_local)
            ]
            cancels, creates = reconcile(live_for_market, desired)
            total_cancels += len(cancels)
            total_creates += len(creates)
            for cid in cancels:
                self._safe_cancel(bot, cid)
            for create in creates:
                self._safe_place(bot, create, m)
        log.info(
            "anchor_summary bot=%s quoted=%s skipped=%s cancels=%s creates=%s",
            bot.name, quoted_markets, skipped_markets, total_cancels, total_creates,
        )

    def _noise_tick_for_bot(self, bot: Bot, market: _MarketView) -> None:
        mid = self._oracle.midpoint(market.poly_yes_token_id) if market.poly_yes_token_id else None
        if mid is None:
            return
        try:
            portfolio = self._client.get_portfolio(
                token=bot.creds.token, market_id=market.market_id,
            )
        except Exception as exc:
            log.warning("portfolio_failed bot=%s err=%s", bot.name, exc)
            return
        balances: dict[str, int] = {}
        for pos in portfolio.get("positions", []):
            balances[str(pos.get("token_id"))] = int(pos.get("balance", 0))
        desired = self._noise_strat.compute_desired_orders(
            market=MarketTokens(
                market_id=market.market_id,
                yes_token_id=market.yes_local,
                no_token_id=market.no_local,
            ),
            poly_yes_mid=mid,
            token_balances=balances,
        )
        if not desired:
            log.info(
                "noise_skip bot=%s market=%s reason=no_orders mid=%.4f",
                bot.name, market.market_id, mid,
            )
            return
        for d in desired:
            # Distance from this outcome's anchor mid in cents.
            anchor_mid = mid if d.token_id == market.yes_local else 1.0 - mid
            price = d.price_int / PRICE_SCALE
            dist_cents = abs(price - anchor_mid) * 100
            log.info(
                "noise_order bot=%s market=%s side=%s outcome=%s price=%.4f "
                "dist_cents=%.2f size_shares=%s",
                bot.name, market.market_id, d.side,
                "Yes" if d.token_id == market.yes_local else "No",
                price, dist_cents, d.size // SHARES_SCALE,
            )
            self._safe_place(bot, d, market)

    # --- helpers --------------------------------------------------------

    def _discover_markets(self, *, require_upstream_tokens: bool) -> list[_MarketView]:
        raw = self._client.get_markets()
        out: list[_MarketView] = []
        for m in raw:
            if m.get("market_state") != "ACTIVE":
                continue
            if int(m["market_id"]) in self._cfg.disabled_market_ids:
                continue
            tokens = m.get("erc1155_tokens") or []
            if len(tokens) != 2:
                continue
            yes_local = no_local = None
            yes_label = no_label = None
            for tok_id, label in tokens:
                if str(label).lower() == "yes":
                    yes_local = str(tok_id); yes_label = str(label)
                elif str(label).lower() == "no":
                    no_local = str(tok_id); no_label = str(label)
            if not (yes_local and no_local and yes_label and no_label):
                continue
            poly_yes = m.get("polymarket_yes_token_id")
            poly_no = m.get("polymarket_no_token_id")
            if require_upstream_tokens and not (poly_yes and poly_no):
                continue
            out.append(_MarketView(
                market_id=int(m["market_id"]),
                yes_local=yes_local, no_local=no_local,
                yes_outcome_label=yes_label, no_outcome_label=no_label,
                poly_yes_token_id=poly_yes, poly_no_token_id=poly_no,
            ))
        return out

    def _refresh_oracle(self, markets: list[_MarketView]) -> None:
        token_ids = [m.poly_yes_token_id for m in markets if m.poly_yes_token_id]
        self._oracle.refresh(token_ids)

    def _fetch_live_orders(self, bot: Bot) -> list[LiveOrder]:
        try:
            raw = self._client.list_my_orders(token=bot.creds.token)
        except Exception as exc:
            log.warning("list_my_orders_failed bot=%s err=%s", bot.name, exc)
            return []
        result: list[LiveOrder] = []
        for r in raw:
            try:
                result.append(LiveOrder(
                    order_id=r["ORDER_ID"], side=r["SIDE"],
                    token_id=str(r["TOKEN_ID"]),
                    price_int=int(r["PRICE"]),
                    remaining_amount=int(r["REMAINING_AMOUNT"]),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def _safe_place(self, bot: Bot, d: DesiredOrder, market: _MarketView) -> None:
        # token_id → outcome label so we can send "Yes"/"No" to /orders
        if d.token_id == market.yes_local:
            outcome = market.yes_outcome_label
        elif d.token_id == market.no_local:
            outcome = market.no_outcome_label
        else:
            log.warning("unknown_token_id token=%s market=%s", d.token_id, market.market_id)
            return
        price_str = f"{d.price_int / PRICE_SCALE:.2f}"
        try:
            self._client.place_order(
                token=bot.creds.token,
                market_id=market.market_id,
                outcome=outcome, side=d.side,
                price=price_str, size=d.size,
            )
        except Exception as exc:
            log.warning(
                "place_failed bot=%s market=%s side=%s outcome=%s err=%s",
                bot.name, market.market_id, d.side, outcome, exc,
            )

    def _safe_cancel(self, bot: Bot, order_id: str) -> None:
        try:
            self._client.cancel_order(token=bot.creds.token, order_id=order_id)
        except Exception as exc:
            log.warning("cancel_failed bot=%s order=%s err=%s", bot.name, order_id, exc)


# --- entry point --------------------------------------------------------

def _build_runner(cfg: BotConfig) -> tuple[Runner, BotPool, list[int]]:
    import requests
    from py_clob_client.client import ClobClient

    session = requests.Session()
    ap_client = AgentpitClient(
        base_url=cfg.base_url, session=session, admin_token=cfg.admin_token,
    )
    clob = ClobClient(host=cfg.polymarket_clob_host)
    oracle = PriceOracle(clob=clob)

    pool = BotPool(
        client=ap_client, creds_path=cfg.creds_path,
        anchor_pool_size=cfg.anchor_pool_size,
        noise_pool_size=cfg.noise_pool_size,
        inventory_split_shares=cfg.inventory_split_shares,
        noise_inventory_split_shares=cfg.noise_inventory_split_shares,
    )
    markets = [m for m in ap_client.get_markets()
               if m.get("market_state") == "ACTIVE"
               and m.get("polymarket_yes_token_id")
               and m.get("polymarket_no_token_id")]
    market_ids = [int(m["market_id"]) for m in markets]
    bots = pool.ensure_provisioned(market_ids_for_inventory=market_ids)
    return Runner(client=ap_client, oracle=oracle, cfg=cfg, bots=bots), pool, market_ids


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT.base_url)
    ap.add_argument("--tick", type=int, default=DEFAULT.tick_interval_sec)
    args = ap.parse_args()

    cfg = BotConfig(base_url=args.base, tick_interval_sec=args.tick)
    runner, _pool, _market_ids = _build_runner(cfg)

    log.info("bot_runner_starting tick_sec=%s", cfg.tick_interval_sec)
    tick_index = 0
    last_noise = 0.0
    try:
        while True:
            try:
                runner.run_anchor_tick()
                if tick_index % max(1, 60 // cfg.tick_interval_sec) == 0:
                    runner.log_drift()
                now = time.time()
                if now - last_noise >= cfg.noise_tick_base_sec:
                    runner.run_noise_tick()
                    last_noise = now
                if tick_index % cfg.mm_rebalance_every_ticks == 0:
                    runner.run_rebalance_tick()
                tick_index += 1
            except Exception:
                log.exception("tick_failed")
            time.sleep(cfg.tick_interval_sec)
    except KeyboardInterrupt:
        log.info("bot_runner_stopping (ctrl-c)")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
