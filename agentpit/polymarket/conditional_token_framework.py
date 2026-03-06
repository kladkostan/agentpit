from typing import Optional, List

from web3 import Web3

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
]

CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
POLYGON_RPC = "https://polygon-rpc.com"

class ConditionalTokenFramework:

    @staticmethod
    def get_onchain_resolution_status(condition_id: str, web3: Web3 = None) -> Optional[List[int]]:
        if web3 is None:
            web3 = Web3(Web3.HTTPProvider(POLYGON_RPC))

        contract_address = Web3.to_checksum_address(CTF_ADDRESS)
        contract = web3.eth.contract(address=contract_address, abi=CTF_ABI)

        # Check if resolved
        # condition_id must be bytes32
        try:
            if condition_id.startswith("0x"):
                condition_id_bytes = bytes.fromhex(condition_id[2:])
            else:
                condition_id_bytes = bytes.fromhex(condition_id)
        except ValueError:
            return None

        try:
            denominator = contract.functions.payoutDenominator(condition_id_bytes).call()
        except Exception:
            # If call fails (e.g. invalid condition ID), return None or re-raise
            return None

        if denominator == 0:
            return None

        # Get payouts for binary market (most common)
        # We iterate until we find all numerators that sum up to denominator
        # or just assume 2 for now as Polymarket is mostly binary.
        # However, to be safe, we can try fetching 0 and 1.

        payouts = []
        current_sum = 0
        i = 0
        # Safety limit
        while i < 10:
            try:
                payout = contract.functions.payoutNumerators(condition_id_bytes, i).call()
                payouts.append(payout)
                current_sum += payout
                if current_sum >= denominator:
                    break
                i += 1
            except Exception:
                break

        return payouts

