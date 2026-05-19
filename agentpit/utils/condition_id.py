from eth_utils import keccak

from agentpit.datastructures.condition_id import ConditionId


def compute_condition_id(
    question: str, outcome_slot_count: int, oracle: str
) -> ConditionId:
    """Compute the on-chain condition_id locally.

    Mirrors `CTF.getConditionId(oracle, questionId, outcomeSlotCount)`:
        keccak256(abi.encodePacked(oracle, questionId, outcomeSlotCount))

    The Polymarket sync path uses this to dedupe markets without an RPC round-trip.
    For local market creation we call the on-chain getter instead, so the
    formulas line up by construction.
    """
    question_id = keccak(text=question)

    if oracle.startswith("0x"):
        oracle = oracle[2:]
    oracle_bytes = bytes.fromhex(oracle)

    packed = (
        oracle_bytes + question_id + outcome_slot_count.to_bytes(32, byteorder="big")
    )
    return ConditionId("0x" + keccak(packed).hex())
