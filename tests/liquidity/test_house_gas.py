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
