# Conditional Token Framework — Design Specification
## Purpose
`agentpit/polymarket/conditional_token_framework.py` is a thin read-only wrapper around the **Gnosis Conditional Token Framework (CTF)** ERC-1155 smart contract on Polygon Mainnet. It answers two questions during market sync:
1. **Does this condition exist on-chain?** (Is the condition prepared by an oracle?)
2. **Has this condition been resolved, and if so, which outcome won?**
No transactions are ever sent. All contract calls are pure `view` reads.
---
## Background: How the CTF Works
The Gnosis CTF is the settlement layer underlying Polymarket. Understanding it helps make sense of the code.
### Condition Lifecycle

```
  oracle calls prepareCondition()
          │
          ▼
  PREPARED  ── getOutcomeSlotCount() → N (e.g. 2)
            ── payoutDenominator    → 0  (unresolved)
          │
          │  event resolves; oracle calls reportPayouts()
          ▼
  RESOLVED  ── payoutDenominator    → 1
            ── payoutNumerators[0]  → 1  (Yes wins)
            ── payoutNumerators[1]  → 0
               or
            ── payoutNumerators[0]  → 0  (No wins)
            ── payoutNumerators[1]  → 1
```

AgentPit reads this state but never writes to it. All CTF calls are `view` only.

---

### Conditions
A **condition** is identified by a `bytes32` `conditionId`, computed as:
```
conditionId = keccak256(abi.encodePacked(oracle, questionId, outcomeSlotCount))
```
Where:
- `oracle` — the address that will report the result (Polymarket uses their own oracle)
- `questionId` — a `bytes32` derived from the question (usually `keccak256(question_text)`)
- `outcomeSlotCount` — number of possible outcomes (typically `2` for Yes/No markets)
A condition is **prepared** by calling `prepareCondition()` on the CTF contract. Once prepared, `getOutcomeSlotCount()` returns a positive number. Before preparation, it returns `0`.
### Resolution
Resolution is recorded by the oracle calling `reportPayouts()`, which stores:
- `payoutDenominator` — the total "score" (e.g. `1`)
- `payoutNumerators[i]` — the score awarded to outcome slot `i`
For a binary market:
| Outcome | `payoutNumerators[0]` (Yes) | `payoutNumerators[1]` (No) | `payoutDenominator` |
|---------|----------------------------|---------------------------|---------------------|
| Unresolved | 0 | 0 | 0 |
| Yes wins | 1 | 0 | 1 |
| No wins | 0 | 1 | 1 |
The contract is considered resolved when `payoutDenominator > 0` and `sum(payoutNumerators) >= payoutDenominator`.
---
## Contract Details
| Property | Value |
|----------|-------|
| Contract | Gnosis `ConditionalTokens` (ERC-1155) |
| Network | Polygon Mainnet |
| Address | `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` |
| RPC | `https://tenderly.rpc.polygon.community` |
A new `Web3` + contract instance is created on every static method call. No connection pooling or caching is done.
---
## Class: `ConditionalTokenFramework`
All methods are `@staticmethod`. There is no instance state.
---
### `condition_exists(condition_id: ConditionId) → bool`
Returns `True` if the condition has been prepared on-chain.
```python
return ConditionalTokenFramework.get_outcome_slot_count(condition_id) > 0
```
**Called by:** `create_polygon_market_if_does_not_exist()` — markets whose condition is absent on-chain are silently skipped and never inserted into the local DB.
---
### `get_outcome_slot_count(condition_id: ConditionId) → int`
Calls `CTF.getOutcomeSlotCount(bytes32 conditionId)`.
Returns:
- `0` — condition not prepared (unknown condition ID)
- `2` — typical binary (Yes/No) market
- `N` — multi-outcome market
---
### `get_onchain_resolution_status(condition_id: ConditionId) → OnchainResolutionStatus`
The main resolution-check method. Steps:
```
get_onchain_resolution_status(condition_id)
        │
        ▼
condition_exists(condition_id)?
        │ no → raise via check_state (unknown condition)
        │ yes
        ▼
payoutDenominator(conditionId)
        │ = 0 → return OnchainResolutionStatus(resolved=False)
        │ > 0
        ▼
getOutcomeSlotCount(conditionId) → N
        │
        ▼
for i in 0..N:
  payoutNumerators(conditionId, i)
  running_sum += payout_i
  if running_sum >= denominator → break (early exit)
        │
        ▼
return OnchainResolutionStatus(
    payouts=[...], denominator=D,
    resolved=(running_sum >= denominator)
)
```
**Worked example — binary Yes/No market where Yes wins:**
```
getOutcomeSlotCount  → 2
payoutDenominator    → 1
payoutNumerators(0)  → 1   (Yes wins)
payoutNumerators(1)  → 0   (No loses, but early exit already hit)
OnchainResolutionStatus(payouts=[1, 0], denominator=1, resolved=True)
get_winner_index() → 0  (index where payout == denominator)
```
**Called by:** `sync_market_state()` — triggers `update_market_state_to_resolved_if_needed(winner_index)` in the local DB.
---
## ABI Calls Used
Only 3 of the contract's many functions are called by this module, all `view`:
| Solidity function | Signature | What it returns |
|-------------------|-----------|-----------------|
| `getOutcomeSlotCount` | `(bytes32) → uint256` | Number of outcome slots; 0 if unprepared |
| `payoutDenominator` | `(bytes32) → uint256` | Total payout score; 0 if unresolved |
| `payoutNumerators` | `(bytes32, uint256) → uint256` | Score for outcome at index `i` |
The `ConditionId.value` hex string is converted to `bytes32` via `agentpit.utils.parse.hex2bytes` before being passed to the contract.
---
## Supporting Dataclasses
### `ConditionId`  (`agentpit/datastructures/condition_id.py`)
```python
@dataclass
class ConditionId:
    value: str   # hex string, e.g. "0xe3b423..."
```
Validated on construction: `value` must be non-empty. This is a pure data wrapper — it does not validate that the string is a valid 32-byte hex value.
**Conversion to bytes32:**
```python
from agentpit.utils.parse import hex2bytes
condition_id_bytes = hex2bytes(condition_id.value)
```
---
### `OnchainResolutionStatus`  (`agentpit/datastructures/onchain_resolution_status.py`)
```python
@dataclass
class OnchainResolutionStatus:
    payouts: List[int]    # payout numerator per outcome slot
    denominator: int      # total payout denominator; 0 = unresolved
    resolved: bool        # True when sum(payouts) >= denominator
```
**`__post_init__` invariant:** if `resolved=True`, `get_winner_index()` must return a non-None value. Raises via `check_state` if violated (i.e. resolved but no single outcome has full payout).
#### `get_winner_index() → int | None`
Iterates `payouts` and returns the **first** index where `payout == denominator`. Returns `None` if not resolved.
```python
# payouts=[1, 0], denominator=1  → returns 0
# payouts=[0, 1], denominator=1  → returns 1
# payouts=[], denominator=0      → returns None (unresolved)
```
This index is passed directly to `TableWrite.update_market_state_to_resolved_if_needed(db, winner_index)`.
---
## Error Handling
| Situation | What happens |
|-----------|-------------|
| `condition_id` not on-chain | `check_state` raises `HTTPException(400, ...)` with call site info |
| `payoutDenominator == 0` | Returns `resolved=False` cleanly — not an error |
| RPC endpoint unreachable | `web3` raises a network exception that propagates to the caller |
| `resolved=True` but no outcome has full payout | `OnchainResolutionStatus.__post_init__` raises via `check_state` |
| Invalid `condition_id` hex | `hex2bytes` raises; propagates to caller |
---
## Integration with Polymarket Sync
```
polymarket_sync.create_polygon_market_if_does_not_exist(db, pm_market)
    │
    └─► CTF.condition_exists(condition_id)
            ├─ False ──► skip (market never inserted into DB)
            └─ True  ──► TableWrite.create_market(...)
polymarket_sync.sync_market_state(db, condition_id)
    │
    └─► CTF.get_onchain_resolution_status(condition_id)
            ├─ resolved=False ──► no action
            └─ resolved=True  ──► TableWrite.update_market_state_to_resolved_if_needed(
                                      db, status.get_winner_index()
                                  )
```
---
## Locally-Created Markets vs Polymarket Markets
AgentPit can create markets independently of Polymarket (via `POST /markets`). These markets compute their own `condition_id` locally using:
```python
# agentpit/utils/condition_id.py
condition_id = keccak256(
    oracle_bytes           # EASYNET_ORACLE_ADDRESS = 0xCB1822859cEF82Cd2Eb4E6276C7916e692995130
    + keccak256(question)  # questionId
    + outcome_count.to_bytes(32, 'big')
)
```
These locally-computed condition IDs will **not** exist on the Polygon CTF contract (they use the EasyNet oracle, not Polymarket's oracle). `CTF.condition_exists()` will return `False` for them, which is correct — they are never passed through the sync pipeline.
---
## Running Integration Tests
The only test for this module hits the live Polygon RPC:
```bash
pytest -s -m integration tests/polymarket/test_conditional_token_framework.py
```
**Test case:** `test_get_onchain_resolution_status_real_resolved_market`
- **Market:** "Will the US federal debt be over $34T by Feb 1, 2024?" (resolved Yes)
- **Condition ID:** `0xe3b423dfad8c22ff75c9899c4e8176f628cf4ad4caa00481764d320e7415f7a9`
- **Expected:** `resolved=True`, `get_winner_index() == 1` (outcome index 1 = "Yes" in this market's token ordering)
```python
condition_id = ConditionId("0xe3b423dfad8c22ff75c9899c4e8176f628cf4ad4caa00481764d320e7415f7a9")
slot_count = ConditionalTokenFramework.get_outcome_slot_count(condition_id)  # → 2
status = ConditionalTokenFramework.get_onchain_resolution_status(condition_id)
assert status.resolved is True
assert status.get_winner_index() == 1
```
---
## Performance Notes
- Each call to `condition_exists`, `get_outcome_slot_count`, or `get_onchain_resolution_status` creates a **new Web3 HTTP connection** and makes **1–3 RPC calls**.
- For large syncs (hundreds of markets), this is the dominant latency source.
- Future improvement: cache the Web3 instance and condition results per sync run, or batch via `eth_call` multicall.
