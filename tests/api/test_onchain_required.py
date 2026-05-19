"""Boot must fail loud if the on-chain stack isn't reachable.

The whole product assumes anvil + the deployed exchange exist. Silently
booting in a degraded "catalog only" mode would let users create accounts
and place orders that can never settle.
"""

from pathlib import Path

import pytest

from agentpit.config import Settings


def test_create_app_raises_when_deployment_file_is_missing(tmp_path: Path):
    from agentpit.api.app import create_app

    settings = Settings(deployment_path=tmp_path / "does-not-exist.json")
    with pytest.raises(Exception) as info:
        create_app(settings)
    msg = str(info.value)
    assert "deployment" in msg.lower() or "on-chain" in msg.lower(), msg
