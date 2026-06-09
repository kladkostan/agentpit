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
