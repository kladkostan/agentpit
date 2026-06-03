import json

from agentpit.datastructures.event import Event
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState
from agentpit.polymarket.gamma import to_gamma_market, to_gamma_event


def _market(state=MarketState.ACTIVE) -> Market:
    return Market(
        question="Will it rain?",
        slug="will-it-rain",
        market_id=7,
        condition_id=ConditionId("0x" + "ab" * 32),
        description="desc",
        erc1155_tokens=[("111", "Yes"), ("222", "No")],
        start_date=1_700_000_000,
        end_date=1_800_000_000,
        market_state=state,
        resolved_outcome=0 if state == MarketState.RESOLVED else None,
    )


def test_to_gamma_market_shape_and_encoding():
    g = to_gamma_market(_market())
    assert g.id == "7"
    assert g.conditionId == "0x" + "ab" * 32
    assert g.question == "Will it rain?"
    # JSON-encoded string arrays (Gamma's quirk), compact (no spaces)
    assert g.outcomes == '["Yes","No"]'
    assert g.clobTokenIds == '["111","222"]'
    assert json.loads(g.outcomes) == ["Yes", "No"]
    assert g.active is True
    assert g.closed is False
    assert g.acceptingOrders is True
    assert g.endDateIso == g.endDate  # endDateIso mirrors endDate
    assert g.endDateIso.endswith("Z")  # ISO8601 UTC
    assert g.volume == "0"
    assert g.bestBid == 0.0


def test_to_gamma_market_closed_states():
    for state in (MarketState.CLOSED, MarketState.RESOLVED, MarketState.CANCELLED):
        g = to_gamma_market(_market(state))
        assert g.active is False
        assert g.closed is True
        assert g.acceptingOrders is False


def test_to_gamma_event_nests_markets():
    g = to_gamma_event(
        Event(event_id=3, slug="weather", title="Weather", description="d"),
        [_market()],
    )
    assert g.id == "3"
    assert g.slug == "weather"
    assert len(g.markets) == 1
    assert g.markets[0].conditionId == "0x" + "ab" * 32
