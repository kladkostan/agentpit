"""Shared fixtures for bot unit tests.

Bot unit tests are pure — no DB, no network. They use the fakes here.
The integration test in tests/bots/test_runner.py is the only one that
spins up FastAPI/Anvil.
"""
import pytest


@pytest.fixture
def bot_config():
    from agentpit_bots.config import BotConfig
    return BotConfig(tick_interval_sec=1, noise_tick_base_sec=1)
