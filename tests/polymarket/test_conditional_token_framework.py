import pytest
from unittest.mock import MagicMock, patch
from agentpit.polymarket.conditional_token_framework import ConditionalTokenFramework
from web3 import Web3

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

    def test_get_onchain_resolution_status_all_scenarios(self, mock_web3, mock_contract):
        # --- Scenario 1: Invalid condition ID ---
        # Invalid condition ID (not hex)
        result = ConditionalTokenFramework.get_onchain_resolution_status("invalid_id", web3=mock_web3)
        assert result is None

        # Invalid condition ID (odd length hex)
        result = ConditionalTokenFramework.get_onchain_resolution_status("0x123", web3=mock_web3)
        assert result is None

        # --- Scenario 2: Contract call failure ---
        condition_id_bytes_32 = "0x" + "00" * 32

        mock_contract.functions.payoutDenominator.return_value.call.side_effect = Exception("Contract error")

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id_bytes_32, web3=mock_web3)
        assert result is None

        mock_contract.functions.payoutDenominator.return_value.call.side_effect = None

        # --- Scenario 3: Unresolved ---
        mock_contract.functions.payoutDenominator.return_value.call.return_value = 0

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id_bytes_32, web3=mock_web3)
        assert result is None

        # --- Scenario 4: Resolved Binary ---
        denominator = 100
        mock_contract.functions.payoutDenominator.return_value.call.return_value = denominator

        payout_numerators_mock = MagicMock()
        mock_contract.functions.payoutNumerators = payout_numerators_mock

        def call_side_effect_binary(condition_id_bytes, index):
            mock_call = MagicMock()
            if index == 0:
                mock_call.call.return_value = 0
            elif index == 1:
                mock_call.call.return_value = 100
            else:
                mock_call.call.return_value = 0
            return mock_call

        # Re-assign side_effect to the mocked function object
        # Note: payoutNumerators is a function that returns a contract function object.
        # But here we are mocking `contract.functions.payoutNumerators` itself.
        payout_numerators_mock.side_effect = call_side_effect_binary

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id_bytes_32, web3=mock_web3)
        assert result == [0, 100]

        # --- Scenario 5: Safety Limit ---
        mock_contract.functions.payoutDenominator.return_value.call.return_value = denominator

        payout_numerators_mock = MagicMock()
        mock_contract.functions.payoutNumerators = payout_numerators_mock

        mock_call_obj = MagicMock()
        mock_call_obj.call.return_value = 1
        payout_numerators_mock.return_value = mock_call_obj

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id_bytes_32, web3=mock_web3)

        assert len(result) == 10
        assert result == [1] * 10

        # --- Scenario 6: Payout Exception ---
        mock_contract.functions.payoutDenominator.return_value.call.return_value = denominator

        payout_numerators_mock = MagicMock()
        mock_contract.functions.payoutNumerators = payout_numerators_mock

        mock_call_0 = MagicMock()
        mock_call_0.call.return_value = 50

        mock_call_1 = MagicMock()
        mock_call_1.call.side_effect = Exception("Some error")

        # side_effect on the call `payoutNumerators(...)`
        payout_numerators_mock.side_effect = [mock_call_0, mock_call_1]

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id_bytes_32, web3=mock_web3)

        assert result == [50]

        # --- Scenario 7: Default Web3 Initialization ---
        with patch('agentpit.polymarket.conditional_token_framework.Web3') as MockWeb3Class:
            # We must configure the mock class to behave like a class that returns an instance
            mock_web3_instance = MockWeb3Class.return_value

            # The code does `contract = web3.eth.contract(...)`
            # So `mock_web3_instance.eth.contract` should return a mock contract
            mock_contract_default = MagicMock()
            mock_web3_instance.eth.contract.return_value = mock_contract_default

            # Setup behavior for payoutDenominator
            mock_contract_default.functions.payoutDenominator.return_value.call.return_value = 0

            # Call without web3 arg
            result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id_bytes_32)

            assert result is None

            # Verify Web3 was instantiated
            MockWeb3Class.assert_called()

