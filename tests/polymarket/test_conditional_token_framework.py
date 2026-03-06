import pytest
from unittest.mock import MagicMock, patch
from agentpit.polymarket.conditional_token_framework import ConditionalTokenFramework, OnchainResolutionStatus, ConditionId
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
        condition_id_invalid = ConditionId("invalid_id")
        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id_invalid, web3=mock_web3)
        assert result is None

        # Invalid condition ID (odd length hex)
        condition_id_invalid_hex = ConditionId("0x123")
        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id_invalid_hex, web3=mock_web3)
        assert result is None

        # --- Scenario 2: Contract call failure ---
        condition_id_bytes_32 = "0x" + "00" * 32
        condition_id = ConditionId(condition_id_bytes_32)

        mock_contract.functions.payoutDenominator.return_value.call.side_effect = Exception("Contract error")

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)
        assert result is None

        mock_contract.functions.payoutDenominator.return_value.call.side_effect = None

        # --- Scenario 3: Unresolved (denominator == 0) ---
        mock_contract.functions.payoutDenominator.return_value.call.return_value = 0

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)

        assert isinstance(result, OnchainResolutionStatus)
        assert result.payouts == []
        assert result.denominator == 0
        assert result.resolved is False

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

        payout_numerators_mock.side_effect = call_side_effect_binary

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)

        assert isinstance(result, OnchainResolutionStatus)
        assert result.payouts == [0, 100]
        assert result.denominator == 100
        assert result.resolved is True

        # --- Scenario 5: Safety Limit ---
        mock_contract.functions.payoutDenominator.return_value.call.return_value = denominator

        payout_numerators_mock = MagicMock()
        mock_contract.functions.payoutNumerators = payout_numerators_mock

        mock_call_obj = MagicMock()
        mock_call_obj.call.return_value = 1

        payout_numerators_mock.side_effect = None
        payout_numerators_mock.return_value = mock_call_obj

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)

        assert isinstance(result, OnchainResolutionStatus)
        assert len(result.payouts) == 10
        assert result.payouts == [1] * 10
        assert result.denominator == 100
        assert result.resolved is False

        # --- Scenario 6: Payout Exception ---
        mock_contract.functions.payoutDenominator.return_value.call.return_value = denominator

        payout_numerators_mock = MagicMock()
        mock_contract.functions.payoutNumerators = payout_numerators_mock

        mock_call_0 = MagicMock()
        mock_call_0.call.return_value = 50

        mock_call_1 = MagicMock()
        mock_call_1.call.side_effect = Exception("Some error")

        payout_numerators_mock.side_effect = [mock_call_0, mock_call_1]

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)

        assert result.payouts == [50]
        assert result.denominator == 100
        assert result.resolved is False

        # --- Scenario 7: Default Web3 Initialization ---
        with patch('agentpit.polymarket.conditional_token_framework.Web3') as MockWeb3Class:
            mock_web3_instance = MockWeb3Class.return_value
            mock_contract_default = MagicMock()
            mock_web3_instance.eth.contract.return_value = mock_contract_default

            mock_contract_default.functions.payoutDenominator.return_value.call.return_value = 0

            result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id)

            assert isinstance(result, OnchainResolutionStatus)
            assert result.resolved is False

            MockWeb3Class.assert_called()

