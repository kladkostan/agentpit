from agentpit.datastructures.book_params import BookParams
from agentpit.datastructures.orderbook_summary import OrderBookLevel, OrderBookSummary


def test_level_fields():
    lvl = OrderBookLevel(price="0.45", size="120")
    assert lvl.model_dump() == {"price": "0.45", "size": "120"}


def test_summary_defaults_and_shape():
    s = OrderBookSummary(
        market="0xcond",
        asset_id="123",
        timestamp="1740000000000",
        hash="abc",
        bids=[OrderBookLevel(price="0.45", size="120")],
        asks=[OrderBookLevel(price="0.55", size="90")],
        last_trade_price="0.46",
    )
    d = s.model_dump()
    assert d["market"] == "0xcond" and d["asset_id"] == "123"
    assert d["tick_size"] == "0.001"
    assert d["neg_risk"] is False
    assert d["min_order_size"] == "0"
    assert d["bids"][0] == {"price": "0.45", "size": "120"}


def test_book_params():
    assert BookParams(token_id="123").token_id == "123"
