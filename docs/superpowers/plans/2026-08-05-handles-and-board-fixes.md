# Everyone gets a name, and the board tells the truth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every account a generated two-word handle, drop the house-agent
marking, make the deposit reset reach API-key-only bots, wire snapshot
retention, rewrite the two board queries so their indexes apply, and bring the
equity sparkline back to the board.

**Architecture:** Five defects and one product gap, all inside the leaderboard
that shipped on 2026-08-04. Handle generation is a new pure module in
`agentpit/domain/` called from `AuthService.register`. The deposit reset moves
from `BalanceService.top_up` (a path the flagship bots never take) into
`LeaderboardService.take_snapshot` (a timer pass that reaches every trading
account regardless of how it authenticates). Retention and the query rewrite are
one-line and one-query changes respectively. The sparkline needs a new
`GET /leaderboard/{address}/history` endpoint over `account_snapshots`; the
drawing code was never deleted and gets reconnected rather than rewritten.

**Tech Stack:** Python 3.13 / FastAPI / psycopg 3 / Postgres; React 19 +
TypeScript + Vite + TanStack Query + Tailwind; pytest and vitest.

**Spec:** `docs/superpowers/specs/2026-08-04-handles-and-board-fixes-design.md`

## Global Constraints

- **Branch is `mvp`.** Never commit to `main`. Verify with `git branch --show-current` before the first commit.
- **Never `git add -A` or `git add .`** — stage only the files named in the step.
- **No `Co-Authored-By` trailer and no AI attribution of any kind** in commit messages.
- **Handles are validated `[a-zA-Z0-9_]{1,15}`** in both `RegisterRequest` and `UpdateHandleRequest`. 15 characters is a hard ceiling; every generated handle must satisfy that regex.
- **apUSD has 6 decimals.** $100,000 is `100000000000`. Money crosses the wire as base-unit **integer strings**, never floats — `capital`, `earned` are strings; `returnPct` is a float percentage.
- **No email address may appear in any public payload** — not as a field, not as a fallback, not derived.
- **No new Python or npm dependencies.** The word lists ship in the repository; `/usr/share/dict` is not reliably present in the API's container image.
- **Backend tests:** `.venv/bin/python -m pytest tests -q --ignore=tests/onchain` from the repo root. **NEVER source `.env`** — the conftest `setdefault`s get defeated and the live Polymarket sync starts, which turns a 40-second run into a 15-minute one.
- **UI tests:** `npx vitest run && npm run typecheck && npm run lint && npm run build`, all from `ui/`.
- Anvil and the deployed exchange must already be running for `tests/api/test_auth.py` (register hits the faucet). Do not start or restart them — ask if they appear to be down.
- Baseline before this plan: backend **424 passed**, UI vitest green.

---

## File Structure

| file | responsibility | task |
|---|---|---|
| `agentpit/domain/handles.py` (new) | the two word lists and the pure handle-picking logic | 1 |
| `tests/test_handles.py` (new) | cross-product validity, retry, suffix fallback | 1 |
| `agentpit/db/table_read.py` | `handle_taken`, `list_account_snapshots`, the two rewritten board queries | 1, 5, 6 |
| `agentpit/services/auth_service.py` | calls `pick_handle` when the caller supplied none | 1 |
| `agentpit/config.py` | drop `house_agent_handles` | 2 |
| `agentpit/services/leaderboard_service.py` | drop `is_house_agent`; the wipe check; `prune_old`; `compute_earned_raw`/`compute_return_pct`; `downsample` | 2, 3, 4, 6 |
| `agentpit/api/routes/leaderboard.py` | drop `isHouseAgent`; add the history endpoint | 2, 6 |
| `agentpit/api/app.py` | pass retention into the leaderboard loop | 4 |
| `ui/src/api/leaderboard.ts` | drop `isHouseAgent`/`houseAgentHref`; add the history query + sample mapping | 2, 7 |
| `ui/src/pages/AgentArenaPage.tsx` | drop the badge and the row link; add the trend column | 2, 7 |
| `docs/launch-plan.md` | remove the "labelled as ours" line it no longer describes | 2 |

---

### Task 1: A generated handle for every account

Nobody fills in the handle field. `display_name` falls back to a truncated
address, so today the board would render as a column of `0x7aD8…0c31`. Every
account gets a name at registration; `PATCH /me` keeps working, so it is a
starting point rather than an assignment.

**Files:**
- Create: `agentpit/domain/handles.py`
- Create: `tests/test_handles.py`
- Modify: `agentpit/db/table_read.py` (add `handle_taken` next to `get_user_by_email`, ~line 229)
- Modify: `agentpit/services/auth_service.py:40-50` (the `register` transaction)
- Test: `tests/test_handles.py`, `tests/api/test_auth.py`

**Interfaces:**
- Produces: `agentpit.domain.handles.pick_handle(taken: Callable[[str], bool], rng=random) -> str`; `agentpit.domain.handles.generate_handle(rng, attempt: int) -> str`; `ADJECTIVES: tuple[str, ...]`; `NOUNS: tuple[str, ...]`; `MAX_HANDLE_LEN = 15`; `PLAIN_ATTEMPTS = 4`; `MAX_ATTEMPTS = 6`.
- Produces: `TableRead.handle_taken(db: psycopg.Connection, handle: str) -> bool`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing test**

Create `tests/test_handles.py`:

```python
"""Generated handles: the 15-character ceiling is the binding constraint."""
import random
import re

from agentpit.db.table_write import TableWrite
from agentpit.db.table_read import TableRead
from agentpit.domain.handles import (
    ADJECTIVES,
    MAX_ATTEMPTS,
    NOUNS,
    PLAIN_ATTEMPTS,
    generate_handle,
    pick_handle,
)
from tests.db_helpers import fresh_test_conn

HANDLE_RE = re.compile(r"[a-zA-Z0-9_]{1,15}")


def test_every_possible_pair_is_a_valid_handle():
    """Asserted over the WHOLE cross product, not a sample: a single overlong
    word would otherwise sit in the list for months and surface as a 422 on
    somebody's signup. 120 x 120 is 14,400 pairs and runs in milliseconds."""
    assert len(ADJECTIVES) >= 100 and len(NOUNS) >= 100
    for a in ADJECTIVES:
        for n in NOUNS:
            pair = a + n
            assert HANDLE_RE.fullmatch(pair), pair


def test_every_suffixed_pair_is_also_a_valid_handle():
    """The suffix tier is the part that can overflow 15 characters, so it gets
    the same exhaustive treatment. The longest suffix is four digits."""
    rng = random.Random(7)
    for a in ADJECTIVES:
        for n in NOUNS:
            longest = (a + n)[: 15 - 4] + "9999"
            assert HANDLE_RE.fullmatch(longest), longest
    # And the real generator, on a suffix-tier attempt, agrees.
    handle = generate_handle(rng, attempt=PLAIN_ATTEMPTS)
    assert HANDLE_RE.fullmatch(handle)
    assert handle[-4:].isdigit()


def test_plain_attempts_are_two_words_with_no_digits():
    rng = random.Random(1)
    handle = generate_handle(rng, attempt=0)
    assert HANDLE_RE.fullmatch(handle)
    assert not any(c.isdigit() for c in handle)
    assert any(handle.startswith(a) for a in ADJECTIVES)


def test_pick_handle_returns_a_free_name():
    assert pick_handle(taken=lambda h: False, rng=random.Random(3))


def test_pick_handle_skips_taken_names():
    """A collision must not surface to the user. The first two candidates are
    claimed; the third is free and is what comes back."""
    seen: list[str] = []

    def taken(h: str) -> bool:
        seen.append(h)
        return len(seen) <= 2

    result = pick_handle(taken=taken, rng=random.Random(5))
    assert result == seen[-1]
    assert len(seen) == 3


def test_pick_handle_falls_back_to_a_numeric_suffix():
    """Once the plain space is exhausted the suffix tier takes over, which is
    what stops a busy instance from failing registrations outright."""
    result = pick_handle(
        taken=lambda h: not any(c.isdigit() for c in h),
        rng=random.Random(11),
    )
    assert result[-4:].isdigit()
    assert HANDLE_RE.fullmatch(result)


def test_pick_handle_gives_up_rather_than_looping_forever():
    attempts: list[str] = []

    def taken(h: str) -> bool:
        attempts.append(h)
        return True

    try:
        pick_handle(taken=taken, rng=random.Random(13))
        raise AssertionError("expected pick_handle to raise")
    except RuntimeError:
        pass
    assert len(attempts) == MAX_ATTEMPTS


def test_handle_taken_reads_the_unique_column():
    conn = fresh_test_conn()
    TableWrite.create_user(
        conn, email="taken@example.com", password_hash="x", handle="BoldRiver"
    )
    assert TableRead.handle_taken(conn, "BoldRiver") is True
    assert TableRead.handle_taken(conn, "MistyCove") is False
    conn.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_handles.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentpit.domain.handles'`

- [ ] **Step 3: Create the handles module**

Create `agentpit/domain/handles.py`:

```python
"""Two-word display handles, generated at registration.

Almost nobody sets a handle, and `display_name` falls back to a truncated
address -- so a leaderboard of accounts that never touched the field renders
as a column of hex strings. Every account gets a name it can change instead
of a blank it has to notice.

The 15-character limit that `RegisterRequest` and `UpdateHandleRequest`
enforce is the binding constraint. The lists are curated to seven characters
and under rather than filtered at generation time, so a pair that would not
validate cannot be produced in the first place -- and the test asserts that
over the whole cross product rather than a sample.

Two lists of 120 give 14,400 pairs with no dependency and no
`/usr/share/dict`, which the API's container image does not reliably have.
"""
import random
from typing import Callable

MAX_HANDLE_LEN = 15
"""Ceiling from the `[a-zA-Z0-9_]{1,15}` validator on both handle requests."""

PLAIN_ATTEMPTS = 4
"""Tries before falling back to a numeric suffix."""

MAX_ATTEMPTS = 6
"""Total tries. Bounded so a saturated name space fails loudly, not forever."""

_SUFFIX_DIGITS = 4

ADJECTIVES: tuple[str, ...] = (
    "Amber", "Ample", "Arctic", "Ashen", "Autumn", "Azure", "Balmy", "Bold",
    "Brave", "Brief", "Bright", "Brisk", "Calm", "Candid", "Chief", "Civic",
    "Clear", "Clever", "Copper", "Coral", "Cosmic", "Crisp", "Curious",
    "Daring", "Deep", "Dense", "Dewy", "Dizzy", "Dusty", "Eager", "Early",
    "Easy", "Eerie", "Elder", "Empty", "Even", "Exact", "Fair", "Fancy",
    "Fast", "Fine", "First", "Fleet", "Fluid", "Fond", "Frank", "Free",
    "Fresh", "Full", "Gentle", "Giant", "Glad", "Golden", "Grand", "Grave",
    "Great", "Green", "Grey", "Happy", "Hardy", "Hazy", "Hidden", "High",
    "Hollow", "Honest", "Humble", "Icy", "Idle", "Ivory", "Jolly", "Keen",
    "Kind", "Late", "Lean", "Light", "Little", "Live", "Lively", "Lone",
    "Long", "Loud", "Loyal", "Lucid", "Lucky", "Main", "Major", "Mellow",
    "Merry", "Mighty", "Mild", "Minor", "Misty", "Modest", "Mute", "Neat",
    "New", "Next", "Nimble", "Noble", "North", "Odd", "Olive", "Open",
    "Pale", "Patient", "Plain", "Polar", "Prime", "Proud", "Pure", "Quick",
    "Quiet", "Rapid", "Rare", "Ready", "Real", "Rich", "Right", "Rosy",
    "Round",
)

NOUNS: tuple[str, ...] = (
    "Anchor", "Apex", "Arbor", "Arrow", "Atlas", "Aurora", "Badge", "Basin",
    "Beacon", "Birch", "Bloom", "Bolt", "Bridge", "Brook", "Cable", "Cactus",
    "Canyon", "Cedar", "Chart", "Cliff", "Cloud", "Coast", "Comet", "Cove",
    "Crane", "Crest", "Crown", "Dawn", "Delta", "Dune", "Eagle", "Ember",
    "Falcon", "Fern", "Field", "Flame", "Flint", "Forest", "Fox", "Gale",
    "Garden", "Gate", "Glade", "Globe", "Grove", "Gulf", "Harbor", "Haven",
    "Hawk", "Hedge", "Heron", "Hill", "Ibex", "Inlet", "Iris", "Island",
    "Ivy", "Jade", "Jetty", "Key", "Lake", "Ledge", "Lemur", "Lily", "Lynx",
    "Maple", "Marsh", "Meadow", "Mesa", "Mint", "Moss", "Nest", "Nova",
    "Oak", "Oasis", "Ocean", "Onyx", "Orbit", "Orchid", "Otter", "Palm",
    "Peak", "Pearl", "Pebble", "Pine", "Plume", "Pond", "Quarry", "Quartz",
    "Quill", "Raven", "Reef", "Ridge", "River", "Robin", "Rock", "Sand",
    "Shore", "Signal", "Slate", "Snow", "Spark", "Spire", "Spring", "Spruce",
    "Star", "Stone", "Storm", "Stream", "Summit", "Swan", "Tide", "Timber",
    "Torch", "Trail", "Tulip", "Tundra", "Valley", "Vine", "Vista",
)


def generate_handle(rng, attempt: int = 0) -> str:
    """One candidate. `attempt` selects the tier, not the words.

    The first `PLAIN_ATTEMPTS` are a bare pair -- at most 13 characters, since
    the longest adjective is 7 and the longest noun 6. Later attempts append
    four digits and slice the pair to fit, which widens the space from 14,400
    to 144 million. The slice is what keeps the result inside 15 characters no
    matter which pair came up; it costs at most two characters off the noun
    and only on a tier reached after four collisions.
    """
    pair = rng.choice(ADJECTIVES) + rng.choice(NOUNS)
    if attempt < PLAIN_ATTEMPTS:
        return pair
    suffix = f"{rng.randrange(10**_SUFFIX_DIGITS):0{_SUFFIX_DIGITS}d}"
    return pair[: MAX_HANDLE_LEN - len(suffix)] + suffix


def pick_handle(taken: Callable[[str], bool], rng=random) -> str:
    """A handle nobody holds, or `RuntimeError` after `MAX_ATTEMPTS` tries.

    `taken` is a predicate rather than a connection so the retry logic can be
    tested without a database. Raising beats looping: a name space this large
    cannot exhaust six draws by chance, so six failures mean something else is
    wrong and a hung registration would hide it.
    """
    for attempt in range(MAX_ATTEMPTS):
        candidate = generate_handle(rng, attempt)
        if not taken(candidate):
            return candidate
    raise RuntimeError(
        f"no free handle after {MAX_ATTEMPTS} attempts"
    )
```

- [ ] **Step 4: Add the `handle_taken` reader**

In `agentpit/db/table_read.py`, directly after `get_user_by_email` (~line 235):

```python
    @staticmethod
    def handle_taken(db: psycopg.Connection, handle: str) -> bool:
        """Whether a handle is already claimed.

        `HANDLE TEXT UNIQUE` is the real guarantee; this is what lets
        registration pick a different name instead of surfacing a constraint
        violation as a 500.
        """
        row = db.execute(
            "SELECT 1 FROM users WHERE HANDLE = %s", (handle,)
        ).fetchone()
        return row is not None
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_handles.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 6: Commit the module**

```bash
git add agentpit/domain/handles.py agentpit/db/table_read.py tests/test_handles.py
git commit -m "feat(auth): two-word handles, generated and collision-safe"
```

- [ ] **Step 7: Write the failing registration test**

Append to `tests/api/test_auth.py`:

```python
def test_register_without_a_handle_generates_one():
    """A leaderboard of accounts that never set a handle is a column of hex
    strings. The generated name is a starting point -- PATCH /me still
    changes it -- but nobody starts nameless."""
    with TestClient(app) as client:
        resp = client.post(
            "/register",
            json={"email": "nameless@example.com", "password": "hunter22hunter22"},
        )
        assert resp.status_code == 200, resp.text
        handle = resp.json()["user"]["handle"]
        assert handle, "registration must not leave the handle blank"
        assert re.fullmatch(r"[a-zA-Z0-9_]{1,15}", handle), handle


def test_register_with_a_handle_keeps_it():
    """Generation fills a blank; it never overrides a choice."""
    with TestClient(app) as client:
        resp = client.post(
            "/register",
            json={
                "email": "chosen@example.com",
                "password": "hunter22hunter22",
                "handle": "chosen_name",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["user"]["handle"] == "chosen_name"
```

And add `import re` to the top of that file, below the module docstring.

- [ ] **Step 8: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_auth.py -q -k "generates_one or keeps_it"`
Expected: FAIL — `assert handle` fails, the generated handle is `None`.

- [ ] **Step 9: Wire generation into registration**

In `agentpit/services/auth_service.py`, replace the body of the first `with`
block in `register` (lines 41-50) with:

```python
        with self._db.write() as conn:
            if TableRead.get_user_by_email(conn, payload.email) is not None:
                raise UserAlreadyExistsError(payload.email)
            password_hash = hash_password(payload.password)
            # A supplied handle is a choice and is kept; a blank one is
            # filled. The availability check runs inside this transaction and
            # `HANDLE TEXT UNIQUE` is still the guarantee behind it -- two
            # signups landing on the same generated name in the same
            # millisecond would fail the insert rather than duplicate it,
            # which needs both a sub-millisecond overlap and the same 1-in-
            # 14,400 draw.
            handle = payload.handle or pick_handle(
                taken=lambda candidate: TableRead.handle_taken(conn, candidate)
            )
            user_id, acct, _api_key = TableWrite.create_user(
                conn,
                email=payload.email,
                password_hash=password_hash,
                handle=handle,
            )
```

And add the import beside the other domain imports at the top:

```python
from agentpit.domain.handles import pick_handle
```

- [ ] **Step 10: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/api/test_auth.py -q`
Expected: PASS, whole file.

- [ ] **Step 11: Run the whole backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS — 424 baseline + 10 new = 434.

- [ ] **Step 12: Commit**

```bash
git add agentpit/services/auth_service.py tests/api/test_auth.py
git commit -m "feat(auth): registration fills a blank handle instead of leaving one"
```

---

### Task 2: Nothing marks an agent as ours

An earlier draft badged our five personalities and keyed the badge to the
handle — a field its subject can edit, which is how official status became
claimable. It was never asked for. It goes, and with it the setting, the wire
field, the badge, and the row link that only house rows had.

**Files:**
- Modify: `agentpit/config.py:190-197` (remove `house_agent_handles`)
- Modify: `agentpit/services/leaderboard_service.py:24,154-155` (remove `is_house_agent`)
- Modify: `agentpit/api/routes/leaderboard.py:26,61` (remove `isHouseAgent`)
- Modify: `ui/src/api/leaderboard.ts:223,281-299` (remove `isHouseAgent`, `HOUSE_AGENT_IDS`, `houseAgentHref`)
- Modify: `ui/src/pages/AgentArenaPage.tsx` (remove the badge, the link, the copy)
- Modify: `docs/launch-plan.md:152-154`
- Test: `tests/test_leaderboard.py`, `ui/src/api/leaderboard.test.ts`

**Interfaces:**
- Produces: `LeaderboardRow` without `is_house_agent`; `LeaderboardEntry` without `isHouseAgent`; TS `BoardEntry` without `isHouseAgent`. Tasks 3-7 must not reference any of them.
- Consumes: nothing.

- [ ] **Step 1: Delete the backend field and its test**

In `agentpit/config.py`, delete lines 190-197 — the three-line comment starting
`# The five Arena personalities are ours:` together with the whole
`house_agent_handles: list[str] = Field(...)` declaration.

In `agentpit/services/leaderboard_service.py`, delete `is_house_agent: bool`
from `LeaderboardRow` (line 24) and the two lines
`is_house_agent=account.handle` / `in self._settings.house_agent_handles,`
from the `LeaderboardRow(...)` call in `build_board` (lines 154-155).

In `agentpit/api/routes/leaderboard.py`, delete `isHouseAgent: bool` from
`LeaderboardEntry` (line 26) and `isHouseAgent=row.is_house_agent,` from the
entry construction (line 61).

In `tests/test_leaderboard.py`: delete the whole
`test_build_board_flags_house_agents_by_handle` function (the last test in the
file), and change the `_row` helper's signature from

```python
def _row(
    name, capital, deposited, trades=1, is_house_agent=False, address="0x" + "11" * 20
):
    return LeaderboardRow(
        name=name,
        address=address,
        capital_raw=capital,
        deposited_raw=deposited,
        trades=trades,
        is_house_agent=is_house_agent,
    )
```

to

```python
def _row(name, capital, deposited, trades=1, address="0x" + "11" * 20):
    return LeaderboardRow(
        name=name,
        address=address,
        capital_raw=capital,
        deposited_raw=deposited,
        trades=trades,
    )
```

- [ ] **Step 2: Run the backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS at 433 (one test deleted). A failure naming `house_agent_handles`
means a reference was missed — `grep -rn house_agent agentpit/ tests/` finds it.

- [ ] **Step 3: Commit the backend half**

```bash
git add agentpit/config.py agentpit/services/leaderboard_service.py agentpit/api/routes/leaderboard.py tests/test_leaderboard.py
git commit -m "refactor(leaderboard): every agent is an ordinary row"
```

- [ ] **Step 4: Delete the UI field, helper and its tests**

In `ui/src/api/leaderboard.ts`: delete `isHouseAgent: boolean;` from
`BoardEntry` (line 223), and delete the entire block from the
`/** The five house personalities' ids double as their handles on the wire. */`
comment through the closing brace of `houseAgentHref` (lines 281-299) — that is
`HOUSE_AGENT_IDS` and `houseAgentHref` together.

In `ui/src/api/leaderboard.test.ts`: delete `isHouseAgent: false,` from the
`boardEntry` factory, delete the whole `describe("houseAgentHref", ...)` block,
and remove `houseAgentHref` from the file's import list.

- [ ] **Step 5: Rewrite the row and the header copy**

In `ui/src/pages/AgentArenaPage.tsx`:

Remove `houseAgentHref` from the import from `@/api/leaderboard`, and remove
the now-unused `import { Link } from "react-router-dom";`.

Replace the header paragraph (lines 51-55):

```tsx
          <p className="mt-1 text-sm text-muted-foreground">
            Every account that has traded on agentpit, ranked by return on what
            it was handed.
          </p>
```

Replace `BoardRow` in full — no `href`, no badge, no `Link`:

```tsx
function BoardRow({ entry }: { entry: BoardEntry }) {
  const addr = shortAddr(entry.address);
  const nameIsAddress = entry.name.toLowerCase().startsWith("0x");

  return (
    <li className="grid grid-cols-[3rem_minmax(0,1fr)_6rem] items-center gap-3 px-4 py-3 sm:grid-cols-[3rem_minmax(0,1fr)_7rem_7rem_6rem_4rem]">
      <span className="text-lg tabular-nums">
        {MEDALS[entry.rank - 1] ?? (
          <span className="text-muted-foreground">{entry.rank}</span>
        )}
      </span>
      <span className="min-w-0">
        <span className="block truncate font-semibold">{entry.name}</span>
        {!nameIsAddress ? (
          <span className="block truncate font-mono text-xs text-muted-foreground">
            {addr}
          </span>
        ) : null}
      </span>
      <span className="hidden text-right text-sm tabular-nums sm:block">
        {formatBoardAmount(entry.capital)}
      </span>
      <span
        className={cn(
          "hidden text-right text-sm tabular-nums sm:block",
          pnlText(Number(entry.earned)),
        )}
      >
        {formatBoardAmount(entry.earned)}
      </span>
      <span
        className={cn(
          "text-right text-sm font-semibold tabular-nums",
          pnlText(entry.returnPct),
        )}
      >
        {formatReturnPct(entry.returnPct)}
      </span>
      <span className="hidden text-right text-sm tabular-nums text-muted-foreground sm:block">
        {entry.trades}
      </span>
    </li>
  );
}
```

- [ ] **Step 6: Run the UI checks**

Run from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all four pass. `typecheck` is what catches a missed `isHouseAgent`
reference.

- [ ] **Step 7: Correct the launch plan**

In `docs/launch-plan.md`, replace the closing paragraph of section 3 (lines
152-154):

```markdown
Every account on the board is an ordinary row. An earlier draft badged our five
personalities as ours and keyed the badge to the handle — a field its subject
can edit — so official status would have been claimable by anyone who set the
right name. Dropped.
```

- [ ] **Step 8: Commit the UI half**

```bash
git add ui/src/api/leaderboard.ts ui/src/api/leaderboard.test.ts ui/src/pages/AgentArenaPage.tsx docs/launch-plan.md
git commit -m "refactor(ui): the board stops marking rows as ours"
```

---

### Task 3: The wipe check moves to the valuation pass

For the third time in this project the repair is hooked to a path the flagship
accounts do not take. `reset_deposits` is reachable only from `top_up` and
`_maybe_reonboard`; the Arena bots authenticate by API key, never log in, and
never top up, so after the next redeploy they sit at −100% return indefinitely.
`take_snapshot` runs for every account that has traded regardless of how it
authenticates — which is exactly why it is the right place.

**Files:**
- Modify: `agentpit/services/leaderboard_service.py:101-128` (`take_snapshot`)
- Test: `tests/test_leaderboard.py`

**Interfaces:**
- Consumes: `TableRead.get_deployment_id(db, user_id) -> str | None`, `TableWrite.reset_deposits(db, user_id, deployment_id) -> bool`, `TableWrite.set_deployment_id(db, user_id, deployment_id) -> None` — all already exist. `OnchainAdmin.deployment_id` is a property returning `str`.
- Produces: `LeaderboardService._reconcile_deployment(conn, user_id) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_leaderboard.py`. Note the fake gains a `deployment_id`
attribute — the existing `_FakeOnchainBalance` needs it too, added in Step 3.

```python
def _seed_traded_user(email: str, *, deployed: str | None, deposited: int):
    """A traded account with a stored deployment identity and a deposit
    ledger. Returns (user_id, account)."""
    conn = fresh_test_conn()
    user_id, acct, key = TableWrite.create_user(
        conn, email=email, password_hash="x", handle=None
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s)",
        (f"t-{email}", key, 1_700_000_000),
    )
    TableWrite.set_total_deposited(conn, user_id, deposited)
    if deployed is not None:
        TableWrite.set_deployment_id(conn, user_id, deployed)
    conn.close()
    return user_id, acct


def _deposited(user_id: str) -> int | None:
    conn = fresh_test_conn()
    row = conn.execute(
        "SELECT TOTAL_DEPOSITED FROM users WHERE USER_ID = %s", (user_id,)
    ).fetchone()
    conn.close()
    return None if row is None else row["TOTAL_DEPOSITED"]


def test_the_pass_resets_a_wiped_account_the_bots_never_top_up():
    """The whole point of moving the check here. This account authenticates by
    API key: it never logs in and never tops up, so neither of the two earlier
    homes for this reset could ever reach it."""
    user_id, acct = _seed_traded_user(
        "wiped@example.com", deployed="old-deployment", deposited=900_000_000_000
    )
    db = fresh_test_db()
    onchain = _FakeOnchainBalance({acct.address: 0}, deployment_id="new-deployment")
    service = LeaderboardService(db, onchain, _FakeAccounts(), Settings())

    service.take_snapshot(1_700_003_000)

    assert _deposited(user_id) == 0
    db.close()


def test_a_second_pass_leaves_the_reset_figure_alone():
    """The test the two previous attempts lacked. A level-triggered check --
    'balance is zero', 'identity does not match' evaluated against a value the
    reset itself does not change -- re-fires every tick and erases whatever the
    account was granted in between. The reset swaps the identity, so the second
    pass matches and changes nothing."""
    user_id, acct = _seed_traded_user(
        "twice@example.com", deployed="old-deployment", deposited=900_000_000_000
    )
    db = fresh_test_db()
    onchain = _FakeOnchainBalance({acct.address: 0}, deployment_id="new-deployment")
    service = LeaderboardService(db, onchain, _FakeAccounts(), Settings())

    service.take_snapshot(1_700_003_000)
    conn = fresh_test_conn()
    TableWrite.set_total_deposited(conn, user_id, 100_000_000_000)
    conn.close()
    service.take_snapshot(1_700_003_300)

    assert _deposited(user_id) == 100_000_000_000
    db.close()


def test_an_unchanged_deployment_accumulates_untouched():
    user_id, acct = _seed_traded_user(
        "same@example.com", deployed="same-deployment", deposited=140_000_000_000
    )
    db = fresh_test_db()
    onchain = _FakeOnchainBalance({acct.address: 0}, deployment_id="same-deployment")
    service = LeaderboardService(db, onchain, _FakeAccounts(), Settings())

    service.take_snapshot(1_700_003_000)

    assert _deposited(user_id) == 140_000_000_000
    db.close()


def test_an_absent_identity_is_recorded_without_a_reset():
    """The row predates the column, which is no evidence of a wipe. Recording
    it is what makes the NEXT redeploy detectable."""
    user_id, acct = _seed_traded_user(
        "absent@example.com", deployed=None, deposited=140_000_000_000
    )
    db = fresh_test_db()
    onchain = _FakeOnchainBalance({acct.address: 0}, deployment_id="first-seen")
    service = LeaderboardService(db, onchain, _FakeAccounts(), Settings())

    service.take_snapshot(1_700_003_000)

    assert _deposited(user_id) == 140_000_000_000
    conn = fresh_test_conn()
    stored = TableRead.get_deployment_id(conn, user_id)
    conn.close()
    assert stored == "first-seen"
    db.close()


def test_the_snapshot_records_the_reset_figure_not_the_stale_one():
    """Ordering, asserted directly: the reset must land before the deposit is
    read, or the row written this tick still carries the pre-wipe number and
    the board shows -100% until the next pass."""
    user_id, acct = _seed_traded_user(
        "ordering@example.com", deployed="old", deposited=900_000_000_000
    )
    db = fresh_test_db()
    onchain = _FakeOnchainBalance({acct.address: 0}, deployment_id="new")
    service = LeaderboardService(db, onchain, _FakeAccounts(), Settings())

    service.take_snapshot(1_700_004_000)

    conn = fresh_test_conn()
    latest = TableRead.latest_account_snapshots(conn)
    conn.close()
    assert latest[user_id] == (0, 0)
    db.close()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_leaderboard.py -q -k "wiped or second_pass or unchanged_deployment or absent_identity or reset_figure"`
Expected: FAIL — `TypeError: _FakeOnchainBalance.__init__() got an unexpected
keyword argument 'deployment_id'`.

- [ ] **Step 3: Give the fake a deployment identity**

In `tests/test_leaderboard.py`, replace `_FakeOnchainBalance.__init__` and add
the attribute:

```python
class _FakeOnchainBalance:
    """usd_balance keyed by address; unknown addresses read as `default`.
    `deployment_id` mirrors OnchainAdmin's property -- the valuation pass reads
    it once per account to decide whether the chain was replaced."""

    def __init__(
        self,
        balances: dict[str, int] | None = None,
        default: int = 0,
        deployment_id: str = "test-deployment",
    ):
        self._balances = balances or {}
        self._default = default
        self.deployment_id = deployment_id

    def usd_balance(self, address: str) -> int:
        return self._balances.get(address, self._default)
```

- [ ] **Step 4: Move the check into the pass**

In `agentpit/services/leaderboard_service.py`, add the helper above
`take_snapshot` and call it from inside the per-account `try`:

```python
    def _reconcile_deployment(self, conn, user_id: str) -> None:
        """Start the deposit ledger over when the chain underneath it changed.

        The database outlives a disposable anvil, so after a redeploy an
        account holds nothing on chain while TOTAL_DEPOSITED still carries
        every historical grant and `earned` reads deeply negative. The stored
        identity makes that an edge rather than a level: `reset_deposits`
        writes the new one in the same statement, so this fires once per
        redeploy per account and is a no-op on every later tick.

        This runs here, and not only in `top_up`, because `top_up` is reached
        by logging in and pressing a button -- and the accounts that most need
        the reset authenticate by API key and do neither. This pass sees every
        account that has traded, whatever it authenticates with.
        """
        current = self._onchain.deployment_id
        seen = TableRead.get_deployment_id(conn, user_id)
        if seen is None:
            # Predates the column: record it, but claim no knowledge of a wipe.
            TableWrite.set_deployment_id(conn, user_id, current)
        elif seen != current:
            TableWrite.reset_deposits(conn, user_id, current)
```

and in `take_snapshot`, change the write block to reconcile first:

```python
                capital = self._capital_raw(account.eth_address)
                with self._db.write() as conn:
                    # Before the deposit is read, not after: the row written
                    # this tick must carry the corrected figure.
                    self._reconcile_deployment(conn, account.user_id)
                    deposited = TableRead.get_total_deposited(
                        conn, account.user_id, self._settings.paper_balance_target_raw
                    )
                    TableWrite.insert_account_snapshot(
                        conn, account.user_id, now, capital, deposited
                    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_leaderboard.py -q`
Expected: PASS, whole file.

- [ ] **Step 6: Run the whole backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS at 438.

- [ ] **Step 7: Commit**

```bash
git add agentpit/services/leaderboard_service.py tests/test_leaderboard.py
git commit -m "fix(leaderboard): the wipe reset finally reaches the API-key bots"
```

---

### Task 4: Snapshot retention gets a caller

`prune_account_snapshots` was written and tested and never called. The
valuation pass writes one row per account every 300 seconds — 288 rows per
account per day, forever. Measured under load at 1.28M rows the board query
costs 1023ms and spills 62MB to disk.

**Files:**
- Modify: `agentpit/services/leaderboard_service.py` (add `prune_old`)
- Modify: `agentpit/api/app.py:326-339` (`_leaderboard_loop`), `:420-436` (the task construction)
- Test: `tests/test_leaderboard.py`, `tests/api/test_leaderboard_retention_wiring.py` (new)

**Interfaces:**
- Consumes: `TableWrite.prune_account_snapshots(db, older_than: int) -> int`; `Settings.snapshot_retention_days` (default 30).
- Produces: `LeaderboardService.prune_old(older_than: int) -> int`; `agentpit.api.app._run_leaderboard_tick(service, retention_seconds) -> tuple[int, int]`; `_leaderboard_loop(service, interval_seconds, retention_seconds)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_leaderboard.py`:

```python
def test_prune_old_deletes_past_the_window_and_keeps_the_rest():
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="pruned@example.com", password_hash="x", handle=None
    )
    TableWrite.insert_account_snapshot(conn, user_id, 1_000, 1, 1)
    TableWrite.insert_account_snapshot(conn, user_id, 5_000, 2, 2)
    conn.close()

    db = fresh_test_db()
    service = LeaderboardService(db, onchain=None, accounts=None, settings=Settings())
    assert service.prune_old(4_000) == 1

    check = fresh_test_conn()
    rows = check.execute("SELECT T FROM account_snapshots").fetchall()
    check.close()
    assert [r["T"] for r in rows] == [5_000]
    db.close()
```

Create `tests/api/test_leaderboard_retention_wiring.py`:

```python
"""The tick prunes as well as writes.

`prune_account_snapshots` shipped tested and uncalled -- the loop that writes
288 rows per account per day had no caller for the one that deletes them. A
unit test of the pruning function would have stayed green through all of that,
so this asserts the wiring instead: that the tick calls it, and with a cutoff
derived from the configured retention rather than some other number.
"""
from agentpit.api.app import _run_leaderboard_tick


class _SpyService:
    def __init__(self):
        self.snapshot_at: int | None = None
        self.pruned_before: int | None = None

    def take_snapshot(self, now: int) -> int:
        self.snapshot_at = now
        return 3

    def prune_old(self, older_than: int) -> int:
        self.pruned_before = older_than
        return 7


def test_the_tick_writes_and_prunes():
    service = _SpyService()
    written, deleted = _run_leaderboard_tick(service, retention_seconds=86_400)

    assert (written, deleted) == (3, 7)
    assert service.snapshot_at is not None
    assert service.pruned_before == service.snapshot_at - 86_400
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_leaderboard.py::test_prune_old_deletes_past_the_window_and_keeps_the_rest tests/api/test_leaderboard_retention_wiring.py -q`
Expected: FAIL — `AttributeError: 'LeaderboardService' object has no attribute
'prune_old'` and `ImportError: cannot import name '_run_leaderboard_tick'`.

- [ ] **Step 3: Add `prune_old` to the service**

In `agentpit/services/leaderboard_service.py`, after `take_snapshot`:

```python
    def prune_old(self, older_than: int) -> int:
        """Drop snapshots older than `older_than`. Returns rows deleted.

        Takes an absolute cutoff rather than a window so the caller owns the
        clock -- the same reason `take_snapshot` takes `now`. Without this the
        table grows by one row per account per tick forever.
        """
        with self._db.write() as conn:
            return TableWrite.prune_account_snapshots(conn, older_than)
```

- [ ] **Step 4: Wire it into the loop**

In `agentpit/api/app.py`, add the tick function directly above
`_leaderboard_loop` (~line 326) and rewrite the loop to use it:

```python
def _run_leaderboard_tick(service, retention_seconds: int) -> tuple[int, int]:
    now = int(time.time())
    written = service.take_snapshot(now)
    deleted = service.prune_old(now - retention_seconds)
    return written, deleted


async def _leaderboard_loop(
    service: LeaderboardService, interval_seconds: int, retention_seconds: int
) -> None:
    while True:
        try:
            written, deleted = await asyncio.to_thread(
                _run_leaderboard_tick, service, retention_seconds
            )
            log.info(
                "Leaderboard tick: %d accounts valued, %d snapshots pruned",
                written,
                deleted,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Leaderboard tick failed")
        await asyncio.sleep(interval_seconds)
```

And in the startup block (~line 420), log the retention and pass it in:

```python
        leaderboard_task: asyncio.Task | None = None
        if settings.leaderboard_enabled:
            log.info(
                "Leaderboard loop enabled (interval=%ds, retention=%dd)",
                settings.leaderboard_interval_seconds,
                settings.snapshot_retention_days,
            )
            leaderboard_service = LeaderboardService(
                db_session,
                onchain_admin,
                AccountService(db_session, onchain_admin),
                settings,
            )
            leaderboard_task = asyncio.create_task(
                _leaderboard_loop(
                    leaderboard_service,
                    settings.leaderboard_interval_seconds,
                    settings.snapshot_retention_days * 86_400,
                )
            )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_leaderboard.py tests/api/test_leaderboard_retention_wiring.py -q`
Expected: PASS.

- [ ] **Step 6: Run the whole backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS at 440.

- [ ] **Step 7: Commit**

```bash
git add agentpit/services/leaderboard_service.py agentpit/api/app.py tests/test_leaderboard.py tests/api/test_leaderboard_retention_wiring.py
git commit -m "fix(leaderboard): snapshot retention gets the caller it never had"
```

---

### Task 5: Queries the indexes can actually drive

`idx_trades_taker_api_key` and `idx_trades_maker_api_key` exist, and neither
board query can use them: Postgres cannot index-drive a join whose condition is
an `OR` across two columns, so both plan a nested loop discarding tens of
millions of rows. Splitting the `OR` into two scans over a `UNION ALL` gives
each index its own branch.

**Files:**
- Modify: `agentpit/db/table_read.py:299-337` (`list_traded_accounts`, `count_trades_by_user`)
- Test: `tests/test_leaderboard.py`

**Interfaces:**
- Produces: unchanged signatures — `TableRead.list_traded_accounts(db) -> list[TradedAccount]`, `TableRead.count_trades_by_user(db) -> dict[str, int]`. Same results, different plans.

- [ ] **Step 1: Write the failing test**

The rewrite must not change results, so the test pins the two behaviours a
naive `UNION ALL` breaks: a maker-only account still appears (already covered
by `test_maker_only_trade_still_counts_as_traded`, which stays), and a trade
where one account is both sides counts **once**, not twice. Append to
`tests/test_leaderboard.py`:

```python
def test_a_self_matched_trade_counts_once_not_twice():
    """The UNION ALL rewrite emits one row per api-key column, so a trade whose
    taker and maker are the same account arrives twice. The OR-join it replaces
    produced a single joined row, and the count must not change: this is the
    regression a plain COUNT(*) over the union would introduce silently."""
    conn = fresh_test_conn()
    user_id, _acct, key = TableWrite.create_user(
        conn, email="selfmatch@example.com", password_hash="x", handle=None
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s, %s)",
        ("t-self", key, key, 1_700_000_000),
    )

    assert TableRead.count_trades_by_user(conn)[user_id] == 1
    assert [r.user_id for r in TableRead.list_traded_accounts(conn)] == [user_id]
    conn.close()


def test_counts_cover_both_sides_of_a_trade():
    conn = fresh_test_conn()
    maker_id, _m, maker_key = TableWrite.create_user(
        conn, email="counted-maker@example.com", password_hash="x", handle=None
    )
    taker_id, _t, taker_key = TableWrite.create_user(
        conn, email="counted-taker@example.com", password_hash="x", handle=None
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s, %s)",
        ("t-both", taker_key, maker_key, 1_700_000_000),
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s)",
        ("t-taker-only", taker_key, 1_700_000_100),
    )

    counts = TableRead.count_trades_by_user(conn)
    assert counts[taker_id] == 2
    assert counts[maker_id] == 1
    conn.close()
```

- [ ] **Step 2: Run them to verify they pass against the old queries**

Run: `.venv/bin/python -m pytest tests/test_leaderboard.py -q -k "self_matched or both_sides"`
Expected: **PASS.** These pin existing behaviour before the rewrite — that is
their job. If either fails now, stop: the current queries do not do what this
task assumes and the plan needs revisiting.

- [ ] **Step 3: Rewrite both queries**

In `agentpit/db/table_read.py`, replace the bodies of `list_traded_accounts`
and `count_trades_by_user`:

```python
    @staticmethod
    def list_traded_accounts(db: psycopg.Connection) -> "list[TradedAccount]":
        """Every non-house account with at least one trade, taker or maker.

        Having traded is the membership rule: it keeps every registered
        address off a public board by default, and an account that never
        traded has nothing to rank. The house is excluded because it is the
        counterparty to nearly every trade rather than a competitor.

        The two api-key columns are separate scans over a UNION ALL rather
        than one join on `taker = key OR maker = key`. Postgres cannot
        index-drive an OR across two columns, so the readable form planned a
        nested loop that discarded 47.6M rows while
        `idx_trades_taker_api_key` and `idx_trades_maker_api_key` sat unused.
        Each branch now drives its own index. `DISTINCT` already collapses the
        duplicate a self-matched trade produces.
        """
        rows = db.execute(
            """
            SELECT DISTINCT u.USER_ID, u.ETH_ADDRESS, u.HANDLE
            FROM users u
            JOIN (
                SELECT TAKER_API_KEY AS K FROM trades
                UNION ALL
                SELECT MAKER_API_KEY AS K FROM trades
            ) t ON t.K = u.API_KEY
            WHERE u.IS_BOT = 0
            ORDER BY u.USER_ID
            """
        ).fetchall()
        return [
            TradedAccount(
                user_id=r["USER_ID"],
                eth_address=r["ETH_ADDRESS"],
                handle=r["HANDLE"],
            )
            for r in rows
        ]

    @staticmethod
    def count_trades_by_user(db: psycopg.Connection) -> "dict[str, int]":
        """user_id -> number of trades it took part in, either side.

        Same UNION ALL rewrite as `list_traded_accounts`, and the reason
        `COUNT(DISTINCT t.TRADE_ID)` is not `COUNT(*)`: the union emits one row
        per api-key column, so an account that was both taker and maker on a
        trade appears twice. The OR-join this replaces produced a single joined
        row, and the figure on the board must not change.
        """
        rows = db.execute(
            """
            SELECT u.USER_ID AS UID, COUNT(DISTINCT t.TRADE_ID) AS N
            FROM users u
            JOIN (
                SELECT TRADE_ID, TAKER_API_KEY AS K FROM trades
                UNION ALL
                SELECT TRADE_ID, MAKER_API_KEY AS K FROM trades
            ) t ON t.K = u.API_KEY
            GROUP BY u.USER_ID
            """
        ).fetchall()
        return {r["UID"]: int(r["N"]) for r in rows}
```

- [ ] **Step 4: Run the leaderboard tests to verify they still pass**

Run: `.venv/bin/python -m pytest tests/test_leaderboard.py -q`
Expected: PASS, whole file — same results from different plans.

- [ ] **Step 5: Run the whole backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS at 442.

- [ ] **Step 6: Commit**

```bash
git add agentpit/db/table_read.py tests/test_leaderboard.py
git commit -m "perf(leaderboard): split the OR so the api-key indexes apply"
```

---

### Task 6: The history endpoint

The board's sparklines vanished because the endpoint that replaced the static
file returns only current figures. The data was never missing: the valuation
pass writes a row per account per tick, so a day gives each account 288 points.
What is missing is the pipe.

**Files:**
- Modify: `agentpit/db/table_read.py` (add `list_account_snapshots` after `latest_account_snapshots`, ~line 354)
- Modify: `agentpit/services/leaderboard_service.py` (add `compute_earned_raw`, `compute_return_pct`, `downsample`; `LeaderboardRow` delegates)
- Modify: `agentpit/api/routes/leaderboard.py` (add the route)
- Test: `tests/test_leaderboard.py`, `tests/api/test_leaderboard_endpoint.py`

**Interfaces:**
- Produces: `TableRead.list_account_snapshots(db, user_id: str, limit: int) -> list[tuple[int, int, int]]` — `(t, capital_raw, deposited_raw)`, oldest first, newest `limit` rows.
- Produces: `compute_earned_raw(capital_raw: int, deposited_raw: int) -> int`; `compute_return_pct(capital_raw: int, deposited_raw: int) -> float`; `downsample(points: list, max_points: int) -> list`.
- Produces: `GET /leaderboard/{address}/history` → `{"points": [{"t": int, "capital": str, "earned": str, "returnPct": float}]}`; 404 for an unknown address.
- Consumes: `TableRead.get_user_by_eth_address(db, eth_address) -> User | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_leaderboard.py`:

```python
from agentpit.services.leaderboard_service import (
    compute_earned_raw,
    compute_return_pct,
    downsample,
)


def test_the_shared_arithmetic_matches_the_row_properties():
    """One formula, two callers: the board row and the history point. The
    properties delegate rather than restate, so a change cannot land in one
    and miss the other."""
    row = _row("a", capital=120_000_000_000, deposited=100_000_000_000)
    assert compute_earned_raw(120_000_000_000, 100_000_000_000) == row.earned_raw
    assert compute_return_pct(120_000_000_000, 100_000_000_000) == row.return_pct
    assert compute_return_pct(5, 0) == 0.0


def test_downsample_keeps_the_newest_point_and_respects_the_cap():
    """A 30-day history at the 5-minute cadence is 8,640 points; a 72-pixel
    sparkline needs a fraction of that, and sending the rest would be the
    board's whole payload. The newest point must survive -- it is the one the
    curve ends on, and dropping it would make the line disagree with the
    Return column beside it."""
    points = [(t, t, 0) for t in range(1_000)]
    thinned = downsample(points, 60)
    assert len(thinned) <= 60
    assert thinned[-1] == points[-1]
    assert thinned == sorted(thinned)


def test_downsample_leaves_a_short_history_alone():
    points = [(1, 10, 10), (2, 20, 10)]
    assert downsample(points, 60) == points
    assert downsample([], 60) == []


def test_list_account_snapshots_returns_the_newest_rows_oldest_first():
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="history@example.com", password_hash="x", handle=None
    )
    for t in (1_000, 2_000, 3_000):
        TableWrite.insert_account_snapshot(conn, user_id, t, t * 10, 500)

    rows = TableRead.list_account_snapshots(conn, user_id, limit=2)
    conn.close()
    assert rows == [(2_000, 20_000, 500), (3_000, 30_000, 500)]
```

Append to `tests/api/test_leaderboard_endpoint.py`:

```python
def test_history_returns_the_accounts_curve():
    conn = fresh_test_conn()
    user_id, acct, key = TableWrite.create_user(
        conn, email="curve@example.com", password_hash="x", handle="curvy"
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s)",
        ("t-curve", key, 1_700_000_000),
    )
    TableWrite.insert_account_snapshot(
        conn, user_id, 1_800_000_000, 100_000_000_000, 100_000_000_000
    )
    TableWrite.insert_account_snapshot(
        conn, user_id, 1_800_000_300, 150_000_000_000, 100_000_000_000
    )
    conn.close()

    with TestClient(app) as client:
        resp = client.get(f"/leaderboard/{acct.address}/history")

    assert resp.status_code == 200, resp.text
    points = resp.json()["points"]
    assert [p["t"] for p in points] == [1_800_000_000, 1_800_000_300]
    assert points[-1]["capital"] == "150000000000"
    assert points[-1]["earned"] == "50000000000"
    assert points[-1]["returnPct"] == 50.0


def test_history_of_an_unknown_address_is_a_404():
    with TestClient(app) as client:
        resp = client.get("/leaderboard/0x" + "00" * 20 + "/history")
    assert resp.status_code == 404


def test_history_carries_no_email():
    """Same guarantee as the board: nobody's signup address on a public
    endpoint, asserted against the raw body."""
    conn = fresh_test_conn()
    user_id, acct, _key = TableWrite.create_user(
        conn, email="private@example.com", password_hash="x", handle="private1"
    )
    TableWrite.insert_account_snapshot(
        conn, user_id, 1_800_000_000, 1, 1
    )
    conn.close()

    with TestClient(app) as client:
        body = client.get(f"/leaderboard/{acct.address}/history").text
    assert "@" not in body
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_leaderboard.py tests/api/test_leaderboard_endpoint.py -q`
Expected: FAIL — `ImportError: cannot import name 'compute_earned_raw'` and 404s
on the history route.

- [ ] **Step 3: Add the reader**

In `agentpit/db/table_read.py`, after `latest_account_snapshots`:

```python
    @staticmethod
    def list_account_snapshots(
        db: psycopg.Connection, user_id: str, limit: int
    ) -> "list[tuple[int, int, int]]":
        """The newest `limit` snapshots for one account, oldest first.

        `ORDER BY T DESC LIMIT n` is what `idx_account_snapshots_user_t`
        drives; the reversal into chronological order happens here so callers
        get a curve rather than a stack. Bounded on purpose: retention keeps
        30 days, which at the 5-minute cadence is 8,640 rows nobody wants to
        serialise.
        """
        rows = db.execute(
            """
            SELECT T, CAPITAL_RAW, DEPOSITED_RAW
            FROM account_snapshots
            WHERE USER_ID = %s
            ORDER BY T DESC, SNAPSHOT_ID DESC
            LIMIT %s
            """,
            (user_id, limit),
        ).fetchall()
        return [
            (int(r["T"]), int(r["CAPITAL_RAW"]), int(r["DEPOSITED_RAW"]))
            for r in reversed(rows)
        ]
```

- [ ] **Step 4: Extract the arithmetic and add `downsample`**

In `agentpit/services/leaderboard_service.py`, add above `LeaderboardRow`:

```python
def compute_earned_raw(capital_raw: int, deposited_raw: int) -> int:
    return capital_raw - deposited_raw


def compute_return_pct(capital_raw: int, deposited_raw: int) -> float:
    """Percent return on what the account was handed.

    Zero deposits cannot happen once the signup grant counts as the first one
    -- which is why it does -- but a board that divides by zero on an edge
    case is worse than one that shows 0%.
    """
    if deposited_raw <= 0:
        return 0.0
    return 100.0 * compute_earned_raw(capital_raw, deposited_raw) / deposited_raw


def downsample(points: list, max_points: int) -> list:
    """At most `max_points` evenly spaced samples, newest always kept.

    Anchored on the end rather than the start: the last point is where the
    curve meets the Return column beside it, and a stride that dropped it
    would draw a line disagreeing with the number it sits next to.
    """
    if max_points <= 0 or len(points) <= max_points:
        return list(points)
    stride = math.ceil(len(points) / max_points)
    return points[::-1][::stride][::-1]
```

Add `import math` at the top of the file, and rewrite the two `LeaderboardRow`
properties to delegate:

```python
    @property
    def earned_raw(self) -> int:
        return compute_earned_raw(self.capital_raw, self.deposited_raw)

    @property
    def return_pct(self) -> float:
        return compute_return_pct(self.capital_raw, self.deposited_raw)
```

(The docstring that was on `return_pct` moves to `compute_return_pct` above —
do not leave a copy behind.)

- [ ] **Step 5: Add the route**

In `agentpit/api/routes/leaderboard.py`, add the imports and the route below
`get_leaderboard`:

```python
from fastapi import APIRouter, HTTPException, Path, Query

from agentpit.api.deps import LeaderboardServiceDep, SessionDep
from agentpit.db.table_read import TableRead
from agentpit.services.leaderboard_service import (
    SORTS,
    compute_earned_raw,
    compute_return_pct,
    downsample,
    rank_rows,
)
```

```python
# 7 days at the 5-minute valuation cadence, thinned to what a 72-pixel
# sparkline can show. Fetching a bounded window and thinning it beats sending
# 8,640 points the client immediately discards.
_HISTORY_ROWS = 2_016
_HISTORY_POINTS = 60


class HistoryPoint(BaseModel):
    t: int
    capital: str
    earned: str
    returnPct: float


class HistoryResponse(BaseModel):
    points: "list[HistoryPoint]"


@router.get("/leaderboard/{address}/history", response_model=HistoryResponse)
def get_leaderboard_history(
    db: SessionDep,
    address: str = Path(...),
) -> HistoryResponse:
    """One account's equity curve, for the sparkline on its board row.

    Return rather than a bare balance, because return is what the board ranks
    on by default and a curve that disagreed with the column beside it would
    be worse than no curve. Public and database-only, like the board itself --
    and carrying no email, for the same reason.

    The address must match what `GET /leaderboard` returned; that is the only
    caller, and it passes the stored string back verbatim.
    """
    with db.read() as conn:
        user = TableRead.get_user_by_eth_address(conn, address)
        if user is None:
            raise HTTPException(status_code=404, detail="no such account")
        rows = TableRead.list_account_snapshots(
            conn, user.user_id, _HISTORY_ROWS
        )

    return HistoryResponse(
        points=[
            HistoryPoint(
                t=t,
                capital=str(capital),
                earned=str(compute_earned_raw(capital, deposited)),
                returnPct=round(compute_return_pct(capital, deposited), 2),
            )
            for t, capital, deposited in downsample(rows, _HISTORY_POINTS)
        ]
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_leaderboard.py tests/api/test_leaderboard_endpoint.py -q`
Expected: PASS.

- [ ] **Step 7: Run the whole backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS at 449.

- [ ] **Step 8: Commit**

```bash
git add agentpit/db/table_read.py agentpit/services/leaderboard_service.py agentpit/api/routes/leaderboard.py tests/test_leaderboard.py tests/api/test_leaderboard_endpoint.py
git commit -m "feat(leaderboard): an equity history endpoint per account"
```

---

### Task 7: The sparkline comes back

The drawing code was never deleted — `Sparkline`, `equityPoints` and the
projection helpers are all still there, currently dead. They get reconnected to
the new endpoint rather than rewritten.

**Files:**
- Modify: `ui/src/api/leaderboard.ts` (add the history types, query and sample mapping)
- Modify: `ui/src/pages/AgentArenaPage.tsx` (a trend column)
- Test: `ui/src/api/leaderboard.test.ts`

**Interfaces:**
- Consumes: `GET /leaderboard/{address}/history` → `{points: [{t, capital, earned, returnPct}]}` (Task 6); `equityPoints(equity: PnlPoint[]): SparklineSample[]` already in `ui/src/api/leaderboard.ts:102`; `Sparkline` from `@/components/Sparkline`; `BoardEntry` without `isHouseAgent` (Task 2).
- Produces: `BoardHistoryPoint`, `BoardHistory`, `useBoardHistory(address: string)`, `boardTrendPoints(history: BoardHistory | undefined): SparklineSample[]`, `trendTone(pct: number): "up" | "down" | "neutral"`.

- [ ] **Step 1: Write the failing test**

Append to `ui/src/api/leaderboard.test.ts` (and add `boardTrendPoints`,
`trendTone` to the imports from `./leaderboard`):

```ts
describe("boardTrendPoints", () => {
  it("plots return, not capital — the figure the board ranks on", () => {
    const points = boardTrendPoints({
      points: [
        { t: 10, capital: "100000000000", earned: "0", returnPct: 0 },
        { t: 20, capital: "150000000000", earned: "50000000000", returnPct: 50 },
      ],
    });
    expect(points).toEqual([
      { t: 10, p: 0 },
      { t: 20, p: 50 },
    ]);
  });

  it("pads a single point so a fresh account draws a flat line, not a dot", () => {
    const points = boardTrendPoints({
      points: [{ t: 10, capital: "1", earned: "0", returnPct: 0 }],
    });
    expect(points).toHaveLength(2);
  });

  it("is empty while the history is still loading", () => {
    expect(boardTrendPoints(undefined)).toEqual([]);
  });
});

describe("trendTone", () => {
  it("matches the sign convention the Return column already uses", () => {
    expect(trendTone(12.5)).toBe("up");
    expect(trendTone(-4)).toBe("down");
    expect(trendTone(0)).toBe("neutral");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run from `ui/`: `npx vitest run src/api/leaderboard.test.ts`
Expected: FAIL — `boardTrendPoints is not a function`.

- [ ] **Step 3: Add the history query and mapping**

Append to `ui/src/api/leaderboard.ts`:

```ts
/** One point of `GET /leaderboard/{address}/history`. Amounts are base-unit
 *  integer strings; `returnPct` is already a percentage. */
export interface BoardHistoryPoint {
  t: number;
  capital: string;
  earned: string;
  returnPct: number;
}

export interface BoardHistory {
  points: BoardHistoryPoint[];
}

/** One account's equity curve. Polled at half the board's rate: a new point
 *  only exists once the valuation pass has run (every five minutes), so
 *  fetching faster would re-download the same curve per row per poll. */
export function useBoardHistory(address: string) {
  return useQuery({
    queryKey: ["leaderboard-history", address],
    queryFn: () =>
      apiFetch<BoardHistory>(
        `/leaderboard/${encodeURIComponent(address)}/history`,
      ),
    refetchInterval: 60_000,
    staleTime: 55_000,
    retry: false,
  });
}

/** History to sparkline samples, plotting **return** rather than capital —
 *  the figure the board ranks on by default, so the curve and the Return
 *  column beside it tell the same story. `equityPoints` pads a single point to
 *  two so a fresh account renders a flat line instead of a lone dot. */
export function boardTrendPoints(
  history: BoardHistory | undefined,
): SparklineSample[] {
  if (!history || history.points.length === 0) return [];
  return equityPoints(history.points.map((d) => ({ t: d.t, p: d.returnPct })));
}

/** Same sign convention as the Return column's colour. */
export function trendTone(pct: number): "up" | "down" | "neutral" {
  return pct > 0 ? "up" : pct < 0 ? "down" : "neutral";
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run from `ui/`: `npx vitest run src/api/leaderboard.test.ts`
Expected: PASS.

- [ ] **Step 5: Add the trend column to the board**

In `ui/src/pages/AgentArenaPage.tsx`, extend the import from
`@/api/leaderboard` with `boardTrendPoints`, `trendTone`, `useBoardHistory`, and
add `import { Sparkline } from "@/components/Sparkline";`.

In the header row (line 92), change the grid template and add the label:

```tsx
        <div className="hidden grid-cols-[3rem_minmax(0,1fr)_5rem_7rem_7rem_6rem_4rem] items-center gap-3 border-b px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground sm:grid">
          <span>#</span>
          <span>Agent</span>
          <span>Trend</span>
          <span className="text-right">Capital</span>
          <span className="text-right">Earned</span>
          <span className="text-right">Return</span>
          <span className="text-right">Trades</span>
        </div>
```

And in `BoardRow` (as rewritten in Task 2), change the `<li>` class to the
seven-column template and insert the sparkline cell directly after the name
cell:

```tsx
function BoardRow({ entry }: { entry: BoardEntry }) {
  const addr = shortAddr(entry.address);
  const nameIsAddress = entry.name.toLowerCase().startsWith("0x");
  const { data: history } = useBoardHistory(entry.address);
  const trend = boardTrendPoints(history);

  return (
    <li className="grid grid-cols-[3rem_minmax(0,1fr)_6rem] items-center gap-3 px-4 py-3 sm:grid-cols-[3rem_minmax(0,1fr)_5rem_7rem_7rem_6rem_4rem]">
      <span className="text-lg tabular-nums">
        {MEDALS[entry.rank - 1] ?? (
          <span className="text-muted-foreground">{entry.rank}</span>
        )}
      </span>
      <span className="min-w-0">
        <span className="block truncate font-semibold">{entry.name}</span>
        {!nameIsAddress ? (
          <span className="block truncate font-mono text-xs text-muted-foreground">
            {addr}
          </span>
        ) : null}
      </span>
      <span className="hidden sm:block">
        <Sparkline
          points={trend}
          width={72}
          height={24}
          tone={trendTone(entry.returnPct)}
        />
      </span>
      <span className="hidden text-right text-sm tabular-nums sm:block">
        {formatBoardAmount(entry.capital)}
      </span>
      <span
        className={cn(
          "hidden text-right text-sm tabular-nums sm:block",
          pnlText(Number(entry.earned)),
        )}
      >
        {formatBoardAmount(entry.earned)}
      </span>
      <span
        className={cn(
          "text-right text-sm font-semibold tabular-nums",
          pnlText(entry.returnPct),
        )}
      >
        {formatReturnPct(entry.returnPct)}
      </span>
      <span className="hidden text-right text-sm tabular-nums text-muted-foreground sm:block">
        {entry.trades}
      </span>
    </li>
  );
}
```

`Sparkline` already renders a dashed placeholder line for an empty `points`
array, so a row whose history has not loaded shows that rather than a gap.

- [ ] **Step 6: Run the full UI chain**

Run from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all four pass.

- [ ] **Step 7: Commit**

```bash
git add ui/src/api/leaderboard.ts ui/src/api/leaderboard.test.ts ui/src/pages/AgentArenaPage.tsx
git commit -m "feat(ui): the board's equity sparkline comes back, off the API"
```

---

## Verification before finishing

- [ ] `git branch --show-current` prints `mvp`.
- [ ] `.venv/bin/python -m pytest tests -q --ignore=tests/onchain` — 449 passed, no `.env` sourced.
- [ ] From `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build` — all green.
- [ ] `git log --oneline` shows nine commits, none carrying a `Co-Authored-By` trailer.
- [ ] `grep -rn "house_agent\|isHouseAgent\|houseAgentHref" agentpit/ ui/src/ tests/` returns nothing.

## Known and deliberate, recorded so review does not relitigate

- **An account whose stored deployment is NULL is never reset**, only recorded — spec section 3. Absent is not evidence of a wipe, so an account that predates the column *and* was wiped reads −100% until it trades against a later redeploy. Accepted in the spec.
- **The board issues one history request per row.** With the board empty at launch and rows counted in tens thereafter, at a 60-second cadence against a database-only, index-driven endpoint. Revisit if the board ever pages.
- **Registration has a sub-millisecond race** between `handle_taken` and the insert. Losing it needs two signups in the same instant drawing the same 1-in-14,400 pair, and it fails loudly against `HANDLE TEXT UNIQUE` rather than duplicating a handle.
- **Deferred by the spec, not to be picked up here:** per-agent pages and the optional owner-only `rationale`; ~110 lines of dead UI code in `ui/src/api/leaderboard.ts` (`rankAgents`, `windowAgent`, `TIME_WINDOWS`, `lastTrade`, `lastHold`, `resolveAgentIdentity`, `useArenaAgentsFeed`) — `equityPoints` stops being dead in Task 7, the rest stay; `/leaderboard` undocumented in `docs/API.md`; `AgentPage` still reading the static `leaderboard.json`.
