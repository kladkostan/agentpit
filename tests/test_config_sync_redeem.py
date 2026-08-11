from agentpit.config import Settings


def _settings(monkeypatch, **env):
    for k in (
        "SYNC", "SYNC_MAX_MARKETS", "SYNC_LIQUIDITY_MIN",
        "RESOLUTION_MIRROR_ENABLED", "RESOLUTION_MIRROR_INTERVAL_SECONDS",
        "AUTO_REDEEM_ENABLED", "AGENTPIT_SYNC_EXCLUDE_CHURN_SERIES",
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


def test_churn_exclusion_is_on_by_default_and_reversible(monkeypatch):
    """The daily-temperature + sports-prop series are 89% of new creations, so
    the default is to drop them; the flag is there to switch it back without a
    code change."""
    assert _settings(monkeypatch).sync_exclude_churn_series is True
    off = _settings(monkeypatch, AGENTPIT_SYNC_EXCLUDE_CHURN_SERIES="false")
    assert off.sync_exclude_churn_series is False


def test_resolution_mirror_defaults_to_sync(monkeypatch):
    s = _settings(monkeypatch, SYNC="true")
    assert s.sync_enabled is True
    assert s.resolution_mirror_enabled is True


def test_resolution_mirror_explicit_override(monkeypatch):
    s = _settings(monkeypatch, SYNC="true", RESOLUTION_MIRROR_ENABLED="false")
    assert s.resolution_mirror_enabled is False
