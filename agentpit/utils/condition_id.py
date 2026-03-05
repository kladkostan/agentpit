from eth_utils import keccak
from eth_abi import encode

from agentpit.contract_simulators.contract_addresses import EASYNET_ORACLE_ADDRESS


def compute_condition_id(question: str, outcome_slot_count: int) -> bytes:
    """
    Compute condition_id using keccak256(abi.encodePacked(oracle, questionId, outcomeSlotCount))

    Args:
        question: Question string (will be hashed to create questionId as 32-byte keccak256)
        outcome_slot_count: Number of outcome slots

    Returns:
        condition_id as bytes32
    """
    # Compute question_id as keccak256 hash of the question
    question_id = keccak(text=question)

    oracle = EASYNET_ORACLE_ADDRESS
    # Normalize oracle address (remove 0x if present, convert to bytes)
    if oracle.startswith('0x'):
        oracle = oracle[2:]
    oracle_bytes = bytes.fromhex(oracle)

    # For abi.encodePacked: concatenate raw bytes without padding
    # address (20 bytes) + bytes32 (32 bytes) + uint256 (32 bytes)
    packed = oracle_bytes + question_id + outcome_slot_count.to_bytes(32, byteorder='big')

    return keccak(packed)
