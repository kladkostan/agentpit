"""Regression: the web3 client must handle Polygon's PoA block headers.

Polygon (the forked chain) carries >32-byte `extraData` in its block headers.
web3 v7 raises `ExtraDataLengthError` on such blocks unless
`ExtraDataToPOAMiddleware` is injected. This bites on-chain ops (e.g.
polymarket_sync's tx building) whenever web3 reads a real Polygon block — most
notably the anvil fork-base block, which is `latest` right after a fork/restart
until a local tx mines an anvil block, causing "Synced 0/N, N failed".
"""

from agentpit.config import Settings
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client

# A block well below the anvil fork point (~88M) → a real Polygon header with
# large extraData, served through the fork. Reading it exercises PoA handling.
_HISTORICAL_POLYGON_BLOCK = 80_000_000


def test_web3_client_reads_poa_polygon_block():
    settings = Settings()
    deployment = Deployment.load(settings.deployment_path)
    client = Web3Client(settings, deployment)

    # Without the POA middleware this raises web3.exceptions.ExtraDataLengthError.
    block = client.web3.eth.get_block(_HISTORICAL_POLYGON_BLOCK)
    assert block.number == _HISTORICAL_POLYGON_BLOCK
