# Paper Balance Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every user a $100k paper balance with a once-a-day top-up button, and fund the house with a single mint instead of repeated faucet drips.

**Architecture:** The mock faucet gains an operator-gated `mintTo(address,uint256)` beside its fixed-amount `drip`, which also becomes operator-gated. Signup then mints exactly the grant, the house is one mint of a stated size, and the top-up button mints the difference up to the target. All of it lands in one chain redeploy.

**Tech Stack:** Solidity 0.8.15 / Foundry, Python 3.13 / FastAPI / psycopg3, React 19 / TypeScript / Vite.

## Global Constraints

- apUSD has **6 decimals**. Every on-chain amount in this plan is raw: $100,000 = `100_000 * 10**6` = `100_000_000_000`.
- The user target is **$100,000**. The house mint is **1e18 apUSD** = `10**24` raw.
- `Faucet.drip` and `Faucet.mintTo` are both **operator-only**. The operator is the `admin` address the deployment script already receives.
- Backend tests: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`. **NEVER source `.env` into pytest** — conftest setdefaults get defeated and live-sync tests hang.
- UI verify chain: `npx vitest run && npm run typecheck && npm run lint && npm run build`, run from `ui/`. Lint must stay at **0 errors** (3 pre-existing react-refresh warnings are expected).
- Contract tests: `cd vendor/ctf-exchange && forge test --match-path "src/dev/test/Faucet.t.sol"`.
- Commit messages carry **no AI attribution trailer**. Stage files by name; never `git add -A`.

---

### Task 1: Faucet — operator gate and an arbitrary mint

**Files:**
- Modify: `vendor/ctf-exchange/src/dev/mocks/Faucet.sol`
- Create: `vendor/ctf-exchange/src/dev/test/Faucet.t.sol`
- Modify: `vendor/ctf-exchange/src/exchange/scripts/ExchangeDeployment.s.sol:57`
- Modify: `agentpit/onchain/abi/faucet.json` (regenerated, not hand-edited)

**Interfaces:**
- Produces: `Faucet(AgentpitUSD _token, uint256 _amount, address _operator)`; `drip(address to)` and `mintTo(address to, uint256 value)`, both reverting with `"only operator"` for anyone else.

- [ ] **Step 1: Write the failing test**

Create `vendor/ctf-exchange/src/dev/test/Faucet.t.sol`:

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.15;

import {Test} from "forge-std/Test.sol";
import {AgentpitUSD} from "dev/mocks/AgentpitUSD.sol";
import {Faucet} from "dev/mocks/Faucet.sol";

contract FaucetTest is Test {
    AgentpitUSD usd;
    Faucet faucet;

    address operator = address(0xA11CE);
    address stranger = address(0xB0B);
    address user = address(0xCAFE);

    uint256 constant GRANT = 100_000 * 10 ** 6;   // $100k, 6 decimals

    function setUp() public {
        usd = new AgentpitUSD(address(this));
        faucet = new Faucet(usd, GRANT, operator);
        usd.setMinter(address(faucet));
    }

    function test_drip_mints_exactly_the_grant() public {
        vm.prank(operator);
        faucet.drip(user);
        assertEq(usd.balanceOf(user), GRANT);
    }

    /// The regression that matters: drip is permissionless today, which is a
    /// way around the daily top-up limit once balances are capped.
    function test_drip_reverts_for_non_operator() public {
        vm.prank(stranger);
        vm.expectRevert("only operator");
        faucet.drip(user);
    }

    function test_mintTo_mints_an_arbitrary_amount() public {
        vm.prank(operator);
        faucet.mintTo(user, 10 ** 24);
        assertEq(usd.balanceOf(user), 10 ** 24);
    }

    function test_mintTo_reverts_for_non_operator() public {
        vm.prank(stranger);
        vm.expectRevert("only operator");
        faucet.mintTo(user, 1);
    }
}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd vendor/ctf-exchange && forge test --match-path "src/dev/test/Faucet.t.sol"
```

Expected: compilation failure — `Faucet` has a two-argument constructor and no `mintTo`.

- [ ] **Step 3: Implement**

Replace the body of `vendor/ctf-exchange/src/dev/mocks/Faucet.sol`:

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.15;

import {AgentpitUSD} from "dev/mocks/AgentpitUSD.sol";

/// @title Faucet
/// @notice Mints AgentpitUSD for the agentpit backend: a fixed signup grant via
///         `drip`, or an arbitrary amount via `mintTo`.
/// @dev Holds the minter role on AgentpitUSD. Both entry points are restricted
///      to the operator. `drip` used to be permissionless, which was harmless
///      while the grant was astronomically large and nobody wanted a second
///      one — but once user balances are capped, an open mint is a way around
///      the cap, so the limit belongs here rather than in network topology.
contract Faucet {
    AgentpitUSD public immutable token;
    uint256 public immutable amount;
    address public immutable operator;

    event Dripped(address indexed to, uint256 amount);

    modifier onlyOperator() {
        require(msg.sender == operator, "only operator");
        _;
    }

    constructor(AgentpitUSD _token, uint256 _amount, address _operator) {
        token = _token;
        amount = _amount;
        operator = _operator;
    }

    /// @notice Mint the fixed signup grant to `to`.
    function drip(address to) external onlyOperator {
        token.mint(to, amount);
        emit Dripped(to, amount);
    }

    /// @notice Mint an arbitrary `value` to `to` — house funding and top-ups.
    function mintTo(address to, uint256 value) external onlyOperator {
        token.mint(to, value);
        emit Dripped(to, value);
    }
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd vendor/ctf-exchange && forge test --match-path "src/dev/test/Faucet.t.sol" -vv
```

Expected: 4 passed.

- [ ] **Step 5: Pass the operator through the deployment script**

In `vendor/ctf-exchange/src/exchange/scripts/ExchangeDeployment.s.sol`, the faucet is constructed at step 2. `admin` is already a parameter of `deployAgentpitStack`, so no signature change is needed:

```solidity
        // 2. Deploy Faucet pointing at the token, operated by the backend admin.
        Faucet faucetContract = new Faucet(usdToken, signupGrantRaw, admin);
```

- [ ] **Step 6: Verify the whole contract suite still compiles and passes**

```bash
cd vendor/ctf-exchange && forge build && forge test
```

Expected: build succeeds; the pre-existing exchange tests stay green. This change touches only the dev mock, so any failure here is a real regression.

- [ ] **Step 7: Regenerate the checked-in ABI**

`agentpit/onchain/contracts.py` loads `agentpit/onchain/abi/faucet.json` — a committed file, not a build artefact — so it must be refreshed or `mintTo` will be invisible to web3:

```bash
cd vendor/ctf-exchange && forge inspect Faucet abi --json > /tmp/faucet-abi.json
cd /Users/yavorsky/dev/agentpit && python3 -m json.tool /tmp/faucet-abi.json > agentpit/onchain/abi/faucet.json
```

Confirm it took:

```bash
grep -c mintTo agentpit/onchain/abi/faucet.json    # expect >= 1
```

- [ ] **Step 8: Commit**

```bash
cd /Users/yavorsky/dev/agentpit
git add vendor/ctf-exchange/src/dev/mocks/Faucet.sol \
        vendor/ctf-exchange/src/dev/test/Faucet.t.sol \
        vendor/ctf-exchange/src/exchange/scripts/ExchangeDeployment.s.sol \
        agentpit/onchain/abi/faucet.json
git commit -m "feat(contracts): operator-gated faucet with an arbitrary mint

drip() takes no amount and the minter role cannot be rotated, so the signup
grant was only re-sizable by redeploying — and one drip amount cannot serve
both a user and the house. mintTo covers both, and drip becomes operator-only:
permissionless minting is harmless at a quadrillion and a way around the daily
limit once balances are capped."
```

---

### Task 2: `OnchainAdmin.mint_to` and the two amounts

**Files:**
- Modify: `agentpit/onchain/admin.py:25-27`
- Modify: `agentpit/config.py:172-177`
- Modify: `tests/test_config_liquidity.py`

**Interfaces:**
- Consumes: `Faucet.mintTo(address,uint256)` from Task 1.
- Produces: `OnchainAdmin.mint_to(recipient: str, amount_raw: int, *, timeout: int = 30) -> TxReceipt`; `Settings.paper_balance_target_raw: int`; `Settings.house_mint_raw: int`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config_liquidity.py`, inside the defaults test:

```python
    assert s.paper_balance_target_raw == 100_000_000_000        # $100k, 6dp
    assert s.house_mint_raw == 10**24                           # 1e18 apUSD
    assert s.topup_cooldown_seconds == 86_400
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_config_liquidity.py -q
```

Expected: `AttributeError: 'Settings' object has no attribute 'paper_balance_target_raw'`.

- [ ] **Step 3: Add the settings**

In `agentpit/config.py`, replace the `liquidity_funding_drips` field (it is superseded — the house is one mint now, not N repetitions of a user's grant) with:

```python
    # apUSD is 6-decimal, so every figure here is raw. The house needs ~150bn
    # to seed every mirrored market; 1e18 is headroom chosen deliberately.
    house_mint_raw: int = Field(
        default=10**24, validation_alias="AGENTPIT_HOUSE_MINT_RAW"
    )
    # What a user's paper balance is restored to. $100,000.
    paper_balance_target_raw: int = Field(
        default=100_000_000_000, validation_alias="AGENTPIT_PAPER_BALANCE_TARGET_RAW"
    )
    topup_cooldown_seconds: int = Field(
        default=86_400, validation_alias="AGENTPIT_TOPUP_COOLDOWN_SECONDS"
    )
```

- [ ] **Step 4: Add `mint_to` beside `faucet_drip`**

In `agentpit/onchain/admin.py`, directly after `faucet_drip`:

```python
    def mint_to(
        self, recipient: str, amount_raw: int, *, timeout: int = 30
    ) -> TxReceipt:
        """Mint an arbitrary amount of apUSD — house funding and top-ups.

        `faucet_drip` mints the fixed signup grant; this is the same faucet's
        unrestricted entry point, and like drip it is operator-only on chain.
        """
        fn = self._contracts.faucet.functions.mintTo(
            Web3.to_checksum_address(recipient), amount_raw
        )
        return send_admin_tx(self._client, fn, timeout=timeout)
```

- [ ] **Step 5: Run the config test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_config_liquidity.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the whole backend suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: all green. Removing `liquidity_funding_drips` will break anything that referenced it — Task 3 fixes the one real caller, so if a test fails here naming that setting, note it and continue; it is expected to go green at the end of Task 3.

- [ ] **Step 7: Commit**

```bash
git add agentpit/config.py agentpit/onchain/admin.py tests/test_config_liquidity.py
git commit -m "feat(onchain): mint_to, plus the house and user balance amounts

liquidity_funding_drips goes with them: the house is now one mint of a stated
size rather than N repetitions of whatever a user happens to be granted."
```

---

### Task 3: The house is one mint

**Files:**
- Modify: `agentpit/liquidity/house_accounts.py:78-84`
- Modify: `tests/liquidity/test_house_gas.py`

**Interfaces:**
- Consumes: `OnchainAdmin.mint_to`, `Settings.house_mint_raw` from Task 2.

- [ ] **Step 1: Write the failing test**

Append to `tests/liquidity/test_house_gas.py`:

```python
def test_house_is_funded_by_one_mint_not_repeated_drips():
    """One mint of a stated size — not N repetitions of a user's grant.

    The faucet's drip amount is the USER grant now ($100k). Funding the house
    that way would need ten trillion transactions, which is the whole reason
    mintTo exists.
    """
    from agentpit.config import Settings
    from agentpit.liquidity.house_accounts import HouseAccountProvisioner

    calls = []

    class _Onchain:
        def faucet_drip(self, address, *, timeout=30):
            calls.append(("drip", address))

        def mint_to(self, address, amount_raw, *, timeout=30):
            calls.append(("mint", address, amount_raw))

        def fund_gas(self, address, value_wei, *, timeout=30):
            calls.append(("gas", address))

        def grant_user_approvals(self, account, *, timeout=30):
            calls.append(("approvals",))

    class _Key:
        address = "0x" + "11" * 20

    settings = Settings()
    prov = HouseAccountProvisioner(None, _Onchain(), settings)
    prov._fund(_Key())

    mints = [c for c in calls if c[0] == "mint"]
    assert len(mints) == 1
    assert mints[0][2] == settings.house_mint_raw
    assert not [c for c in calls if c[0] == "drip"]
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest tests/liquidity/test_house_gas.py -q
```

Expected: FAIL — `_fund` still loops `faucet_drip`, and `liquidity_funding_drips` no longer exists after Task 2, so it may raise `AttributeError` instead. Either failure is the expected red.

- [ ] **Step 3: Implement**

In `agentpit/liquidity/house_accounts.py`, replace `_fund`:

```python
    def _fund(self, acct) -> None:
        timeout = self._settings.tx_confirmations_timeout_s
        self._onchain.mint_to(
            acct.address, self._settings.house_mint_raw, timeout=timeout
        )
        self._onchain.fund_gas(
            acct.address, self._settings.signup_gas_grant_wei, timeout=timeout
        )
        self._onchain.grant_user_approvals(acct, timeout=timeout)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/bin/python -m pytest tests/liquidity/test_house_gas.py -q
```

Expected: PASS.

- [ ] **Step 5: Run the whole backend suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: all green, including anything Task 2 left red.

- [ ] **Step 6: Commit**

```bash
git add agentpit/liquidity/house_accounts.py tests/liquidity/test_house_gas.py
git commit -m "feat(liquidity): fund the house with a single mint

The faucet's drip is the user grant now, so drip-based house funding would need
ten trillion transactions."
```

---

### Task 4: Top-up — arithmetic, cooldown, and the column

**Files:**
- Create: `agentpit/services/balance_service.py`
- Modify: `agentpit/db/table_create.py:118-125`
- Modify: `agentpit/db/table_read.py` (add `get_last_topup_at`)
- Modify: `agentpit/db/table_write.py` (add `set_last_topup_at`)
- Create: `tests/test_balance_topup.py`

**Interfaces:**
- Consumes: `Settings.paper_balance_target_raw`, `Settings.topup_cooldown_seconds`, `OnchainAdmin.mint_to`, `OnchainAdmin.usd_balance` from Task 2.
- Produces: `topup_amount_raw(balance_raw: int, target_raw: int) -> int`; `next_allowed_at(last_topup_at: int | None, cooldown_seconds: int) -> int`; `BalanceService.top_up(user: User, now: int) -> TopUpResult`, where `TopUpResult` is a pydantic model with `balance_raw: int`, `minted_raw: int`, `next_allowed_at: int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_balance_topup.py`:

```python
from agentpit.services.balance_service import next_allowed_at, topup_amount_raw

TARGET = 100_000_000_000        # $100k, 6dp
DAY = 86_400


def test_below_target_mints_the_difference():
    assert topup_amount_raw(30_000_000_000, TARGET) == 70_000_000_000


def test_at_target_mints_nothing():
    assert topup_amount_raw(TARGET, TARGET) == 0


def test_above_target_mints_nothing_rather_than_clawing_back():
    """Someone who traded past the target has nothing to restore. That is a
    no-op, not an error, and certainly not a negative mint."""
    assert topup_amount_raw(TARGET + 1, TARGET) == 0


def test_the_result_never_exceeds_the_target():
    for balance in (0, 1, TARGET // 2, TARGET - 1, TARGET, TARGET * 3):
        assert balance + topup_amount_raw(balance, TARGET) <= max(balance, TARGET)


def test_first_top_up_is_allowed_immediately():
    assert next_allowed_at(None, DAY) == 0


def test_a_second_top_up_waits_a_day():
    assert next_allowed_at(1_000_000, DAY) == 1_000_000 + DAY
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_balance_topup.py -q
```

Expected: `ModuleNotFoundError: No module named 'agentpit.services.balance_service'`.

- [ ] **Step 3: Write the service**

Create `agentpit/services/balance_service.py`:

```python
"""Restoring a user's paper balance to the target, at most once a day."""
from pydantic import BaseModel

from agentpit.config import Settings
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.onchain.admin import OnchainAdmin


class TopUpResult(BaseModel):
    balance_raw: int
    minted_raw: int
    next_allowed_at: int


def topup_amount_raw(balance_raw: int, target_raw: int) -> int:
    """How much to mint so the account lands exactly on the target.

    Zero when the balance is already there or beyond: this restores a demo
    balance, it does not hand out a fixed sum. A flat grant would pay more to
    someone who lost everything than to someone who did well.
    """
    return max(0, target_raw - balance_raw)


def next_allowed_at(last_topup_at: int | None, cooldown_seconds: int) -> int:
    """Unix time when the next top-up becomes allowed; 0 when it already is."""
    if last_topup_at is None:
        return 0
    return last_topup_at + cooldown_seconds


class BalanceService:
    def __init__(self, db: DbSession, onchain: OnchainAdmin, settings: Settings):
        self._db = db
        self._onchain = onchain
        self._settings = settings

    def top_up(self, user: User, now: int) -> TopUpResult:
        with self._db.read() as conn:
            last = TableRead.get_last_topup_at(conn, user.user_id)

        allowed_at = next_allowed_at(last, self._settings.topup_cooldown_seconds)
        balance = self._onchain.usd_balance(user.eth_address)
        if now < allowed_at:
            return TopUpResult(
                balance_raw=balance, minted_raw=0, next_allowed_at=allowed_at
            )

        minted = topup_amount_raw(balance, self._settings.paper_balance_target_raw)
        if minted == 0:
            # Nothing to restore. Not a failure, and it must not start the
            # cooldown — otherwise checking while ahead costs you the day.
            return TopUpResult(
                balance_raw=balance, minted_raw=0, next_allowed_at=allowed_at
            )

        self._onchain.mint_to(
            user.eth_address,
            minted,
            timeout=self._settings.tx_confirmations_timeout_s,
        )
        with self._db.write() as conn:
            TableWrite.set_last_topup_at(conn, user.user_id, now)
        return TopUpResult(
            balance_raw=balance + minted,
            minted_raw=minted,
            next_allowed_at=now + self._settings.topup_cooldown_seconds,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_balance_topup.py -q
```

Expected: 6 passed.

- [ ] **Step 5: Add the column and its accessors**

In `agentpit/db/table_create.py`, add to the `additions` list in `_migrate_users_table`:

```python
            ("LAST_TOPUP_AT", "BIGINT"),
```

In `agentpit/db/table_read.py`, beside the other user reads:

```python
    @staticmethod
    def get_last_topup_at(db: psycopg.Connection, user_id: str) -> int | None:
        row = db.execute(
            "SELECT LAST_TOPUP_AT FROM users WHERE USER_ID = %s", (user_id,)
        ).fetchone()
        return row["LAST_TOPUP_AT"] if row else None
```

In `agentpit/db/table_write.py`:

```python
    @staticmethod
    def set_last_topup_at(db: psycopg.Connection, user_id: str, at: int) -> None:
        db.execute(
            "UPDATE users SET LAST_TOPUP_AT = %s WHERE USER_ID = %s", (at, user_id)
        )
```

- [ ] **Step 6: Add a round-trip test for the column**

Append to `tests/test_balance_topup.py`:

```python
def test_last_topup_at_round_trips():
    from tests.conftest import fresh_test_conn      # same helper the other DB tests use
    from agentpit.db.table_read import TableRead
    from agentpit.db.table_write import TableWrite

    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="topup@example.com", password_hash="x", handle=None
    )
    assert TableRead.get_last_topup_at(conn, user_id) is None
    TableWrite.set_last_topup_at(conn, user_id, 1_700_000_000)
    assert TableRead.get_last_topup_at(conn, user_id) == 1_700_000_000
    conn.close()
```

If `fresh_test_conn` is not importable from `tests.conftest`, copy the import used at the top of `tests/test_event_volume.py` — that file uses the same helper.

- [ ] **Step 7: Run the whole backend suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add agentpit/services/balance_service.py agentpit/db/table_create.py \
        agentpit/db/table_read.py agentpit/db/table_write.py tests/test_balance_topup.py
git commit -m "feat(balance): restore a paper balance to the target, once a day

Tops up TO the target rather than granting a fixed sum — a flat grant would pay
more to someone who lost everything than to someone who did well. Being already
above the target is a no-op that does not consume the day's allowance."
```

---

### Task 5: The top-up endpoint

**Files:**
- Modify: `agentpit/api/deps.py` (add `BalanceServiceDep`)
- Modify: `agentpit/api/routes/users.py`
- Create: `tests/api/test_topup.py`

**Interfaces:**
- Consumes: `BalanceService.top_up`, `TopUpResult` from Task 4.
- Produces: `POST /me/top-up` returning `{"balance": "<raw>", "minted": "<raw>", "nextAllowedAt": <unix>}`.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_topup.py`:

```python
from fastapi.testclient import TestClient

from agentpit.api.main import app


def test_top_up_requires_auth():
    with TestClient(app) as client:
        assert client.post("/me/top-up").status_code in (401, 403)


def test_top_up_route_exists():
    """Registered at all — the route table is the thing under test here; the
    arithmetic is covered by tests/test_balance_topup.py."""
    paths = {r.path for r in app.routes}
    assert "/me/top-up" in paths
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest tests/api/test_topup.py -q
```

Expected: FAIL — `/me/top-up` is not in the route table.

- [ ] **Step 3: Wire the dependency**

In `agentpit/api/deps.py`, following the shape of `get_account_service`:

```python
def get_balance_service(
    db: SessionDep, onchain: OnchainAdminDep, settings: SettingsDep
) -> BalanceService:
    return BalanceService(db, onchain, settings)


BalanceServiceDep = Annotated[BalanceService, Depends(get_balance_service)]
```

Match the existing parameter names in that file — if `get_account_service` takes its dependencies differently, follow it rather than this sketch.

- [ ] **Step 4: Add the route**

In `agentpit/api/routes/users.py`:

```python
@router.post("/me/top-up", response_model=TopUpWire)
def top_up_balance(user: CurrentUserDep, service: BalanceServiceDep) -> TopUpWire:
    """Restore the paper balance to the target, at most once a day.

    Returns 200 with `minted: "0"` when the cooldown is still running or the
    balance is already at the target — the button shows the reason, and neither
    case is an error worth an exception.
    """
    result = service.top_up(user, int(time.time()))
    return TopUpWire(
        balance=str(result.balance_raw),
        minted=str(result.minted_raw),
        nextAllowedAt=result.next_allowed_at,
    )
```

Define `TopUpWire` beside the other wire models used by this router (amounts as strings, matching how `/balance-allowance` already returns `{"balance": "<raw>"}`):

```python
class TopUpWire(BaseModel):
    balance: str
    minted: str
    nextAllowedAt: int
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
.venv/bin/python -m pytest tests/api/test_topup.py -q
```

Expected: 2 passed.

- [ ] **Step 6: Run the whole backend suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add agentpit/api/deps.py agentpit/api/routes/users.py tests/api/test_topup.py
git commit -m "feat(api): POST /me/top-up

Returns 200 with minted 0 when the cooldown is running or the balance is
already at target — both are states the button explains, not errors."
```

---

### Task 6: The button

**Files:**
- Modify: `ui/src/api/portfolio.ts`
- Modify: `ui/src/pages/ProfilePage.tsx:177`
- Create: `ui/src/api/topUp.test.ts`

**Interfaces:**
- Consumes: `POST /me/top-up` from Task 5.
- Produces: `useTopUp()` mutation; `topUpLabel(nextAllowedAt: number, now: number): string`.

- [ ] **Step 1: Write the failing test**

Create `ui/src/api/topUp.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { topUpLabel } from "./portfolio";

const NOW = 1_700_000_000;

describe("topUpLabel", () => {
  it("offers the top-up when the cooldown has passed", () => {
    expect(topUpLabel(NOW - 1, NOW)).toBe("Top up to $100k");
  });

  it("counts down in hours while the cooldown runs", () => {
    expect(topUpLabel(NOW + 3 * 3600, NOW)).toBe("Available in 3h");
  });

  it("rounds a part-hour up rather than showing 0h", () => {
    expect(topUpLabel(NOW + 60, NOW)).toBe("Available in 1h");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ui && npx vitest run src/api/topUp.test.ts
```

Expected: FAIL — `topUpLabel` is not exported.

- [ ] **Step 3: Implement the hook and the label**

Append to `ui/src/api/portfolio.ts`:

```ts
export interface TopUpResult {
  balance: string;
  minted: string;
  nextAllowedAt: number;
}

/** What the button says. A part-hour rounds UP: "Available in 0h" reads as a
 *  bug, and rounding down would invite a click that fails. */
export function topUpLabel(nextAllowedAt: number, now: number): string {
  if (now >= nextAllowedAt) return "Top up to $100k";
  return `Available in ${Math.ceil((nextAllowedAt - now) / 3600)}h`;
}

export function useTopUp() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<TopUpResult>("/me/top-up", { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["balance-allowance", "COLLATERAL"],
      });
    },
  });
}
```

Add `useMutation` and `useQueryClient` to the existing `@tanstack/react-query` import in that file if they are not already there.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ui && npx vitest run src/api/topUp.test.ts
```

Expected: 3 passed.

- [ ] **Step 5: Put the button on the profile**

In `ui/src/pages/ProfilePage.tsx`, beside the balance stat at line 177, add:

```tsx
<Button
  size="sm"
  variant="outline"
  disabled={topUp.isPending || now < nextAllowedAt}
  onClick={() => topUp.mutate()}
>
  {topUp.isPending ? "Topping up…" : topUpLabel(nextAllowedAt, now)}
</Button>
```

with, near the other hooks in that component:

```tsx
const topUp = useTopUp();
const now = Math.floor(Date.now() / 1000);
const nextAllowedAt = topUp.data?.nextAllowedAt ?? 0;
```

- [ ] **Step 6: Run the full UI chain**

```bash
cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build
```

Expected: all tests pass, typecheck clean, **0 lint errors** (3 pre-existing warnings), build succeeds.

- [ ] **Step 7: Commit**

```bash
git add ui/src/api/portfolio.ts ui/src/api/topUp.test.ts ui/src/pages/ProfilePage.tsx
git commit -m "feat(ui): top-up button on the profile

Disabled with an hours countdown while the daily cooldown runs. Part-hours
round up: 'Available in 0h' reads as a bug, and rounding down invites a click
that fails."
```

---

### Task 7: The signup grant becomes $100k, and the redeploy runbook

**Files:**
- Modify: `scripts/deploy_exchange.sh:17-19`
- Modify: `deploy/env.prod.example`
- Modify: `docs/launch-plan.md`

- [ ] **Step 1: Change the grant**

In `scripts/deploy_exchange.sh`, replace the comment and default at lines 17-19:

```bash
# Faucet drip amount = the USER signup grant: $100,000 apUSD (6 decimals).
# The house is funded separately by Faucet.mintTo, so this figure no longer has
# to serve both.
SIGNUP_GRANT_RAW="${SIGNUP_GRANT_RAW:-100000000000}"
```

- [ ] **Step 2: Document the two knobs in the prod example**

In `deploy/env.prod.example`, under the product config block:

```bash
# Paper balance restored by the profile's top-up button, raw (6 decimals).
AGENTPIT_PAPER_BALANCE_TARGET_RAW=100000000000
AGENTPIT_TOPUP_COOLDOWN_SECONDS=86400
```

- [ ] **Step 3: Verify the whole suite one last time**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build
cd vendor/ctf-exchange && forge test
```

Expected: all three green.

- [ ] **Step 4: Commit**

```bash
git add scripts/deploy_exchange.sh deploy/env.prod.example docs/launch-plan.md
git commit -m "feat(deploy): signup grant is \$100k

The house no longer draws from this figure, so it can finally be the user
number it was always meant to be."
```

- [ ] **Step 5: Redeploy — local first**

New contracts mean a new CTF, new ERC-1155 token ids, and a database full of stale references. **This destroys every position, order and trade.** Do it locally first and confirm the flow end to end before touching production.

```bash
# stop the API, then:
pkill -f "anvil --load-state" || true
rm -f .anvil-state.json
nohup bash scripts/run_node.sh > /tmp/anvil.log 2>&1 &
sleep 5
bash scripts/deploy_exchange.sh
bash scripts/db_reset.sh agentpit
# start the API; it rebuilds the schema, re-syncs markets, re-provisions the house
```

Then confirm, in order:

```bash
# a fresh account gets exactly $100k
curl -s -X POST localhost:8000/register -H 'Content-Type: application/json' \
  -d '{"email":"grant-check@example.com","password":"grant-check-pw"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['user']['eth_address'])"
# then GET /balance-allowance?asset_type=COLLATERAL with that key → "100000000000"

# the house got its mint
# (house address from: SELECT ETH_ADDRESS FROM users WHERE IS_BOT = 1)
```

- [ ] **Step 6: Redeploy — production**

**Confirm with the user before running this.** Same sequence inside the compose stack, and it wipes production's positions and the Arena's history:

```bash
ssh root@23.88.62.130
cd /root/dev/agentpit
git pull
docker compose -f deploy/docker-compose.prod.yml --env-file .env down api
docker volume rm agentpit_agentpit_anvil        # fresh chain
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d anvil
docker compose -f deploy/docker-compose.prod.yml --env-file .env run --rm chain-init
# reset the database, then bring the API back
docker compose -f deploy/docker-compose.prod.yml --env-file .env build api caddy
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d api caddy
```

Verify afterwards: markets re-synced, a fresh registration lands on exactly $100k, the house holds `house_mint_raw`, and the top-up button appears on the profile.

---

## Self-review

**Spec coverage.** Operator gate and `mintTo` → Task 1. The two amounts and `mint_to` → Task 2. One house mint, `liquidity_funding_drips` removed → Task 3. Top-up to the target, the no-op-when-ahead rule, the 24h limit on a new column → Task 4. The endpoint → Task 5. The button with its countdown → Task 6. `SIGNUP_GRANT_RAW` and the redeploy → Task 7. "No treasury" needs no task: it is the design not creating one.

**Placeholders.** None: every step carries the code or command it needs. Two steps deliberately say "match the existing shape in that file" (`deps.py` wiring, the `fresh_test_conn` import) because the surrounding convention is the requirement, and both name the file to copy from.

**Type consistency.** `topup_amount_raw`, `next_allowed_at`, `TopUpResult{balance_raw, minted_raw, next_allowed_at}`, `TopUpWire{balance, minted, nextAllowedAt}`, `topUpLabel(nextAllowedAt, now)` — raw ints inside, strings on the wire for amounts, matching `/balance-allowance`. `house_mint_raw` and `paper_balance_target_raw` are used under those names in Tasks 3, 4 and 7.
