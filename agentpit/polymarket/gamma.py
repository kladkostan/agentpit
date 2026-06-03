"""Serialize agentpit Market/Event domain objects into Gamma wire models.

Price/volume fields emit neutral placeholders here; spec Phase 3/4 wires real
book/trade-derived values (bestBid/bestAsk/lastTradePrice/spread/outcomePrices/
volume/liquidity).
"""

import json
from datetime import datetime, timezone

from agentpit.datastructures.event import Event
from agentpit.datastructures.gamma_market import GammaEvent, GammaMarket
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState

_CLOSED_STATES = (MarketState.CLOSED, MarketState.RESOLVED, MarketState.CANCELLED)


def _iso(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _json_arr(items: list[str]) -> str:
    """Compact JSON array string (no spaces), matching Gamma's encoding."""
    return json.dumps(items, separators=(",", ":"))


def to_gamma_market(market: Market) -> GammaMarket:
    labels = [label for _token_id, label in market.erc1155_tokens]
    token_ids = [token_id for token_id, _label in market.erc1155_tokens]
    active = market.market_state == MarketState.ACTIVE
    closed = market.market_state in _CLOSED_STATES
    end_iso = _iso(market.end_date)
    return GammaMarket(
        id=str(market.market_id),
        conditionId=market.condition_id.value,
        question=market.question,
        slug=market.slug,
        description=market.description,
        outcomes=_json_arr(labels),
        outcomePrices=_json_arr(["0.5" for _ in labels]),
        clobTokenIds=_json_arr(token_ids),
        active=active,
        closed=closed,
        acceptingOrders=active,
        startDate=_iso(market.start_date),
        endDate=end_iso,
        endDateIso=end_iso,
        icon=market.icon_url,
        image=market.icon_url,
        volume="0",
        liquidity="0",
        bestBid=0.0,
        bestAsk=0.0,
        lastTradePrice=0.0,
        spread=0.0,
    )


def to_gamma_event(event: Event, markets: list[Market]) -> GammaEvent:
    return GammaEvent(
        id=str(event.event_id),
        slug=event.slug,
        title=event.title,
        description=event.description,
        icon=event.icon_url,
        category=event.category,
        startDate=_iso(event.start_date),
        endDate=_iso(event.end_date),
        markets=[to_gamma_market(m) for m in markets],
    )
