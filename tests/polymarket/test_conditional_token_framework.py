import pytest
from unittest.mock import MagicMock, patch
from web3 import Web3
from agentpit.polymarket.conditional_token_framework import ConditionalTokenFramework, CTF_ADDRESS, CTF_ABI

class TestConditionalTokenFramework:

    @pytest.fixture
    def mock_web3(self):
        web3 = MagicMock()
        return web3

    @pytest.fixture
    def mock_contract(self, mock_web3):
        contract = MagicMock()
        mock_web3.eth.contract.return_value = contract
        return contract

    def test_get_onchain_resolution_status_invalid_condition_id(self, mock_web3):
        # Invalid condition ID (not hex)
        result = ConditionalTokenFramework.get_onchain_resolution_status("invalid_id", web3=mock_web3)
        assert result is None

        # Invalid condition ID (odd length hex)
        result = ConditionalTokenFramework.get_onchain_resolution_status("0x123", web3=mock_web3)
        assert result is None

    def test_get_onchain_resolution_status_contract_call_failure(self, mock_web3, mock_contract):
        condition_id = "0x" + "00" * 32

        # Mock payoutDenominator to raise exception
        mock_contract.functions.payoutDenominator.return_value.call.side_effect = Exception("Contract error")

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)
        assert result is None

    def test_get_onchain_resolution_status_unresolved(self, mock_web3, mock_contract):
        condition_id = "0x" + "00" * 32

        # Mock payoutDenominator to return 0
        mock_contract.functions.payoutDenominator.return_value.call.return_value = 0

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)
        assert result is None

    def test_get_onchain_resolution_status_resolved_binary(self, mock_web3, mock_contract):
        condition_id = "0x" + "00" * 32

        # Mock payoutDenominator to return 1 (binary market often resolves with denominator 1, payouts summing to 1)
        # Or denominator could be large number like 10**18

        denominator = 100
        mock_contract.functions.payoutDenominator.return_value.call.return_value = denominator

        # Mock payoutNumerators
        # Let's say it's outcome A wins (full payout)
        # Index 0: 0
        # Index 1: 100

        def payout_side_effect(condition_id_bytes, index):
            if index == 0:
                return 0
            if index == 1:
                return 100
            if index == 2:
                # Should not be called if logic is correct
                return 0
            raise Exception("Index out of bounds")

        mock_contract.functions.payoutNumerators.side_effect = None
        # The code does contract.functions.payoutNumerators(condition_id_bytes, i).call()
        # So we need to mock the call chain.

        # Creating a more sophisticated mock for the double call
        # contract.functions.payoutNumerators returns a function object which has .call()

        # We can use side_effect on the function call itself

        payout_numerators_mock = MagicMock()
        mock_contract.functions.payoutNumerators = payout_numerators_mock

        def call_side_effect(condition_id_bytes, index):
            mock_call = MagicMock()
            if index == 0:
                mock_call.call.return_value = 0
            elif index == 1:
                mock_call.call.return_value = 100
            else:
                mock_call.call.return_value = 0
            return mock_call

        payout_numerators_mock.side_effect = call_side_effect

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)

        assert result == [0, 100]
        # It should have called 2 times: index 0 and index 1.
        # At index 1, sum becomes 0+100 = 100 >= denominator(100), so it breaks.

    def test_get_onchain_resolution_status_safety_limit(self, mock_web3, mock_contract):
        condition_id = "0x" + "00" * 32
        denominator = 100
        mock_contract.functions.payoutDenominator.return_value.call.return_value = denominator

        # Mock payoutNumerators to return 1 for each index
        # This will simulate hitting the loop limit (10) since sum won't reach 100

        payout_numerators_mock = MagicMock()
        mock_contract.functions.payoutNumerators = payout_numerators_mock

        mock_call_obj = MagicMock()
        mock_call_obj.call.return_value = 1
        payout_numerators_mock.return_value = mock_call_obj

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)

        assert len(result) == 10
        assert result == [1] * 10

    def test_get_onchain_resolution_status_payout_exception(self, mock_web3, mock_contract):
        condition_id = "0x" + "00" * 32
        denominator = 100
        mock_contract.functions.payoutDenominator.return_value.call.return_value = denominator

        payout_numerators_mock = MagicMock()
        mock_contract.functions.payoutNumerators = payout_numerators_mock

        # First call succeeds, second raises exception
        mock_call_0 = MagicMock()
        mock_call_0.call.return_value = 50

        mock_call_1 = MagicMock()
        mock_call_1.call.side_effect = Exception("Some error")

        payout_numerators_mock.side_effect = [mock_call_0, mock_call_1]

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)

        # Should return [50] and stop
        assert result == [50]

    def test_default_web3_initialization(self):
        condition_id = "0x" + "00" * 32

        # Use patch to mock Web3 constructor
        with patch('agentpit.polymarket.conditional_token_framework.Web3') as MockWeb3Class:
             # Also need to mock instance returned by Web3()
            mock_web3_instance = MockWeb3Class.return_value
            mock_contract = MagicMock()
            mock_web3_instance.eth.contract.return_value = mock_contract

            mock_contract.functions.payoutDenominator.return_value.call.return_value = 0

            result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id)

            assert result is None
            # Verify Web3 was instantiated with HTTPProvider
            MockWeb3Class.assert_called()
            MockWeb3Class.HTTPProvider.assert_called()

