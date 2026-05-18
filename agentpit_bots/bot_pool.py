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
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from agentpit_bots.client import BotCredentials

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


_BOT_PASSWORD = "bot-default-pw-32-chars-min-length"   # >= 8 chars; never exposed


class BotPool:
    def __init__(
        self,
        *,
        client,
        creds_path: str,
        anchor_pool_size: int,
        noise_pool_size: int,
        inventory_split_shares: int = 500,
    ):
        self._client = client
        self._creds_path = Path(creds_path)
        self._anchor_pool_size = anchor_pool_size
        self._noise_pool_size = noise_pool_size
        self._inventory_split_shares = inventory_split_shares

    def ensure_provisioned(
        self, *, market_ids_for_inventory: Iterable[int]
    ) -> list[Bot]:
        existing = self._load_existing()
        existing_by_name = {b["name"]: b for b in existing}

        want: list[tuple[str, BotRole]] = [
            (f"anchor-{i}", BotRole.ANCHOR) for i in range(self._anchor_pool_size)
        ] + [
            (f"noise-{i}", BotRole.NOISE) for i in range(self._noise_pool_size)
        ]

        bots: list[Bot] = []
        new_entries: list[dict] = list(existing)
        for name, role in want:
            if name in existing_by_name:
                e = existing_by_name[name]
                bots.append(Bot(
                    name=name, role=BotRole(e["role"]),
                    creds=BotCredentials(token=e["token"], eth_address=e["eth_address"]),
                ))
                continue
            email = _make_email(name)
            creds = self._client.register(email=email, password=_BOT_PASSWORD)
            self._client.mark_bot(eth_address=creds.eth_address)
            bots.append(Bot(name=name, role=role, creds=creds))
            new_entries.append({
                "name": name, "role": role.value,
                "token": creds.token, "eth_address": creds.eth_address,
                "email": email,
            })
            log.info("registered_bot name=%s role=%s eth=%s",
                     name, role.value, creds.eth_address)

        self._save(new_entries)

        # Inventory split for anchor bots.
        market_ids = list(market_ids_for_inventory)
        for bot in bots:
            if bot.role != BotRole.ANCHOR:
                continue
            for market_id in market_ids:
                try:
                    self._client.split_position(
                        token=bot.creds.token, market_id=market_id,
                        amount=self._inventory_split_shares,
                    )
                except Exception as exc:
                    log.warning(
                        "split_position_failed bot=%s market_id=%s err=%s",
                        bot.name, market_id, exc,
                    )
        return bots

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
