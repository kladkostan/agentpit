import os
from agentpit.config import Settings


def test_liquidity_defaults():
    s = Settings()
    assert s.liquidity_engine_enabled is False
    assert s.liquidity_house_account_count == 100
    assert s.liquidity_wallet_funding_usdc == 1_000_000_000
    assert s.liquidity_split_per_market_usdc == 10_000
    assert s.liquidity_makers_per_market == 16
    assert s.liquidity_ladder_rungs_per_side == 8
    assert abs(s.liquidity_wall_fraction - 0.6) < 1e-9


def test_liquidity_env_override(monkeypatch):
    monkeypatch.setenv("LIQUIDITY_ENGINE", "true")
    monkeypatch.setenv("AGENTPIT_LIQUIDITY_HOUSE_ACCOUNTS", "5")
    s = Settings()
    assert s.liquidity_engine_enabled is True
    assert s.liquidity_house_account_count == 5
