from agentpit.config import Settings


def _settings(monkeypatch, **env):
    for k in (
        "SYNC", "SYNC_MAX_MARKETS", "SYNC_LIQUIDITY_MIN",
        "RESOLUTION_MIRROR_ENABLED", "RESOLUTION_MIRROR_INTERVAL_SECONDS",
        "AUTO_REDEEM_ENABLED",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_new_knobs_defaults(monkeypatch):
    s = _settings(monkeypatch)
    assert s.sync_max_markets == 300
    assert s.sync_liquidity_min == 0.0
    assert s.resolution_mirror_interval_seconds == 300
    assert s.auto_redeem_enabled is True
    # resolution_mirror_enabled defaults to sync_enabled (False here)
    assert s.resolution_mirror_enabled is False


def test_resolution_mirror_defaults_to_sync(monkeypatch):
    s = _settings(monkeypatch, SYNC="true")
    assert s.sync_enabled is True
    assert s.resolution_mirror_enabled is True


def test_resolution_mirror_explicit_override(monkeypatch):
    s = _settings(monkeypatch, SYNC="true", RESOLUTION_MIRROR_ENABLED="false")
    assert s.resolution_mirror_enabled is False
