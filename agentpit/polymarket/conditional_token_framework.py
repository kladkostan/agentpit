from web3 import Web3

from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.onchain_resolution_status import OnchainResolutionStatus
from agentpit.utils.parse import hex2bytes

CTF_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "", "type": "bytes32"}],
        "name": "payoutDenominator",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "", "type": "bytes32"}, {"name": "", "type": "uint256"}],
        "name": "payoutNumerators",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "conditionId", "type": "bytes32"}],
        "name": "getOutcomeSlotCount",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
]

CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
POLYGON_RPC = "https://polygon-rpc.com"

class ConditionalTokenFramework:

    @staticmethod
    def get_outcome_slot_count(condition_id: ConditionId, web3: Web3 = None) -> int:
        if web3 is None:
            web3 = Web3(Web3.HTTPProvider(POLYGON_RPC))

        contract_address = Web3.to_checksum_address(CTF_ADDRESS)
        contract = web3.eth.contract(address=contract_address, abi=CTF_ABI)

        condition_id_bytes = hex2bytes(condition_id.value)
        return contract.functions.getOutcomeSlotCount(condition_id_bytes).call()

    @staticmethod
    def get_onchain_resolution_status(condition_id: ConditionId, web3: Web3 = None) -> OnchainResolutionStatus:
        if web3 is None:
            web3 = Web3(Web3.HTTPProvider(POLYGON_RPC))

        contract_address = Web3.to_checksum_address(CTF_ADDRESS)
        contract = web3.eth.contract(address=contract_address, abi=CTF_ABI)

        # Check if resolved
        # condition_id must be bytes32
        val = condition_id.value

        condition_id_bytes = hex2bytes(val)

        denominator = contract.functions.payoutDenominator(condition_id_bytes).call()

        if denominator == 0:
            return OnchainResolutionStatus(payouts=[], denominator=0, resolved=False)


        payouts = []
        current_sum = 0
        i = 0
        # Safety limit
        while i < 10:
            payout = contract.functions.payoutNumerators(condition_id_bytes, i).call()
            payouts.append(payout)
            current_sum += payout
            if current_sum >= denominator:
                break
            i += 1

        return OnchainResolutionStatus(
            payouts=payouts,
            denominator=denominator,
            resolved=current_sum >= denominator
        )
