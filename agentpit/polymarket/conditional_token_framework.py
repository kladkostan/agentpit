from web3 import Web3

from agentpit.common import check_state
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.onchain_resolution_status import OnchainResolutionStatus
from agentpit.utils.parse import hex2bytes

CTF_ABI = [{"constant": True, "inputs": [{"name": "owner", "type": "address"}, {"name": "id", "type": "uint256"}],
            "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "payable": False,
            "stateMutability": "view", "type": "function"}, {"constant": False,
                                                             "inputs": [{"name": "collateralToken", "type": "address"},
                                                                        {"name": "parentCollectionId",
                                                                         "type": "bytes32"},
                                                                        {"name": "conditionId", "type": "bytes32"},
                                                                        {"name": "indexSets", "type": "uint256[]"}],
                                                             "name": "redeemPositions", "outputs": [], "payable": False,
                                                             "stateMutability": "nonpayable", "type": "function"},
           {"constant": True, "inputs": [{"name": "interfaceId", "type": "bytes4"}], "name": "supportsInterface",
            "outputs": [{"name": "", "type": "bool"}], "payable": False, "stateMutability": "view", "type": "function"},
           {"constant": True, "inputs": [{"name": "", "type": "bytes32"}, {"name": "", "type": "uint256"}],
            "name": "payoutNumerators", "outputs": [{"name": "", "type": "uint256"}], "payable": False,
            "stateMutability": "view", "type": "function"}, {"constant": False,
                                                             "inputs": [{"name": "from", "type": "address"},
                                                                        {"name": "to", "type": "address"},
                                                                        {"name": "ids", "type": "uint256[]"},
                                                                        {"name": "values", "type": "uint256[]"},
                                                                        {"name": "data", "type": "bytes"}],
                                                             "name": "safeBatchTransferFrom", "outputs": [],
                                                             "payable": False, "stateMutability": "nonpayable",
                                                             "type": "function"}, {"constant": True, "inputs": [
        {"name": "collateralToken", "type": "address"}, {"name": "collectionId", "type": "bytes32"}],
                                                                                   "name": "getPositionId", "outputs": [
            {"name": "", "type": "uint256"}], "payable": False, "stateMutability": "pure", "type": "function"},
           {"constant": True, "inputs": [{"name": "owners", "type": "address[]"}, {"name": "ids", "type": "uint256[]"}],
            "name": "balanceOfBatch", "outputs": [{"name": "", "type": "uint256[]"}], "payable": False,
            "stateMutability": "view", "type": "function"}, {"constant": False,
                                                             "inputs": [{"name": "collateralToken", "type": "address"},
                                                                        {"name": "parentCollectionId",
                                                                         "type": "bytes32"},
                                                                        {"name": "conditionId", "type": "bytes32"},
                                                                        {"name": "partition", "type": "uint256[]"},
                                                                        {"name": "amount", "type": "uint256"}],
                                                             "name": "splitPosition", "outputs": [], "payable": False,
                                                             "stateMutability": "nonpayable", "type": "function"},
           {"constant": True,
            "inputs": [{"name": "oracle", "type": "address"}, {"name": "questionId", "type": "bytes32"},
                       {"name": "outcomeSlotCount", "type": "uint256"}], "name": "getConditionId",
            "outputs": [{"name": "", "type": "bytes32"}], "payable": False, "stateMutability": "pure",
            "type": "function"}, {"constant": True, "inputs": [{"name": "parentCollectionId", "type": "bytes32"},
                                                               {"name": "conditionId", "type": "bytes32"},
                                                               {"name": "indexSet", "type": "uint256"}],
                                  "name": "getCollectionId", "outputs": [{"name": "", "type": "bytes32"}],
                                  "payable": False, "stateMutability": "view", "type": "function"}, {"constant": False,
                                                                                                     "inputs": [{
                                                                                                         "name": "collateralToken",
                                                                                                         "type": "address"},
                                                                                                         {
                                                                                                             "name": "parentCollectionId",
                                                                                                             "type": "bytes32"},
                                                                                                         {
                                                                                                             "name": "conditionId",
                                                                                                             "type": "bytes32"},
                                                                                                         {
                                                                                                             "name": "partition",
                                                                                                             "type": "uint256[]"},
                                                                                                         {
                                                                                                             "name": "amount",
                                                                                                             "type": "uint256"}],
                                                                                                     "name": "mergePositions",
                                                                                                     "outputs": [],
                                                                                                     "payable": False,
                                                                                                     "stateMutability": "nonpayable",
                                                                                                     "type": "function"},
           {"constant": False,
            "inputs": [{"name": "operator", "type": "address"}, {"name": "approved", "type": "bool"}],
            "name": "setApprovalForAll", "outputs": [], "payable": False, "stateMutability": "nonpayable",
            "type": "function"}, {"constant": False, "inputs": [{"name": "questionId", "type": "bytes32"},
                                                                {"name": "payouts", "type": "uint256[]"}],
                                  "name": "reportPayouts", "outputs": [], "payable": False,
                                  "stateMutability": "nonpayable", "type": "function"},
           {"constant": True, "inputs": [{"name": "conditionId", "type": "bytes32"}], "name": "getOutcomeSlotCount",
            "outputs": [{"name": "", "type": "uint256"}], "payable": False, "stateMutability": "view",
            "type": "function"}, {"constant": False, "inputs": [{"name": "oracle", "type": "address"},
                                                                {"name": "questionId", "type": "bytes32"},
                                                                {"name": "outcomeSlotCount", "type": "uint256"}],
                                  "name": "prepareCondition", "outputs": [], "payable": False,
                                  "stateMutability": "nonpayable", "type": "function"},
           {"constant": True, "inputs": [{"name": "", "type": "bytes32"}], "name": "payoutDenominator",
            "outputs": [{"name": "", "type": "uint256"}], "payable": False, "stateMutability": "view",
            "type": "function"},
           {"constant": True, "inputs": [{"name": "owner", "type": "address"}, {"name": "operator", "type": "address"}],
            "name": "isApprovedForAll", "outputs": [{"name": "", "type": "bool"}], "payable": False,
            "stateMutability": "view", "type": "function"}, {"constant": False,
                                                             "inputs": [{"name": "from", "type": "address"},
                                                                        {"name": "to", "type": "address"},
                                                                        {"name": "id", "type": "uint256"},
                                                                        {"name": "value", "type": "uint256"},
                                                                        {"name": "data", "type": "bytes"}],
                                                             "name": "safeTransferFrom", "outputs": [],
                                                             "payable": False, "stateMutability": "nonpayable",
                                                             "type": "function"}, {"anonymous": False, "inputs": [
        {"indexed": True, "name": "conditionId", "type": "bytes32"},
        {"indexed": True, "name": "oracle", "type": "address"},
        {"indexed": True, "name": "questionId", "type": "bytes32"},
        {"indexed": False, "name": "outcomeSlotCount", "type": "uint256"}], "name": "ConditionPreparation",
                                                                                   "type": "event"},
           {"anonymous": False, "inputs": [{"indexed": True, "name": "conditionId", "type": "bytes32"},
                                           {"indexed": True, "name": "oracle", "type": "address"},
                                           {"indexed": True, "name": "questionId", "type": "bytes32"},
                                           {"indexed": False, "name": "outcomeSlotCount", "type": "uint256"},
                                           {"indexed": False, "name": "payoutNumerators", "type": "uint256[]"}],
            "name": "ConditionResolution", "type": "event"}, {"anonymous": False, "inputs": [
        {"indexed": True, "name": "stakeholder", "type": "address"},
        {"indexed": False, "name": "collateralToken", "type": "address"},
        {"indexed": True, "name": "parentCollectionId", "type": "bytes32"},
        {"indexed": True, "name": "conditionId", "type": "bytes32"},
        {"indexed": False, "name": "partition", "type": "uint256[]"},
        {"indexed": False, "name": "amount", "type": "uint256"}], "name": "PositionSplit", "type": "event"},
           {"anonymous": False, "inputs": [{"indexed": True, "name": "stakeholder", "type": "address"},
                                           {"indexed": False, "name": "collateralToken", "type": "address"},
                                           {"indexed": True, "name": "parentCollectionId", "type": "bytes32"},
                                           {"indexed": True, "name": "conditionId", "type": "bytes32"},
                                           {"indexed": False, "name": "partition", "type": "uint256[]"},
                                           {"indexed": False, "name": "amount", "type": "uint256"}],
            "name": "PositionsMerge", "type": "event"}, {"anonymous": False, "inputs": [
        {"indexed": True, "name": "redeemer", "type": "address"},
        {"indexed": True, "name": "collateralToken", "type": "address"},
        {"indexed": True, "name": "parentCollectionId", "type": "bytes32"},
        {"indexed": False, "name": "conditionId", "type": "bytes32"},
        {"indexed": False, "name": "indexSets", "type": "uint256[]"},
        {"indexed": False, "name": "payout", "type": "uint256"}], "name": "PayoutRedemption", "type": "event"},
           {"anonymous": False, "inputs": [{"indexed": True, "name": "operator", "type": "address"},
                                           {"indexed": True, "name": "from", "type": "address"},
                                           {"indexed": True, "name": "to", "type": "address"},
                                           {"indexed": False, "name": "id", "type": "uint256"},
                                           {"indexed": False, "name": "value", "type": "uint256"}],
            "name": "TransferSingle", "type": "event"}, {"anonymous": False, "inputs": [
        {"indexed": True, "name": "operator", "type": "address"}, {"indexed": True, "name": "from", "type": "address"},
        {"indexed": True, "name": "to", "type": "address"}, {"indexed": False, "name": "ids", "type": "uint256[]"},
        {"indexed": False, "name": "values", "type": "uint256[]"}], "name": "TransferBatch", "type": "event"},
           {"anonymous": False, "inputs": [{"indexed": True, "name": "owner", "type": "address"},
                                           {"indexed": True, "name": "operator", "type": "address"},
                                           {"indexed": False, "name": "approved", "type": "bool"}],
            "name": "ApprovalForAll", "type": "event"}, {"anonymous": False, "inputs": [
        {"indexed": False, "name": "value", "type": "string"}, {"indexed": True, "name": "id", "type": "uint256"}],
                                                         "name": "URI", "type": "event"}]

CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
POLYGON_RPC = "https://tenderly.rpc.polygon.community"


class ConditionalTokenFramework:

    @staticmethod
    def condition_exists(condition_id: ConditionId) -> bool:
        return ConditionalTokenFramework.get_outcome_slot_count(condition_id) > 0

    @staticmethod
    def get_outcome_slot_count(condition_id: ConditionId) -> int:

        web3 = Web3(Web3.HTTPProvider(POLYGON_RPC))

        contract_address = Web3.to_checksum_address(CTF_ADDRESS)
        contract = web3.eth.contract(address=contract_address, abi=CTF_ABI)

        condition_id_bytes = hex2bytes(condition_id.value)
        return contract.functions.getOutcomeSlotCount(condition_id_bytes).call()

    @staticmethod
    def get_onchain_resolution_status(
            condition_id: ConditionId
    ) -> OnchainResolutionStatus:

        web3 = Web3(Web3.HTTPProvider(POLYGON_RPC))

        contract_address = Web3.to_checksum_address(CTF_ADDRESS)
        contract = web3.eth.contract(address=contract_address, abi=CTF_ABI)

        # Check if resolved
        # condition_id must be bytes32

        check_state(
            ConditionalTokenFramework.condition_exists(condition_id),
            f"Condition {condition_id.value} does not exist on chain",
        )

        condition_id_bytes = hex2bytes(condition_id.value)

        denominator = contract.functions.payoutDenominator(condition_id_bytes).call()

        outcome_slot_count = ConditionalTokenFramework.get_outcome_slot_count(
            condition_id
        )

        if denominator == 0:
            return OnchainResolutionStatus(payouts=[], denominator=0, resolved=False)

        payouts = []
        current_sum = 0
        for i in range(outcome_slot_count):
            payout = contract.functions.payoutNumerators(condition_id_bytes, i).call()
            payouts.append(payout)
            current_sum += payout
            if current_sum >= denominator:
                break

        return OnchainResolutionStatus(
            payouts=payouts,
            denominator=denominator,
            resolved=current_sum >= denominator,
        )
