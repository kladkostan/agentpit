from agentpit.liquidity import price_oracle


def test_mid_to_micro():
    got = price_oracle.fetch_mid_micro("TID", getter=lambda url: {"mid": "0.55"})
    assert got == 550_000


def test_bad_payload_returns_none():
    assert price_oracle.fetch_mid_micro("TID", getter=lambda url: {}) is None
    assert price_oracle.fetch_mid_micro("TID", getter=lambda url: {"mid": "x"}) is None


def test_fetch_error_isolated():
    def boom(url):
        raise RuntimeError("clob down")
    assert price_oracle.fetch_mid_micro("TID", getter=boom) is None


def test_uses_yes_token_id_in_url():
    seen = {}
    def getter(url):
        seen["url"] = url
        return {"mid": "0.42"}
    price_oracle.fetch_mid_micro("YESTOKEN", getter=getter)
    assert "token_id=YESTOKEN" in seen["url"]


def test_bid_ask_from_book():
    book = {"bids": [{"price": "0.50", "size": "1"}, {"price": "0.54", "size": "1"}],
            "asks": [{"price": "0.58", "size": "1"}, {"price": "0.56", "size": "1"}]}
    bid, ask = price_oracle.fetch_bid_ask_micro("TID", getter=lambda url: book)
    assert bid == 540_000   # max of bids
    assert ask == 560_000   # min of asks


def test_bid_ask_one_sided_book():
    book = {"bids": [{"price": "0.40", "size": "1"}], "asks": []}
    bid, ask = price_oracle.fetch_bid_ask_micro("TID", getter=lambda url: book)
    assert bid == 400_000
    assert ask is None


def test_bid_ask_fetch_error_isolated():
    def boom(url):
        raise RuntimeError("clob down")
    assert price_oracle.fetch_bid_ask_micro("TID", getter=boom) == (None, None)


def test_bid_ask_uses_book_url():
    seen = {}
    def getter(url):
        seen["url"] = url
        return {"bids": [], "asks": []}
    price_oracle.fetch_bid_ask_micro("YESTOKEN", getter=getter)
    assert "/book?token_id=YESTOKEN" in seen["url"]
