import agentpit.polymarket.polymarket_sync as sync


def test_fetch_uses_volume_order_and_caps(monkeypatch):
    seen = {"urls": []}

    def fake_get(url):
        seen["urls"].append(url)
        # One full page then stop. Each market clears any floor (high volume).
        return [
            {
                "conditionId": f"0x{i:064x}",
                "question": f"Q{i}",
                "volumeNum": 10_000_000,
                "liquidity": 10_000_000,
                "active": True,
                "closed": False,
                "archived": False,
                "clobTokenIds": '["1","2"]',
                "outcomes": '["Yes","No"]',
            }
            for i in range(5)
        ]

    monkeypatch.setattr(sync, "get", fake_get)

    out = sync.fetch_all_polymarket_markets(
        order="volume_24hr", max_markets=3, liquidity_threshold=0
    )

    assert len(out) == 3  # capped to max_markets
    url = seen["urls"][0]
    assert "order=volume_24hr" in url
    assert "ascending=false" in url
    assert "active=true" in url
    assert "closed=false" in url


def test_pagination_collects_across_capped_pages(monkeypatch):
    """Gamma caps each response at ~100 rows regardless of the requested
    `limit`. The fetch must paginate by the actual page size (advancing offset
    and stopping on an empty page), not break after one page on `len < limit`.
    """
    import urllib.parse as up

    universe = [
        {
            "conditionId": f"0x{i:064x}",
            "question": f"Q{i}",
            "volumeNum": 5_000_000,
            "active": True,
            "closed": False,
            "archived": False,
            "clobTokenIds": '["1","2"]',
            "outcomes": '["Yes","No"]',
        }
        for i in range(350)
    ]

    offsets = []

    def fake_get(url):
        offset = int(up.parse_qs(up.urlparse(url).query).get("offset", ["0"])[0])
        offsets.append(offset)
        return universe[offset : offset + 100]  # Gamma's hard 100-row cap

    monkeypatch.setattr(sync, "get", fake_get)

    out = sync.fetch_all_polymarket_markets(
        order="volume_24hr", max_markets=250, liquidity_threshold=0
    )

    assert len(out) == 250  # paginated across 100-row pages, not stuck at ~100
    assert offsets[:3] == [0, 100, 200]  # advanced by actual page size
