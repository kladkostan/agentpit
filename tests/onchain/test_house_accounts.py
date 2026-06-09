from agentpit.config import Settings
from agentpit.liquidity.house_accounts import HouseAccountProvisioner
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.contracts import Contracts
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client
from tests.db_helpers import fresh_test_db


def _provisioner(count=3):
    s = Settings(liquidity_house_account_count=count, liquidity_funding_drips=1)
    d = Deployment.load(s.deployment_path)
    w = Web3Client(s, d)
    admin = OnchainAdmin(w, Contracts(w.web3, d))
    return HouseAccountProvisioner(fresh_test_db(), admin, s), admin, d


def test_provision_creates_and_funds():
    prov, admin, d = _provisioner(count=3)
    users = prov.ensure_provisioned()
    assert len(users) == 3
    for u in users:
        assert u.is_bot is True
        assert u.onboarded_at is not None
        assert admin.usd_balance(u.eth_address) >= d.signup_grant_raw  # >= 1 drip
        assert admin.native_balance(u.eth_address) > 0


def test_provision_is_idempotent():
    prov, _admin, _d = _provisioner(count=3)
    first = prov.ensure_provisioned()
    second = prov.ensure_provisioned()
    assert {u.email for u in first} == {u.email for u in second}
    assert len(second) == 3  # no duplicates created
