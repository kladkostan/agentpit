import agentpit.api.app as app_mod


def test_run_pin_sync_calls_sync_inside_write(monkeypatch):
    calls = {"n": 0, "conn": None, "pinned": None, "now": None}

    class FakeSettings:
        pinned_series = [("btc-updown-5m", 300)]

    class FakeDb:
        def write(self):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                yield "CONN"

            return _cm()

    def fake_sync(conn, admin, pinned, now):
        calls["n"] += 1
        calls["conn"] = conn
        calls["pinned"] = pinned
        calls["now"] = now
        return ["m1", "m2", "m3"]

    monkeypatch.setattr(app_mod, "sync_pinned_series", fake_sync)

    count = app_mod._run_pin_sync(
        FakeDb(), admin="ADMIN", settings=FakeSettings()  # type: ignore[arg-type]
    )

    assert count == 3
    assert calls["n"] == 1
    assert calls["conn"] == "CONN"
    assert calls["pinned"] == [("btc-updown-5m", 300)]
    assert isinstance(calls["now"], int)
