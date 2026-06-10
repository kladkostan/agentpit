"""Regression: the web3 client must install the PoA extraData middleware.

Real Polygon block headers carry >32-byte `extraData`; without
`ExtraDataToPOAMiddleware` web3 v7 raises `ExtraDataLengthError` when the
polymarket-sync path reads a real Polygon block. The local node is no longer a
Polygon fork, so we assert the middleware is installed on our Web3Client
directly rather than by fetching a historical Polygon block.
"""

from web3.middleware import ExtraDataToPOAMiddleware

from agentpit.config import Settings
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client


def test_web3_client_installs_poa_middleware():
    settings = Settings()
    deployment = Deployment.load(settings.deployment_path)
    client = Web3Client(settings, deployment)

    # Without the inject() call in Web3Client.__init__ this is False, and reading
    # any real Polygon block would raise web3.exceptions.ExtraDataLengthError.
    assert ExtraDataToPOAMiddleware in client.web3.middleware_onion
