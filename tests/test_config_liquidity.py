from agentpit.config import Settings


def test_liquidity_defaults():
    s = Settings()
    assert s.liquidity_engine_enabled is False
    assert s.liquidity_house_account_count == 1
    assert s.liquidity_funding_drips == 1
    assert s.mirror_assets_per_connection == 200
    assert abs(s.mirror_reconcile_min_interval_seconds - 0.5) < 1e-9
    assert abs(s.mirror_watchdog_seconds - 120.0) < 1e-9
    assert abs(s.mirror_inventory_buffer - 1.2) < 1e-9
    assert s.mirror_max_settlements_per_cycle == 1
    assert s.mirror_tape_enabled is True
    assert abs(s.mirror_target_refresh_seconds - 15.0) < 1e-9
    assert s.mirror_book_depth == 8


def test_liquidity_env_override(monkeypatch):
    monkeypatch.setenv("LIQUIDITY_ENGINE", "true")
    monkeypatch.setenv("AGENTPIT_LIQUIDITY_HOUSE_ACCOUNTS", "5")
    s = Settings()
    assert s.liquidity_engine_enabled is True
    assert s.liquidity_house_account_count == 5
