"""Conftest for the live on-chain integration suite.

These tests need anvil running on RPC_URL with the agentpit stack deployed
(`./scripts/run_node.sh && ./scripts/deploy_exchange.sh`). They are skipped if
the RPC is not reachable so `pytest -q` stays green in CI.
"""
import os
from pathlib import Path

# Restore real env values (PK, JWT_SECRET, real DB path) that the parent
# conftest may have stubbed out for fast off-chain tests.
os.environ.pop("AGENTPIT_DB_PATH", None)
os.environ.pop("JWT_SECRET", None)

import pytest
from web3 import Web3

from agentpit.config import Settings


def _rpc_reachable() -> bool:
    settings = Settings()
    rpc = settings.rpc_url_override or "http://127.0.0.1:8545"
    try:
        w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 1}))
        return w3.is_connected()
    except Exception:
        return False


_ONCHAIN_OK = _rpc_reachable() and Path("deployments/local.json").exists()


def pytest_collection_modifyitems(config, items):
    if _ONCHAIN_OK:
        return
    skip = pytest.mark.skip(reason="anvil not running or deployments/local.json missing")
    for item in items:
        item.add_marker(skip)
