import pytest
from unittest.mock import MagicMock, patch

from agentpit.common import check_state
from agentpit.polymarket.conditional_token_framework import (
    ConditionalTokenFramework,
    OnchainResolutionStatus,
    ConditionId,
)
from web3 import Web3


class TestConditionalTokenFramework:

    @pytest.mark.integration
    def test_get_onchain_resolution_status_real_resolved_market(self):
        """
        This is an integration test that checks the resolution of a real market on Polygon.
        It will fail if there is no connection or if the RPC is down.
        """
        # This is the conditionId for the Polymarket market:
        # "Will the US federal debt be over $34T by Feb 1, 2024?"
        # This market resolved to "Yes".

        condition_id = ConditionId(
            "0xe3b423dfad8c22ff75c9899c4e8176f628cf4ad4caa00481764d320e7415f7a9"
        )

        slot_count = ConditionalTokenFramework.get_outcome_slot_count(condition_id)

        check_state(slot_count == 2, "Expected positive slot count for resolved market")

        status = ConditionalTokenFramework.get_onchain_resolution_status(condition_id)

        assert status.resolved is True
        assert status.get_winner_index() == 1  # Payout for "Yes" is 1, "No" is 0
