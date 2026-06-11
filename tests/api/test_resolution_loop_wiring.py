import agentpit.api.app as app_mod


def test_run_resolution_cycle_resolves_then_redeems(monkeypatch):
    calls = {"mirror": 0, "redeem": 0, "now": None}

    class FakeSettings:
        auto_redeem_enabled = True

    class FakeDb:
        def write(self):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                yield "CONN"

            return _cm()

    def fake_mirror(conn, admin, *, now):
        calls["mirror"] += 1
        calls["now"] = now
        assert conn == "CONN"
        return 2

    def fake_redeem(db, admin):
        calls["redeem"] += 1
        return 3

    monkeypatch.setattr(app_mod, "mirror_polymarket_resolutions", fake_mirror)
    monkeypatch.setattr(app_mod, "auto_redeem_resolved_markets", fake_redeem)

    resolved, redeemed = app_mod._run_resolution_cycle(
        FakeDb(), admin="ADMIN", settings=FakeSettings()  # type: ignore[arg-type]
    )

    assert (resolved, redeemed) == (2, 3)
    assert calls["mirror"] == 1 and calls["redeem"] == 1
    assert isinstance(calls["now"], int)


def test_run_resolution_cycle_skips_redeem_when_disabled(monkeypatch):
    class FakeSettings:
        auto_redeem_enabled = False

    class FakeDb:
        def write(self):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                yield "CONN"

            return _cm()

    monkeypatch.setattr(
        app_mod, "mirror_polymarket_resolutions", lambda conn, admin, *, now: 1
    )
    called = {"redeem": False}

    def fake_redeem(db, admin):
        called["redeem"] = True
        return 0

    monkeypatch.setattr(app_mod, "auto_redeem_resolved_markets", fake_redeem)

    resolved, redeemed = app_mod._run_resolution_cycle(
        FakeDb(), admin="ADMIN", settings=FakeSettings()  # type: ignore[arg-type]
    )
    assert (resolved, redeemed) == (1, 0)
    assert called["redeem"] is False
