import pytest
from unittest.mock import MagicMock, patch

from agentpit.common import check_state
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

    def test_get_outcome_slot_count(self, mock_web3, mock_contract):
        condition_id = ConditionId("0x" + "11" * 32)
        mock_contract.functions.getOutcomeSlotCount.return_value.call.return_value = 3

        count = ConditionalTokenFramework.get_outcome_slot_count(condition_id, web3=mock_web3)

        assert count == 3

    def test_get_outcome_slot_count_default_web3_initialization(self):
        condition_id = ConditionId("0x" + "22" * 32)

        with patch('agentpit.polymarket.conditional_token_framework.Web3') as MockWeb3Class:
            mock_web3_instance = MockWeb3Class.return_value
            mock_contract = MagicMock()
            mock_web3_instance.eth.contract.return_value = mock_contract
            mock_contract.functions.getOutcomeSlotCount.return_value.call.return_value = 2

            count = ConditionalTokenFramework.get_outcome_slot_count(condition_id)

            assert count == 2
            MockWeb3Class.assert_called()

    def test_get_onchain_resolution_status_all_scenarios(self, mock_web3, mock_contract):
        # --- Scenario 1: Invalid condition ID ---
        # Invalid condition ID (not hex)
        condition_id_invalid = ConditionId("invalid_id")
        with pytest.raises(ValueError):
            ConditionalTokenFramework.get_onchain_resolution_status(condition_id_invalid, web3=mock_web3)

        # Invalid condition ID (odd length hex)
        condition_id_invalid_hex = ConditionId("0x123")
        with pytest.raises(ValueError):
            ConditionalTokenFramework.get_onchain_resolution_status(condition_id_invalid_hex, web3=mock_web3)

        # --- Scenario 2: Contract call failure ---
        condition_id_bytes_32 = "0x" + "00" * 32
        condition_id = ConditionId(condition_id_bytes_32)

        mock_contract.functions.payoutDenominator.return_value.call.side_effect = Exception("Contract error")

        with pytest.raises(Exception, match="Contract error"):
            ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)

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
        mock_contract.functions.getOutcomeSlotCount.return_value.call.return_value = 2

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

        # --- Scenario 5: Bounded by outcome slot count ---
        mock_contract.functions.payoutDenominator.return_value.call.return_value = denominator
        mock_contract.functions.getOutcomeSlotCount.return_value.call.return_value = 3

        payout_numerators_mock = MagicMock()
        mock_contract.functions.payoutNumerators = payout_numerators_mock

        mock_call_obj = MagicMock()
        mock_call_obj.call.return_value = 1

        payout_numerators_mock.side_effect = None
        payout_numerators_mock.return_value = mock_call_obj

        result = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)

        assert isinstance(result, OnchainResolutionStatus)
        assert len(result.payouts) == 3
        assert result.payouts == [1] * 3
        assert result.denominator == 100
        assert result.resolved is False

        # --- Scenario 6: Payout Exception ---
        mock_contract.functions.payoutDenominator.return_value.call.return_value = denominator
        mock_contract.functions.getOutcomeSlotCount.return_value.call.return_value = 2

        payout_numerators_mock = MagicMock()
        mock_contract.functions.payoutNumerators = payout_numerators_mock

        mock_call_0 = MagicMock()
        mock_call_0.call.return_value = 50

        mock_call_1 = MagicMock()
        mock_call_1.call.side_effect = Exception("Some error")

        # side_effect list applies to consecutive calls to payoutNumerators
        # 1st call: i=0 -> returns mock_call_0 which returns 50
        # 2nd call: i=1 -> returns mock_call_1 which raises Exception on call()

        # When payoutNumerators is called, it returns a mock object that has a .call() method.
        # We need to set side_effect on the mock object returned by payoutNumerators call...
        # But here payoutNumerators(condition_id_bytes, i) is called.

        # In test setup:
        # payout_numerators_mock is assigned to mock_contract.functions.payoutNumerators
        # payout_numerators_mock(bytes, i) returns a mock object (let's call it 'method_mock')
        # method_mock.call() is then called.

        # So we need payout_numerators_mock.side_effect to return different method_mocks.
        payout_numerators_mock.side_effect = [mock_call_0, mock_call_1]

        with pytest.raises(Exception, match="Some error"):
            ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3=mock_web3)

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

    @pytest.mark.integration
    def test_get_onchain_resolution_status_real_unresolved_market(self):
        """
        This is an integration test that checks the resolution of a real market on Polygon.
        It will fail if there is no connection or if the RPC is down.
        """
        # This is the conditionId for the Polymarket market:
        # "Will the US federal debt be over $34T by Feb 1, 2024?"
        # This market resolved to "Yes".
        condition_id = ConditionId("0x55757944295b6994355171361952eb86904f3b5a9b4c6ab1ee99a6b349424313")

        # This test uses a public Polygon RPC.
        web3 = Web3(Web3.HTTPProvider("https://tenderly.rpc.polygon.community/"))

        status = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3)

        assert status.resolved is False
        assert status.get_winner_index() is None   # Payout for "Yes" is 1, "No" is 0

    @pytest.mark.integration
    def test_get_onchain_resolution_status_real_resolved_market(self):
        """
        This is an integration test that checks the resolution of a real market on Polygon.
        It will fail if there is no connection or if the RPC is down.
        """
        # This is the conditionId for the Polymarket market:
        # "Will the US federal debt be over $34T by Feb 1, 2024?"
        # This market resolved to "Yes".

        # This test uses a public Polygon RPC.
        web3 = Web3(Web3.HTTPProvider("https://tenderly.rpc.polygon.community/"))

        condition_id = ConditionId("0xe3b423dfad8c22ff75c9899c4e8176f628cf4ad4caa00481764d320e7415f7a9")


        slot_count = ConditionalTokenFramework.get_outcome_slot_count(condition_id, web3)

        check_state(slot_count == 2, "Expected positive slot count for resolved market")


        status = ConditionalTokenFramework.get_onchain_resolution_status(condition_id, web3)

        assert status.resolved is True
        assert status.get_winner_index() == 1   # Payout for "Yes" is 1, "No" is 0
