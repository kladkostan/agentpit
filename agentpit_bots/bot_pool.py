"""BotPool — registers, persists, and provisions bot identities.

Roles:
- ANCHOR: one or a few bots that run AnchorMarketMaker. Need inventory
  per market (split a complete set so they can post SELL orders).
- NOISE: bots that run NoiseTrader. No per-market inventory — they
  acquire via MINT matches as they trade.

Bot identities are persisted in ``creds_path`` (JSON list). On startup
the pool reads existing entries and only registers what's missing.
"""

from __future__ import annotations

import enum
import json
import logging
import secrets
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from agentpit_bots.client import BotCredentials
from agentpit_bots.config import SHARES_SCALE

log = logging.getLogger(__name__)


class BotRole(str, enum.Enum):
    ANCHOR = "ANCHOR"
    NOISE = "NOISE"


@dataclass
class Bot:
    name: str
    role: BotRole
    creds: BotCredentials


def _make_email(name: str) -> str:
    # Random suffix prevents collision with any user that registered manually.
    return f"bot-{name}-{secrets.token_hex(4)}@agentpit.internal"


_BOT_PASSWORD = "bot-default-pw-32-chars-min-length"  # >= 8 chars; never exposed


class BotPool:
    def __init__(
        self,
        *,
        client,
        creds_path: str,
        anchor_pool_size: int,
        noise_pool_size: int,
        inventory_split_shares: int = 500,
        noise_inventory_split_shares: int = 100,
        provision_concurrency: int = 4,
    ):
        self._client = client
        self._creds_path = Path(creds_path)
        self._anchor_pool_size = anchor_pool_size
        self._noise_pool_size = noise_pool_size
        self._inventory_split_shares = inventory_split_shares
        self._noise_inventory_split_shares = noise_inventory_split_shares
        self._provision_concurrency = max(1, provision_concurrency)

    def ensure_provisioned(
        self, *, market_ids_for_inventory: Iterable[int]
    ) -> list[Bot]:
        existing = self._load_existing()
        existing_by_name = {b["name"]: b for b in existing}

        want: list[tuple[str, BotRole]] = [
            (f"anchor-{i}", BotRole.ANCHOR) for i in range(self._anchor_pool_size)
        ] + [(f"noise-{i}", BotRole.NOISE) for i in range(self._noise_pool_size)]

        bots: list[Bot] = []
        new_entries: list[dict] = list(existing)
        for name, role in want:
            if name in existing_by_name:
                e = existing_by_name[name]
                bots.append(
                    Bot(
                        name=name,
                        role=BotRole(e["role"]),
                        creds=BotCredentials(
                            token=e["token"], eth_address=e["eth_address"]
                        ),
                    )
                )
                continue
            email = _make_email(name)
            creds = self._client.register(email=email, password=_BOT_PASSWORD)
            self._client.mark_bot(eth_address=creds.eth_address)
            bots.append(Bot(name=name, role=role, creds=creds))
            new_entries.append(
                {
                    "name": name,
                    "role": role.value,
                    "token": creds.token,
                    "eth_address": creds.eth_address,
                    "email": email,
                }
            )
            log.info(
                "registered_bot name=%s role=%s eth=%s",
                name,
                role.value,
                creds.eth_address,
            )

        self._save(new_entries)

        self._provision_inventory(bots, list(market_ids_for_inventory))
        return bots

    # --- inventory provisioning ----------------------------------------

    def _inventory_shares(self, bot: Bot) -> int:
        """Target complete-set size (display shares) this bot's role wants in
        every market. 0 means the role opts out of the bootstrap split.

        - anchor needs a deep float to quote both sides of every market
        - noise needs a small float so its SELL picks can fire — without it,
          noise BUYs rest forever (never cross the anchor's SELL) and the ask
          side of every market shows only the anchor's one quote.
        """
        if bot.role == BotRole.ANCHOR:
            return self._inventory_split_shares
        if bot.role == BotRole.NOISE:
            return self._noise_inventory_split_shares
        return 0

    def _provision_inventory(self, bots: list[Bot], market_ids: list[int]) -> None:
        """Bring every bot up to its target complete set in each market.

        Provisions up to ``provision_concurrency`` bots at a time: each
        on-chain account has its own nonce stream, so bots are safe to run
        concurrently, while markets within a bot stay sequential to avoid
        nonce collisions. The fan-out is capped because every split is an
        on-chain tx and the dev API is a single worker — a thread per bot (30+)
        buries it in concurrent on-chain calls and the client times out.
        Markets a bot already holds at/above target are skipped, so a restart
        with funded bots does ~no on-chain work.
        """
        if not market_ids:
            return
        funding = [
            (bot, shares) for bot in bots if (shares := self._inventory_shares(bot)) > 0
        ]
        if not funding:
            return
        workers = min(self._provision_concurrency, len(funding))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(self._provision_bot, bot, shares, market_ids)
                for bot, shares in funding
            ]
            for future in as_completed(futures):
                future.result()  # surface unexpected (non-split) errors

    def _provision_bot(self, bot: Bot, shares: int, market_ids: list[int]) -> None:
        funded = self._funded_market_ids(bot, min_shares=shares)
        for market_id in market_ids:
            if market_id in funded:
                continue
            try:
                self._client.split_position(
                    token=bot.creds.token,
                    market_id=market_id,
                    amount=shares * SHARES_SCALE,
                )
            except Exception as exc:
                log.warning(
                    "split_position_failed bot=%s market_id=%s err=%s",
                    bot.name,
                    market_id,
                    exc,
                )

    def _funded_market_ids(self, bot: Bot, *, min_shares: int) -> set[int]:
        """Markets where `bot` already holds a complete set at/above target.

        A market counts only if both outcome tokens are present and the
        smaller balance meets the target — a depleted side means the bot must
        be topped up. On a portfolio read failure we provision everything
        (return empty), preferring redundant work over a starved book.
        """
        try:
            portfolio = self._client.get_portfolio(token=bot.creds.token)
        except Exception as exc:
            log.warning(
                "portfolio_failed bot=%s err=%s — provisioning all markets",
                bot.name,
                exc,
            )
            return set()
        balances_by_market: dict[int, list[int]] = {}
        for pos in portfolio.get("positions", []):
            mid = int(pos.get("market_id", 0))
            bal_shares = int(pos.get("balance", 0)) // SHARES_SCALE
            balances_by_market.setdefault(mid, []).append(bal_shares)
        return {
            mid
            for mid, bals in balances_by_market.items()
            if len(bals) >= 2 and min(bals) >= min_shares
        }

    def _load_existing(self) -> list[dict]:
        if not self._creds_path.exists():
            return []
        try:
            return json.loads(self._creds_path.read_text())
        except (ValueError, OSError) as exc:
            log.warning("creds_load_failed path=%s err=%s", self._creds_path, exc)
            return []

    def _save(self, entries: list[dict]) -> None:
        self._creds_path.parent.mkdir(parents=True, exist_ok=True)
        self._creds_path.write_text(json.dumps(entries, indent=2))
