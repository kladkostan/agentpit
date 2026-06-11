from contextlib import contextmanager

import agentpit.api.app as app_mod


class _FakeDb:
    """DbSession stub whose write()/read() both yield a sentinel connection."""

    def write(self):
        @contextmanager
        def _cm():
            yield "CONN"

        return _cm()

    def read(self):
        @contextmanager
        def _cm():
            yield "CONN"

        return _cm()


class _FakeSettings:
    pinned_series = [("btc-updown-5m", 300)]


def test_run_pin_sync_syncs_then_returns_current_window_ids(monkeypatch):
    calls = {"sync": 0, "ids": 0, "sync_conn": None, "ids_conn": None}

    def fake_sync(conn, admin, pinned, now):
        calls["sync"] += 1
        calls["sync_conn"] = conn
        assert pinned == [("btc-updown-5m", 300)]
        assert isinstance(now, int)
        return ["m1", "m2", "m3"]

    def fake_ids(conn, pinned, now):
        calls["ids"] += 1
        calls["ids_conn"] = conn
        return [10, 20]

    monkeypatch.setattr(app_mod, "sync_pinned_series", fake_sync)
    monkeypatch.setattr(app_mod, "current_window_market_ids", fake_ids)

    ids = app_mod._run_pin_sync(
        _FakeDb(), admin="ADMIN", settings=_FakeSettings()  # type: ignore[arg-type]
    )

    # Returns the current-window ids (for the immediate fill), not a count.
    assert ids == [10, 20]
    assert calls["sync"] == 1 and calls["ids"] == 1
    assert calls["sync_conn"] == "CONN"  # sync ran inside db.write()
    assert calls["ids_conn"] == "CONN"  # lookup ran inside db.read()
