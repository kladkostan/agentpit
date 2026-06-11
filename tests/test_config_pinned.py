from agentpit.config import Settings


def _settings(monkeypatch, **env):
    for k in (
        "SYNC", "PINNED_SERIES", "PIN_SYNC_ENABLED", "PIN_SYNC_OFFSET_SECONDS",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_pin_defaults(monkeypatch):
    s = _settings(monkeypatch)
    assert s.pin_sync_offset_seconds == 10
    assert s.pinned_series == [("btc-updown-5m", 300)]
    # pin_sync_enabled follows SYNC (False by default here).
    assert s.pin_sync_enabled is False


def test_pin_enabled_follows_sync(monkeypatch):
    s = _settings(monkeypatch, SYNC="true")
    assert s.pin_sync_enabled is True


def test_pin_enabled_explicit_override(monkeypatch):
    s = _settings(monkeypatch, SYNC="true", PIN_SYNC_ENABLED="false")
    assert s.pin_sync_enabled is False


def test_pinned_series_parsed_from_env(monkeypatch):
    s = _settings(monkeypatch, PINNED_SERIES="btc-updown-5m:300,eth-updown-5m:900")
    assert s.pinned_series == [("btc-updown-5m", 300), ("eth-updown-5m", 900)]


def test_pinned_series_empty_when_blank(monkeypatch):
    s = _settings(monkeypatch, PINNED_SERIES="")
    assert s.pinned_series == []
