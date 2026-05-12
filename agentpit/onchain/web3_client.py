import threading
from functools import lru_cache

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from agentpit.config import Settings
from agentpit.onchain.deployment import Deployment


class Web3Client:
    """Holds the singleton web3 + admin/operator account, and a tx-send lock.

    The lock serializes admin-key sends so we don't pick the same nonce twice
    when concurrent requests both try to use the admin (faucet drip, fund-gas,
    matchOrders). For first cut this is enough; later we can replace it with a
    dispatcher that tracks pending nonces explicitly.
    """

    def __init__(self, settings: Settings, deployment: Deployment):
        rpc_url = settings.rpc_url_override or deployment.rpc_url
        self.web3 = Web3(Web3.HTTPProvider(rpc_url))
        self.deployment = deployment
        self._send_lock = threading.Lock()

        if not settings.operator_private_key:
            raise RuntimeError(
                "PK env var is unset — agentpit requires an admin/operator key"
            )
        self.admin: LocalAccount = Account.from_key(settings.operator_private_key)

        if self.admin.address.lower() != deployment.admin.lower():
            raise RuntimeError(
                f"PK address {self.admin.address} does not match deployment.admin "
                f"{deployment.admin} from {settings.deployment_path}"
            )

    def verify_chain(self) -> None:
        chain_id = self.web3.eth.chain_id
        if chain_id != self.deployment.chain_id:
            raise RuntimeError(
                f"Connected chain_id {chain_id} != deployment chain_id "
                f"{self.deployment.chain_id}"
            )

    @property
    def send_lock(self) -> threading.Lock:
        return self._send_lock


@lru_cache(maxsize=1)
def _shared_client(settings: Settings, deployment: Deployment) -> Web3Client:
    return Web3Client(settings, deployment)


def get_web3_client(settings: Settings, deployment: Deployment) -> Web3Client:
    return _shared_client(settings, deployment)
