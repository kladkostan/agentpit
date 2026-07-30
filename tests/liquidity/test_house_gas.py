# tests/liquidity/test_house_gas.py
from agentpit.liquidity.house_accounts import gas_topup_wei

ETH = 10**18
FLOOR = 5 * ETH
TARGET = 100 * ETH


def test_no_topup_while_above_the_floor():
    assert gas_topup_wei(6 * ETH, FLOOR, TARGET) == 0
    assert gas_topup_wei(TARGET, FLOOR, TARGET) == 0


def test_floor_itself_is_not_a_refill():
    assert gas_topup_wei(FLOOR, FLOOR, TARGET) == 0


def test_below_the_floor_refills_to_target():
    assert gas_topup_wei(4 * ETH, FLOOR, TARGET) == 96 * ETH


def test_production_dust_is_refilled():
    # The balance the mirror actually stalled on: starved, but not zero, so the
    # old "refill at exactly zero" rule never fired.
    dust = 11_211_539_964_876
    assert gas_topup_wei(dust, FLOOR, TARGET) == TARGET - dust


def test_zero_floor_disables_topups():
    assert gas_topup_wei(0, 0, TARGET) == 0


def test_never_returns_negative_when_misconfigured():
    # floor above target: a balance under the floor but over the target must
    # not ask for a negative transfer.
    assert gas_topup_wei(50 * ETH, 100 * ETH, 10 * ETH) == 0


# --- the simulated-chain gate -----------------------------------------------
# Re-onboarding on a zero balance repairs an account a disposable chain forgot.
# On a durable chain the same condition means the account spent its gas, and
# re-granting on login would be a faucet anyone could drain on repeat.

class _FakeOnchain:
    def __init__(self):
        self.funded = []

    def native_balance(self, address):
        return 0                      # looks exactly like a chain wipe

    def faucet_drip(self, address, *, timeout=30):
        self.funded.append(("drip", address))

    def fund_gas(self, address, value_wei, *, timeout=30):
        self.funded.append(("gas", address))

    def grant_user_approvals(self, account, *, timeout=30):
        self.funded.append(("approvals", account))


def _provisioner(simulated: bool):
    from agentpit.config import Settings
    from agentpit.liquidity.house_accounts import HouseAccountProvisioner
    onchain = _FakeOnchain()
    settings = Settings(AGENTPIT_SIMULATED_CHAIN=simulated)
    return HouseAccountProvisioner(None, onchain, settings), onchain


class _Key:
    address = "0x" + "11" * 20


class _User:
    user_id = "u1"
    email = "house-bot-0@agentpit.local"
    eth_address = "0x" + "11" * 20
    eth_key = _Key()


def test_zero_balance_reonboards_on_a_simulated_chain():
    prov, onchain = _provisioner(True)
    prov._maybe_reonboard(_User())
    assert onchain.funded, "a wiped chain must be repaired"


def test_zero_balance_does_not_regrant_on_a_durable_chain():
    prov, onchain = _provisioner(False)
    prov._maybe_reonboard(_User())
    assert onchain.funded == [], "login must not mint a fresh gas grant"
