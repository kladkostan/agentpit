# Match Legs and Price Prints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the seven read paths that still treat a trade row as "one token at one price" tell the truth about MINT and MERGE matches.

**Architecture:** Two primitives, deliberately separate. A *user leg* (who did what — a NORMAL match yields two, one per party) is pure Python in a new `datastructures/match_leg.py`, extracted from the rule already inside `_token_flow`. A *price print* (this token traded at this price — a NORMAL match yields exactly one) is a SQL CTE constant in `table_read.py`, because its consumers are batched and use `DISTINCT ON`. Everything is derived at read time; there is no data migration.

**Tech Stack:** Python 3.13, FastAPI, psycopg3 + Postgres, pytest.

## Global Constraints

- `trades.PRICE` is ALWAYS the maker's price. `trades.ASSET_ID` is ALWAYS the taker's token.
- MICRO = `1_000_000`. A MINT/MERGE's two legs have prices summing to exactly MICRO.
- A NORMAL match yields exactly ONE price print. Emitting both legs doubles every chart point and every volume figure derived from the tape — it fails silently.
- A NORMAL match yields TWO user legs (buyer and seller). This is the inverse of the print rule; one shared helper for both would be wrong.
- Rows may carry NULL `MATCH_KIND` / `MAKER_ASSET_ID` (fixtures inserting into `trades` directly). Those take the NORMAL path.
- One api_key can be BOTH taker and maker on one row — the matcher has no same-account guard, and 373,221 of 458,000 production rows are self-matched.
- Read paths only. Do not change the matcher, `_insert_trade`, or anything about how a match is decided or written.
- Rows are dict-style and case-insensitive via `ci_dict_row`; string-keyed access is the house pattern and pyright complains about it everywhere. Do not fight it.
- Backend tests: `cd /Users/yavorsky/dev/agentpit && .venv/bin/python -m pytest tests -q --ignore=tests/onchain`. NEVER source `.env` — `tests/conftest.py` uses `os.environ.setdefault` and a sourced `.env` defeats every default. The local anvil must be running (`./scripts/run_node.sh`), because `conftest` imports the app.
- Commit messages must NOT carry a `Co-Authored-By` trailer. Commit on branch `mvp`.
- No UI changes. No new variant in `ActivityWire`. No divergence from the Polymarket API shape.

## File Structure

| File | Responsibility |
| --- | --- |
| `agentpit/datastructures/match_leg.py` (new) | The user-leg truth table. Pure functions, no I/O. |
| `agentpit/db/table_read.py` | Gains `TOKEN_PRINTS_CTE`; three tape readers and the trades filter change. |
| `agentpit/db/table_create.py` | Two idempotent indexes. |
| `agentpit/services/account_service.py` | `_token_flow` adopts `match_leg`; `_cur_price` and `list_activity` change. |
| `agentpit/services/order_service.py` | Three tape readers change. |
| `agentpit/services/trade_service.py` | The maker perspective emits its own token and price. |
| `tests/datastructures/test_match_leg.py` (new) | The pure truth table. |
| `tests/db/test_token_prints.py` (new) | The three invariants + the indexes. |
| `tests/services/test_match_leg_consumers.py` (new) | The five tape sites, Activity, and `/data/trades`. |

---

### Task 1: The user-leg truth table

**Files:**
- Create: `agentpit/datastructures/match_leg.py`
- Modify: `agentpit/services/account_service.py` (`_token_flow`, ~lines 292-355)
- Test: `tests/datastructures/test_match_leg.py`

**Interfaces:**
- Produces: `MICRO: int`, `Leg` (frozen dataclass with `token_id: str`, `side: str`, `price_micro: int`, `size_micro: int`, `is_taker: bool`), and `legs_for_user(row, api_key) -> list[Leg]`. `row` is any Mapping with the upper-case keys `TAKER_API_KEY`, `MAKER_API_KEY`, `ASSET_ID`, `MAKER_ASSET_ID`, `MATCH_KIND`, `SIDE`, `PRICE`, `TRADE_SIZE`. Tasks 4 and 5 consume this.

- [ ] **Step 1: Write the failing test**

Create `tests/datastructures/test_match_leg.py`:

```python
"""The user-leg truth table: what did THIS account do on this row.

A NORMAL match yields two legs — buyer and seller, same token, one price.
A MINT/MERGE yields two legs on DIFFERENT tokens whose prices sum to MICRO.
This is pure: no database, no I/O.
"""

from __future__ import annotations

from agentpit.datastructures.match_leg import MICRO, legs_for_user


def _row(**over):
    row = {
        "TAKER_API_KEY": "taker",
        "MAKER_API_KEY": "maker",
        "ASSET_ID": "yes",
        "MAKER_ASSET_ID": "no",
        "MATCH_KIND": "NORMAL",
        "SIDE": "BUY",
        "PRICE": 300_000,
        "TRADE_SIZE": 100,
    }
    row.update(over)
    return row


def test_a_normal_match_gives_the_taker_its_side_and_the_maker_the_opposite():
    row = _row(MAKER_ASSET_ID="yes")
    taker = legs_for_user(row, "taker")
    maker = legs_for_user(row, "maker")
    assert [(l.token_id, l.side, l.price_micro) for l in taker] == [
        ("yes", "BUY", 300_000)
    ]
    assert [(l.token_id, l.side, l.price_micro) for l in maker] == [
        ("yes", "SELL", 300_000)
    ]


def test_a_mint_gives_both_sides_a_buy_of_different_tokens():
    row = _row(MATCH_KIND="MINT")
    taker = legs_for_user(row, "taker")[0]
    maker = legs_for_user(row, "maker")[0]
    assert (taker.token_id, taker.side) == ("yes", "BUY")
    assert (maker.token_id, maker.side) == ("no", "BUY")
    # The pair costs exactly $1.
    assert taker.price_micro + maker.price_micro == MICRO
    assert maker.price_micro == 300_000  # the stored price IS the maker's


def test_a_merge_gives_both_sides_a_sell_of_different_tokens():
    row = _row(MATCH_KIND="MERGE", SIDE="SELL")
    taker = legs_for_user(row, "taker")[0]
    maker = legs_for_user(row, "maker")[0]
    assert (taker.token_id, taker.side) == ("yes", "SELL")
    assert (maker.token_id, maker.side) == ("no", "SELL")
    assert taker.price_micro + maker.price_micro == MICRO


def test_a_null_match_kind_takes_the_normal_path():
    """Fixtures insert into `trades` directly and leave the columns NULL."""
    row = _row(MATCH_KIND=None, MAKER_ASSET_ID=None)
    maker = legs_for_user(row, "maker")[0]
    assert (maker.token_id, maker.side, maker.price_micro) == ("yes", "SELL", 300_000)


def test_a_self_matched_row_yields_both_legs():
    """The matcher has no same-account guard; both legs are real."""
    row = _row(TAKER_API_KEY="same", MAKER_API_KEY="same", MAKER_ASSET_ID="yes")
    legs = legs_for_user(row, "same")
    assert sorted(l.side for l in legs) == ["BUY", "SELL"]
    assert {l.token_id for l in legs} == {"yes"}


def test_a_stranger_owns_no_legs():
    assert legs_for_user(_row(), "nobody") == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/datastructures/test_match_leg.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentpit.datastructures.match_leg'`.

- [ ] **Step 3: Write the implementation**

Create `agentpit/datastructures/match_leg.py`:

```python
"""What one account actually did on one trade row.

`trades.PRICE` is always the MAKER's price and `trades.ASSET_ID` is always the
TAKER's token. That is the whole truth for a NORMAL match, where both parties
transact in the same token at the same price. It is not for the two special
kinds:

| kind   | the taker's leg                  | the maker's leg                     |
| ------ | -------------------------------- | ----------------------------------- |
| NORMAL | ASSET_ID, side SIDE, price p     | ASSET_ID, opposite of SIDE, price p |
| MINT   | ASSET_ID, BUY, price MICRO - p   | MAKER_ASSET_ID, BUY, price p        |
| MERGE  | ASSET_ID, SELL, price MICRO - p  | MAKER_ASSET_ID, SELL, price p       |

A MINT mints a complementary pair for $1, so both sides ACQUIRE, of different
tokens, at prices summing to MICRO. A MERGE burns one, so both sides DISPOSE.

This is the per-user view: a NORMAL match yields TWO legs, the buyer's and the
seller's. Do not confuse it with a price print, where a NORMAL match yields
exactly ONE — see `TOKEN_PRINTS_CTE` in `agentpit/db/table_read.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: Prices and sizes are integers scaled by 10**6; MICRO is $1.00.
MICRO = 1_000_000


@dataclass(frozen=True)
class Leg:
    token_id: str
    side: str          # "BUY" (acquires) | "SELL" (disposes)
    price_micro: int
    size_micro: int
    is_taker: bool


def _leg(row: Mapping[str, Any], *, is_taker: bool) -> Leg:
    kind = row["MATCH_KIND"] or "NORMAL"
    price = int(row["PRICE"])          # always the MAKER's price
    asset = row["ASSET_ID"]
    maker_asset = row["MAKER_ASSET_ID"] or asset
    if kind == "MINT":
        side = "BUY"
    elif kind == "MERGE":
        side = "SELL"
    else:
        # One token, opposite directions, one price.
        side = row["SIDE"] if is_taker else (
            "SELL" if row["SIDE"] == "BUY" else "BUY"
        )
    if is_taker:
        token = asset
        # The pair costs $1: the maker put up `price`, so the taker put up the
        # rest. NORMAL keeps the single price both parties agreed on.
        if kind in ("MINT", "MERGE"):
            price = MICRO - price
    else:
        token = asset if kind == "NORMAL" else maker_asset
    return Leg(
        token_id=token,
        side=side,
        price_micro=price,
        size_micro=int(row["TRADE_SIZE"]),
        is_taker=is_taker,
    )


def legs_for_user(row: Mapping[str, Any], api_key: str) -> list[Leg]:
    """Every leg of `row` that `api_key` holds, newest-first order irrelevant.

    Usually one. Two when the account is on BOTH sides: the matcher has no
    same-account guard, so a resting order of theirs can be crossed by their
    own later order, and both legs are real.
    """
    legs: list[Leg] = []
    if row["TAKER_API_KEY"] == api_key:
        legs.append(_leg(row, is_taker=True))
    if row["MAKER_API_KEY"] == api_key:
        legs.append(_leg(row, is_taker=False))
    return legs
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/datastructures/test_match_leg.py -q`
Expected: PASS, 6 tests. If `tests/datastructures/` has no `__init__.py` while its sibling test packages do, add an empty one to match.

- [ ] **Step 5: Make `_token_flow` read the shared rule**

In `agentpit/services/account_service.py`, `_token_flow` currently inlines the same truth table. Replace its per-row body so the rule lives in one place. Keep the method's signature, the SQL, and `_TokenFlow` exactly as they are — only the loop changes:

```python
        for r in rows:
            for leg in legs_for_user(r, api_key):
                if leg.token_id != token_id:
                    continue
                if leg.side == "BUY":
                    bought_size += leg.size_micro
                    bought_cost += leg.price_micro * leg.size_micro
                else:
                    sold_size += leg.size_micro
                    sold_proceeds += leg.price_micro * leg.size_micro
                    last_sell_time = max(last_sell_time, int(r["MATCH_TIME"] or 0))
```

Add `from agentpit.datastructures.match_leg import legs_for_user` to the imports. Rewrite the docstring's truth table to say it now lives in `match_leg`, and keep the paragraph explaining why the query ORs the two api_key branches.

The `if leg.token_id != token_id: continue` guard is load-bearing: the SQL already scopes rows to the token, but a self-matched MINT row matches on both branches while only one of its legs moves this token.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. `tests/services/test_mint_merge_accounting.py`, `tests/db/test_cost_basis.py` and `tests/services/test_closed_positions.py` all exercise `_token_flow`; they must pass UNCHANGED. This step is the proof the extraction is behaviour-preserving. If one fails, the extraction is wrong — read the failure, do not adjust an assertion.

- [ ] **Step 7: Commit**

```bash
git add agentpit/datastructures/match_leg.py tests/datastructures/ \
        agentpit/services/account_service.py
git commit -m "refactor(trades): one definition of what a user's leg is"
```

---

### Task 2: The price-print CTE and its indexes

**Files:**
- Modify: `agentpit/db/table_read.py` (add a module-level constant near the top, after the imports)
- Modify: `agentpit/db/table_create.py` (`create_trades_table`, beside `idx_trades_unlabelled`)
- Test: `tests/db/test_token_prints.py`

**Interfaces:**
- Consumes: `MICRO` from `agentpit.datastructures.match_leg` (Task 1).
- Produces: `TableRead.TOKEN_PRINTS_CTE: str` — a `WITH prints AS (...)` prefix taking exactly TWO parameters, both the SAME list of token ids. Callers append their own `SELECT ... FROM prints`. Tasks 3 and 4 consume it.

**Why the CTE takes the token list twice:** the predicate is pushed into each UNION branch so both can use an index. A single filter over the union would seq-scan 458k rows.

- [ ] **Step 1: Write the failing test**

Create `tests/db/test_token_prints.py`:

```python
"""A price print is "this token traded at this price".

A NORMAL match yields exactly ONE print — both parties trade the same token at
the same price, and emitting both legs would double every chart point and every
volume figure derived from the tape. A MINT/MERGE yields TWO, on different
tokens, whose prices sum to MICRO.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from agentpit.datastructures.match_leg import MICRO, legs_for_user
from agentpit.db.table_read import TableRead
from tests.db_helpers import fresh_test_conn


@pytest.fixture()
def db() -> Any:
    conn = fresh_test_conn()
    yield conn
    conn.close()


def _trade(db, *, asset, maker_asset, kind, side, price, size=100, t=1000):
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, MAKER_ASSET_ID, MATCH_KIND, "
        "SIDE, PRICE, TRADE_SIZE, STATUS, MATCH_TIME, TAKER_API_KEY, "
        "MAKER_API_KEY) VALUES (%s,%s,%s,%s,%s,%s,%s,'matched',%s,'tk','mk')",
        (uuid.uuid4().hex, asset, maker_asset, kind, side, price, size, t),
    )


def _prints(db, tokens):
    rows = db.execute(
        TableRead.TOKEN_PRINTS_CTE
        + "SELECT TOKEN_ID, MATCH_TIME, PRICE, TRADE_SIZE, SIDE FROM prints "
          "ORDER BY TOKEN_ID, MATCH_TIME",
        (list(tokens), list(tokens)),
    ).fetchall()
    return [(r["TOKEN_ID"], int(r["PRICE"]), r["SIDE"]) for r in rows]


def test_a_normal_match_yields_exactly_one_print(db):
    """The double-counting trap: a NORMAL maker trades the SAME token at the
    SAME price, so its leg is not a second print."""
    _trade(db, asset="y", maker_asset="y", kind="NORMAL", side="BUY", price=250_000)
    assert _prints(db, ["y", "n"]) == [("y", 250_000, "BUY")]


def test_a_mint_yields_a_print_on_each_token_summing_to_one_dollar(db):
    _trade(db, asset="y", maker_asset="n", kind="MINT", side="BUY", price=300_000)
    got = _prints(db, ["y", "n"])
    assert got == [("n", 300_000, "BUY"), ("y", 700_000, "BUY")]
    assert sum(p for _, p, _ in got) == MICRO


def test_a_merge_prints_a_sell_on_each_token(db):
    _trade(db, asset="y", maker_asset="n", kind="MERGE", side="SELL", price=400_000)
    got = _prints(db, ["y", "n"])
    assert got == [("n", 400_000, "SELL"), ("y", 600_000, "SELL")]


def test_a_null_match_kind_takes_the_normal_path(db):
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, SIDE, PRICE, TRADE_SIZE, "
        "STATUS, MATCH_TIME) VALUES (%s,'y','BUY',250000,100,'matched',1000)",
        (uuid.uuid4().hex,),
    )
    assert _prints(db, ["y"]) == [("y", 250_000, "BUY")]


def test_a_failed_trade_never_prints(db):
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, MAKER_ASSET_ID, MATCH_KIND, "
        "SIDE, PRICE, TRADE_SIZE, STATUS, MATCH_TIME) "
        "VALUES (%s,'y','n','MINT','BUY',300000,100,'FAILED',1000)",
        (uuid.uuid4().hex,),
    )
    assert _prints(db, ["y", "n"]) == []


def test_the_sql_and_the_python_truth_table_agree(db):
    """The two representations encode the same domain in two languages. This
    is what stops them drifting — silently, months from now."""
    cases = [
        ("NORMAL", "BUY", 250_000, "y"),
        ("NORMAL", "SELL", 250_000, "y"),
        ("MINT", "BUY", 300_000, "n"),
        ("MERGE", "SELL", 400_000, "n"),
    ]
    for kind, side, price, maker_asset in cases:
        db.execute("DELETE FROM trades")
        _trade(db, asset="y", maker_asset=maker_asset, kind=kind, side=side,
               price=price)
        row = db.execute(
            "SELECT TAKER_API_KEY, MAKER_API_KEY, ASSET_ID, MAKER_ASSET_ID, "
            "MATCH_KIND, SIDE, PRICE, TRADE_SIZE FROM trades"
        ).fetchone()
        # Every leg the SQL prints must be a leg the truth table agrees with.
        by_token = {}
        for leg in legs_for_user(row, "tk") + legs_for_user(row, "mk"):
            by_token[leg.token_id] = (leg.price_micro, leg.side)
        for token, price_sql, side_sql in _prints(db, ["y", "n"]):
            assert by_token[token] == (price_sql, side_sql), (kind, token)


def test_both_token_columns_are_indexed(db):
    """Without these the tape seq-scans the whole table on every chart load —
    measured at 132 ms over 458k rows to return 21 points."""
    names = {
        r["INDEXNAME"]
        for r in db.execute(
            "SELECT indexname AS INDEXNAME FROM pg_indexes WHERE tablename='trades'"
        ).fetchall()
    }
    assert "idx_trades_asset_id" in names
    assert "idx_trades_maker_asset_id" in names
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/db/test_token_prints.py -q`
Expected: FAIL — `AttributeError: type object 'TableRead' has no attribute 'TOKEN_PRINTS_CTE'`.

- [ ] **Step 3: Add the CTE**

In `agentpit/db/table_read.py`, inside `class TableRead`, before the first method:

```python
    #: One price print per (match, token): "this token traded at this price".
    #:
    #: The taker branch covers every non-failed row; the maker branch fires
    #: ONLY for MINT/MERGE, because a NORMAL maker trades the same token at
    #: the same price and its leg is not a second print. Emitting it would
    #: double every chart point and every tape-derived volume, silently.
    #:
    #: For a MINT/MERGE the stored PRICE is the maker's, so the taker's token
    #: printed at MICRO - PRICE and the maker's at PRICE — summing to the $1
    #: the pair costs or returns.
    #:
    #: Takes TWO parameters, both the SAME list of token ids: the predicate is
    #: pushed into each branch so both use an index. One filter over the union
    #: would seq-scan the whole table.
    #:
    #: Append your own `SELECT ... FROM prints`.
    TOKEN_PRINTS_CTE = """
        WITH prints AS (
            SELECT ASSET_ID AS TOKEN_ID, MATCH_TIME, TRADE_SIZE,
                   CASE WHEN COALESCE(MATCH_KIND, 'NORMAL') IN ('MINT', 'MERGE')
                        THEN 1000000 - PRICE ELSE PRICE END AS PRICE,
                   CASE WHEN COALESCE(MATCH_KIND, 'NORMAL') = 'MINT' THEN 'BUY'
                        WHEN COALESCE(MATCH_KIND, 'NORMAL') = 'MERGE' THEN 'SELL'
                        ELSE SIDE END AS SIDE
            FROM trades
            WHERE STATUS != 'FAILED' AND ASSET_ID = ANY(%s)
            UNION ALL
            SELECT MAKER_ASSET_ID, MATCH_TIME, TRADE_SIZE, PRICE,
                   CASE WHEN MATCH_KIND = 'MINT' THEN 'BUY' ELSE 'SELL' END
            FROM trades
            WHERE STATUS != 'FAILED' AND MATCH_KIND IN ('MINT', 'MERGE')
              AND MAKER_ASSET_ID IS NOT NULL AND MAKER_ASSET_ID = ANY(%s)
        )
    """
```

- [ ] **Step 4: Add the indexes**

In `agentpit/db/table_create.py`, in `create_trades_table`, immediately after the `idx_trades_unlabelled` block:

```python
        # The price tape looks a token up by BOTH columns — the taker's leg on
        # ASSET_ID and, for a MINT/MERGE, the maker's on MAKER_ASSET_ID.
        # Neither was indexed: production measured a 132 ms parallel seq scan
        # over 458k rows to return 21 chart points, on every chart load.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_asset_id ON trades(ASSET_ID)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_maker_asset_id "
            "ON trades(MAKER_ASSET_ID)"
        )
```

DDL at startup is fine. A data migration at startup is NOT — see `scripts/backfill_trade_match_kind.py` for why. This change needs no migration.

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/db/test_token_prints.py -q`
Expected: PASS, 7 tests.

- [ ] **Step 6: Commit**

```bash
git add agentpit/db/table_read.py agentpit/db/table_create.py \
        tests/db/test_token_prints.py
git commit -m "feat(trades): one price print per token a match moved"
```

---

### Task 3: The price tape reads prints

**Files:**
- Modify: `agentpit/services/order_service.py:470` (`get_book`'s last trade), `:547-552` (`/prices-history`), `:596-604` (`get_last_trade_price`)
- Modify: `agentpit/db/table_read.py:984-996` (`last_trade_prices_for_tokens`)
- Modify: `agentpit/services/account_service.py:517-522` (`_cur_price`)
- Test: `tests/services/test_match_leg_consumers.py`

**Interfaces:**
- Consumes: `TableRead.TOKEN_PRINTS_CTE` (Task 2). Two parameters, both the same list.
- Produces: no new API. Every signature and return shape is unchanged; only the numbers change.

- [ ] **Step 1: Write the failing test**

Create `tests/services/test_match_leg_consumers.py`:

```python
"""The read paths that still told a MINT's story with the wrong token or the
wrong price. The money was already right — this is the narration of it."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from agentpit.db.table_read import TableRead
from tests.db_helpers import fresh_test_conn


@pytest.fixture()
def db() -> Any:
    conn = fresh_test_conn()
    yield conn
    conn.close()


def _mint(db, *, asset="y", maker_asset="n", price=300_000, t=1000, size=100):
    """A MINT: taker BUYs `asset` at MICRO-price, maker BUYs `maker_asset` at
    price. The stored PRICE is the maker's."""
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, MAKER_ASSET_ID, MATCH_KIND, "
        "SIDE, PRICE, TRADE_SIZE, STATUS, MATCH_TIME, TAKER_API_KEY, "
        "MAKER_API_KEY) VALUES (%s,%s,%s,'MINT','BUY',%s,%s,'matched',%s,"
        "'tk','mk')",
        (uuid.uuid4().hex, asset, maker_asset, price, size, t),
    )


def test_the_batched_last_price_marks_the_taker_token_at_its_own_price(db):
    _mint(db, price=300_000)
    got = TableRead.last_trade_prices_for_tokens(db, ["y", "n"])
    assert got["y"] == 700_000
    assert got["n"] == 300_000, "the complement had no print at all before"


def test_the_batched_last_price_is_unchanged_for_a_normal_match(db):
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, MAKER_ASSET_ID, MATCH_KIND, "
        "SIDE, PRICE, TRADE_SIZE, STATUS, MATCH_TIME) "
        "VALUES (%s,'y','y','NORMAL','BUY',250000,100,'matched',1000)",
        (uuid.uuid4().hex,),
    )
    assert TableRead.last_trade_prices_for_tokens(db, ["y", "n"]) == {"y": 250_000}


def test_the_newest_print_wins_across_both_legs(db):
    """A later MINT on the complement must beat an earlier print on this
    token — the maker branch has to take part in the DISTINCT ON."""
    _mint(db, asset="a", maker_asset="b", price=200_000, t=1000)
    _mint(db, asset="b", maker_asset="a", price=900_000, t=2000)
    got = TableRead.last_trade_prices_for_tokens(db, ["a"])
    # At t=2000 token "a" was the MAKER's token, priced at the stored PRICE.
    assert got["a"] == 900_000
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/services/test_match_leg_consumers.py -q`
Expected: FAIL — `KeyError: 'n'` on the first test: the complement has no row today.

- [ ] **Step 3: Rewrite `last_trade_prices_for_tokens`**

In `agentpit/db/table_read.py`, replace the body of `last_trade_prices_for_tokens` (keep the signature and docstring intent):

```python
    @staticmethod
    def last_trade_prices_for_tokens(
        db: psycopg.Connection, token_ids: "list[str]"
    ) -> "dict[str, int]":
        """Most-recent price print per token, batched.

        Reads prints rather than raw rows: a MINT prints on BOTH tokens, and
        the complement's price is the one the maker actually paid.
        """
        if not token_ids:
            return {}
        ids = list(token_ids)
        rows = db.execute(
            TableRead.TOKEN_PRINTS_CTE
            + "SELECT DISTINCT ON (TOKEN_ID) TOKEN_ID, PRICE FROM prints "
              "ORDER BY TOKEN_ID, MATCH_TIME DESC",
            (ids, ids),
        ).fetchall()
        return {r["TOKEN_ID"]: int(r["PRICE"]) for r in rows}
```

- [ ] **Step 4: Rewrite the three `order_service` readers**

`get_book`'s last trade, at `agentpit/services/order_service.py:470`:

```python
            last = conn.execute(
                TableRead.TOKEN_PRINTS_CTE
                + "SELECT PRICE FROM prints ORDER BY MATCH_TIME DESC LIMIT 1",
                ([token_id], [token_id]),
            ).fetchone()
```

`/prices-history`, at `:547-552`:

```python
            rows = conn.execute(
                TableRead.TOKEN_PRINTS_CTE
                + "SELECT MATCH_TIME, PRICE FROM prints "
                  "WHERE MATCH_TIME >= %s AND MATCH_TIME <= %s "
                  "ORDER BY MATCH_TIME ASC",
                ([token_id], [token_id], start, end),
            ).fetchall()
```

`get_last_trade_price`, at `:596-604`:

```python
            row = conn.execute(
                TableRead.TOKEN_PRINTS_CTE
                + "SELECT PRICE, SIDE FROM prints ORDER BY MATCH_TIME DESC LIMIT 1",
                ([token_id], [token_id]),
            ).fetchone()
```

Parameter order matters: the CTE's two placeholders come FIRST, then the outer query's own. Add `from agentpit.db.table_read import TableRead` if `order_service.py` does not already import it — check before adding.

- [ ] **Step 5: Rewrite `_cur_price`'s fallback**

In `agentpit/services/account_service.py`, replace only the `last = ...` query inside `_cur_price` (lines 517-521). The book-midpoint branch above it is unchanged:

```python
        last = conn.execute(
            TableRead.TOKEN_PRINTS_CTE
            + "SELECT PRICE FROM prints ORDER BY MATCH_TIME DESC LIMIT 1",
            ([token_id], [token_id]),
        ).fetchone()
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/services/test_match_leg_consumers.py -q`
Expected: PASS, 3 tests.

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. Existing chart and pricing tests write no `MATCH_KIND`, so they take the NORMAL path and their numbers are unchanged. If one fails, read the failure — do not adjust an assertion.

- [ ] **Step 7: Commit**

```bash
git add agentpit/services/order_service.py agentpit/db/table_read.py \
        agentpit/services/account_service.py \
        tests/services/test_match_leg_consumers.py
git commit -m "fix(prices): the tape prints every token a match moved"
```

---

### Task 4: The Activity feed shows the account's own leg

**Files:**
- Modify: `agentpit/services/account_service.py:407-459` (`list_activity`)
- Test: `tests/services/test_match_leg_consumers.py` (append)

**Interfaces:**
- Consumes: `legs_for_user` (Task 1).
- Produces: no API change. `ActivityWire` gains no field and no new `type`.

**Decided in the spec:** a maker's MINT renders as an ordinary `TRADE` with the correct token, direction and price — not a new event type.

- [ ] **Step 1: Write the failing test**

Append to `tests/services/test_match_leg_consumers.py`:

```python
# ----- the activity feed ------------------------------------------------------

from agentpit.datastructures.condition_id import ConditionId  # noqa: E402
from agentpit.datastructures.create_market_request import (  # noqa: E402
    CreateMarketRequest,
)
from agentpit.datastructures.market_state import MarketState  # noqa: E402
from agentpit.db.table_write import TableWrite  # noqa: E402


def _market(db, seed="act"):
    return TableWrite.create_market(
        db,
        CreateMarketRequest(
            question=f"{seed}?",
            description="d",
            erc1155_tokens=[(f"{seed}-y", "Yes"), (f"{seed}-n", "No")],
            slug=seed,
            condition_id=ConditionId("0x" + seed.encode().hex().ljust(64, "0")[:64]),
            state=MarketState.ACTIVE,
        ),
        is_polygon_market=False,
    )


def _activity_rows(db, api_key, eth_address):
    """The trade half of list_activity, exercised through the same code."""
    from agentpit.services.account_service import AccountService
    return AccountService._trade_activity(db, api_key, eth_address)


def test_a_mint_makers_activity_names_the_token_it_received(db):
    m = _market(db, "act")
    db.execute(
        "INSERT INTO trades (TRADE_ID, MARKET, ASSET_ID, MAKER_ASSET_ID, "
        "MATCH_KIND, SIDE, PRICE, TRADE_SIZE, STATUS, MATCH_TIME, "
        "TAKER_API_KEY, MAKER_API_KEY) "
        "VALUES (%s,%s,'act-y','act-n','MINT','BUY',300000,100,'matched',10,"
        "'tk','mk')",
        (uuid.uuid4().hex, m.condition_id.value),
    )
    acts = _activity_rows(db, "mk", "0xmaker")
    assert len(acts) == 1
    a = acts[0]
    assert a.asset == "act-n", "the maker received the OTHER outcome"
    assert a.side == "BUY", "both sides of a mint ACQUIRE"
    assert a.price == 0.3, "the stored price IS the maker's"
    assert a.outcome == "No"
    assert a.usdcSize == pytest.approx(0.3 * a.size)


def test_the_mint_taker_sees_the_complement_of_the_stored_price(db):
    m = _market(db, "actt")
    db.execute(
        "INSERT INTO trades (TRADE_ID, MARKET, ASSET_ID, MAKER_ASSET_ID, "
        "MATCH_KIND, SIDE, PRICE, TRADE_SIZE, STATUS, MATCH_TIME, "
        "TAKER_API_KEY, MAKER_API_KEY) "
        "VALUES (%s,%s,'actt-y','actt-n','MINT','BUY',300000,100,'matched',10,"
        "'tk','mk')",
        (uuid.uuid4().hex, m.condition_id.value),
    )
    a = _activity_rows(db, "tk", "0xtaker")[0]
    assert a.asset == "actt-y"
    assert a.side == "BUY"
    assert a.price == 0.7


def test_a_self_matched_normal_row_shows_both_sides(db):
    """One account on both legs is the dominant shape on production."""
    m = _market(db, "acts")
    db.execute(
        "INSERT INTO trades (TRADE_ID, MARKET, ASSET_ID, MAKER_ASSET_ID, "
        "MATCH_KIND, SIDE, PRICE, TRADE_SIZE, STATUS, MATCH_TIME, "
        "TAKER_API_KEY, MAKER_API_KEY) "
        "VALUES (%s,%s,'acts-y','acts-y','NORMAL','BUY',250000,100,'matched',"
        "10,'same','same')",
        (uuid.uuid4().hex, m.condition_id.value),
    )
    acts = _activity_rows(db, "same", "0xsame")
    assert sorted(a.side for a in acts) == ["BUY", "SELL"]
    assert {a.price for a in acts} == {0.25}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/services/test_match_leg_consumers.py -q -k activity or mint_maker`
Expected: FAIL — `AttributeError: type object 'AccountService' has no attribute '_trade_activity'`.

- [ ] **Step 3: Extract and rewrite the trade half of `list_activity`**

`list_activity` currently does the trade rows and the transaction rows in one method, which is why its trade half cannot be tested without the whole service. Extract the trade half into a static method on `AccountService`, and have `list_activity` call it. Keep the transaction half exactly where it is.

The new method — note the SELECT gains the three columns the truth table needs, and the loop iterates legs rather than rows:

```python
    @staticmethod
    def _trade_activity(conn, api_key: str, eth_address: str) -> "list[ActivityWire]":
        """One ActivityWire per leg this account holds.

        A NORMAL self-match yields two rows, a buy and a sell — that is the
        account genuinely standing on both sides. A MINT/MERGE maker's row
        names the token it actually received, not the taker's.
        """
        rows = conn.execute(
            "SELECT MARKET, ASSET_ID, MAKER_ASSET_ID, MATCH_KIND, SIDE, PRICE, "
            "TRADE_SIZE, MATCH_TIME, TRANSACTION_HASH, TAKER_API_KEY, "
            "MAKER_API_KEY FROM trades "
            "WHERE (TAKER_API_KEY = %s OR MAKER_API_KEY = %s) AND STATUS != 'FAILED'",
            (api_key, api_key),
        ).fetchall()

        acts: list[ActivityWire] = []
        slug_cache: dict[int, str] = {}

        def event_slug_of(mkt) -> str:
            if mkt is None or mkt.event_id is None:
                return ""
            if mkt.event_id not in slug_cache:
                found = TableRead.event_slugs_by_id(conn, [mkt.event_id])
                slug_cache[mkt.event_id] = found.get(mkt.event_id, "")
            return slug_cache[mkt.event_id]

        for r in rows:
            for leg in legs_for_user(r, api_key):
                # Resolve the token THIS leg moved, not the row's ASSET_ID:
                # they differ for a MINT/MERGE maker, and the outcome label
                # and index have to follow the corrected token.
                resolved = resolve_by_token_id(conn, leg.token_id)
                mkt = resolved.market if resolved else None
                price = price_to_float(leg.price_micro)
                size = size_to_float(leg.size_micro)
                outcome = (
                    mkt.erc1155_tokens[resolved.outcome_index][1]
                    if resolved and mkt else ""
                )
                acts.append(ActivityWire(
                    proxyWallet=eth_address,
                    timestamp=int(r["MATCH_TIME"] or 0),
                    conditionId=r["MARKET"],
                    type="TRADE",
                    size=size,
                    usdcSize=price * size,
                    transactionHash=r["TRANSACTION_HASH"] or "",
                    price=price,
                    asset=leg.token_id,
                    side=leg.side,
                    outcomeIndex=resolved.outcome_index if resolved else 0,
                    title=mkt.question if mkt else "",
                    slug=(mkt.slug or "") if mkt else "",
                    icon=(mkt.icon_url or "") if mkt else "",
                    eventSlug=event_slug_of(mkt),
                    outcome=outcome,
                ))
        return acts
```

In `list_activity`, delete the `trade_rows` query and the `for r in trade_rows:` block (and the now-duplicated `slug_cache` / `event_slug_of` if the transaction half does not use them — check before deleting), and start the list with:

```python
            acts: list[ActivityWire] = AccountService._trade_activity(
                conn, user.api_key, eth_address
            )
```

Keep every existing sort, filter and truncation that follows the two loops exactly as it is.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/services/test_match_leg_consumers.py -q`
Expected: PASS, 6 tests.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. Existing activity tests write no `MATCH_KIND`; a NORMAL row where the user is one party still yields exactly one entry.

Note the one intended behaviour change to look for: a NORMAL row where the user is BOTH taker and maker now yields TWO entries where it used to yield one. That is correct — the account did both — but if an existing test asserts a count over self-matched fixtures, read it carefully before deciding.

- [ ] **Step 6: Commit**

```bash
git add agentpit/services/account_service.py tests/services/test_match_leg_consumers.py
git commit -m "fix(activity): show the leg the account actually took"
```

---

### Task 5: `/data/trades` stops dropping your own maker fills

**Files:**
- Modify: `agentpit/db/table_read.py:1139-1150` (`list_trades_for_api_key`)
- Modify: `agentpit/services/trade_service.py:46-77`
- Test: `tests/services/test_match_leg_consumers.py` (append)

**Interfaces:**
- Consumes: `legs_for_user` (Task 1).
- Produces: no API change. `TradeWire`'s fields are unchanged; `asset_id` and `price` become correct for the MAKER perspective.

**The bug in one line:** the `asset_id` filter matches `ASSET_ID` only, so asking for your own MINT/MERGE token silently omits the fill. And the projection already flips `side` and `outcome` for the maker while emitting the taker's `asset_id` — the file contradicts itself.

**Careful:** `PRICE` IS the maker's price. The MAKER perspective must NOT flip it. Only the TAKER's price flips, and only on MINT/MERGE.

**A third defect in the same block.** `outcome` is taken from `maker_orders[0].outcome` for BOTH perspectives — the maker's own outcome label. For a NORMAL match that is the same token and so the same label, which is why nobody noticed. For a MINT the taker is handed the COMPLEMENT's label. `outcome` must follow the leg's token, exactly as the Activity feed does, which means the projection needs a connection to resolve it.

- [ ] **Step 1: Write the failing test**

Append to `tests/services/test_match_leg_consumers.py`:

```python
# ----- /data/trades -----------------------------------------------------------


def _mint_row(db, condition_id):
    db.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_ORDER_ID, MAKER_ORDERS, MARKET, "
        "ASSET_ID, MAKER_ASSET_ID, MATCH_KIND, SIDE, PRICE, TRADE_SIZE, "
        "STATUS, MATCH_TIME, BUCKET_INDEX, FEE_RATE_BPS, TAKER_API_KEY, "
        "MAKER_API_KEY) VALUES (%s,'o','[]',%s,'dt-y','dt-n','MINT','BUY',"
        "300000,100,'matched',10,0,0,'tk','mk')",
        (uuid.uuid4().hex, condition_id),
    )


def test_filtering_by_your_own_token_finds_your_maker_fill(db):
    m = _market(db, "dt")
    _mint_row(db, m.condition_id.value)
    rows = TableRead.list_trades_for_api_key(db, "mk", asset_id="dt-n")
    assert len(rows) == 1, "the maker's own token used to match nothing"


def test_the_taker_filter_is_unaffected(db):
    m = _market(db, "dt")
    _mint_row(db, m.condition_id.value)
    assert len(TableRead.list_trades_for_api_key(db, "tk", asset_id="dt-y")) == 1
    assert TableRead.list_trades_for_api_key(db, "tk", asset_id="dt-n") == []


def test_the_maker_perspective_reports_its_own_token_at_its_own_price(db):
    from agentpit.services.trade_service import TradeService
    m = _market(db, "dt")
    _mint_row(db, m.condition_id.value)
    rows = TableRead.list_trades_for_api_key(db, "mk")
    wire = TradeService._to_wire(db, rows[0], api_key="mk", user_id=1,
                                 eth_address="0xmaker")
    assert wire.asset_id == "dt-n"
    assert wire.price == "0.3", "PRICE is already the maker's — do not flip it"
    assert wire.side == "BUY"
    assert wire.outcome == "No"
    assert wire.trader_side == "MAKER"


def test_the_taker_perspective_flips_the_price_and_keeps_its_own_outcome(db):
    from agentpit.services.trade_service import TradeService
    m = _market(db, "dt")
    _mint_row(db, m.condition_id.value)
    rows = TableRead.list_trades_for_api_key(db, "tk")
    wire = TradeService._to_wire(db, rows[0], api_key="tk", user_id=2,
                                 eth_address="0xtaker")
    assert wire.asset_id == "dt-y"
    assert wire.price == "0.7"
    assert wire.outcome == "Yes", "used to report the maker's outcome label"
    assert wire.trader_side == "TAKER"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/services/test_match_leg_consumers.py -q -k trades`
Expected: FAIL — the first test finds 0 rows.

- [ ] **Step 3: Widen the filter and the projection**

In `agentpit/db/table_read.py`, `list_trades_for_api_key`, replace the `asset_id` clause:

```python
        if asset_id is not None:
            # Either leg: a MINT/MERGE maker's own token is MAKER_ASSET_ID,
            # and filtering on ASSET_ID alone dropped their fill entirely.
            clauses.append("(ASSET_ID = %s OR COALESCE(MAKER_ASSET_ID, ASSET_ID) = %s)")
            params.append(asset_id); params.append(asset_id)
```

and add the two columns the truth table needs to the SELECT list:

```python
            "SELECT TRADE_ID, TAKER_ORDER_ID, MAKER_ORDERS, MARKET, ASSET_ID, "
            "MAKER_ASSET_ID, MATCH_KIND, "
            "PRICE, TRADE_SIZE, SIDE, STATUS, MATCH_TIME, TRANSACTION_HASH, "
            "BUCKET_INDEX, FEE_RATE_BPS, TAKER_API_KEY, MAKER_API_KEY "
```

- [ ] **Step 4: Extract `_to_wire` in `trade_service.py`**

The per-row projection is currently inline in `list_trades`, which is why it cannot be tested without a `DbSession`. Extract it to a static method and have `list_trades` call it. Signature:

```python
    @staticmethod
    def _to_wire(
        conn, r, *, api_key: str, user_id: int, eth_address: str
    ) -> TradeWire:
```

`conn` is needed to resolve the outcome label of the leg's own token — see the third defect above.

Inside, replace the perspective block. `legs_for_user` returns both legs when the account is on both sides; `/data/trades` is a per-row API, so take the leg matching `trader_side`:

```python
        trader_side = "TAKER" if r["TAKER_API_KEY"] == api_key else "MAKER"
        legs = legs_for_user(r, api_key)
        leg = next(
            (x for x in legs if x.is_taker == (trader_side == "TAKER")), legs[0]
        )
        makers_raw = json.loads(r["MAKER_ORDERS"]) if r["MAKER_ORDERS"] else []
        maker_orders = [ ... this list comprehension is unchanged ... ]
        # The outcome label follows the token THIS leg moved. It used to come
        # from maker_orders[0] for both perspectives, which handed a MINT's
        # taker the complement's label.
        resolved = resolve_by_token_id(conn, leg.token_id)
        outcome = (
            resolved.market.erc1155_tokens[resolved.outcome_index][1]
            if resolved and resolved.market else ""
        )
```

and in the `TradeWire(...)` construction use the leg for the three fields that were wrong, plus `owner=user_id` and `maker_address=eth_address` where the old code read them off `user`:

```python
                    asset_id=leg.token_id,
                    side=leg.side,
                    price=price_to_decimal_str(leg.price_micro),
```

Everything else in the construction is unchanged. Add these imports:

```python
from agentpit.datastructures.match_leg import legs_for_user
from agentpit.polymarket.resolve import resolve_by_token_id
```

`list_trades` becomes:

```python
    def list_trades(self, user: User, *, limit: int = 100, **filters) -> TradesEnvelope:
        with self._db.read() as conn:
            rows = TableRead.list_trades_for_api_key(conn, user.api_key, **filters)
            trades = [
                TradeService._to_wire(
                    conn, r, api_key=user.api_key, user_id=user.user_id,
                    eth_address=user.eth_address,
                )
                for r in rows
            ]
        page = trades[:limit]
        return TradesEnvelope(limit=limit, count=len(page), data=page)
```

Note the list comprehension moves INSIDE the `with` block — `_to_wire` now needs the connection.

Keep the existing comment about `next_cursor` being a static sentinel where it is.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/services/test_match_leg_consumers.py -q`
Expected: PASS, 10 tests.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. Existing `/data/trades` tests write no `MATCH_KIND`, so both perspectives take the NORMAL path: the maker's leg is the same token at the same price with the opposite side — exactly what the old code produced.

- [ ] **Step 7: Commit**

```bash
git add agentpit/db/table_read.py agentpit/services/trade_service.py \
        tests/services/test_match_leg_consumers.py
git commit -m "fix(trades api): a maker's fill reports its own token and price"
```

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task. §A (price prints) → Task 2 defines them, Task 3 makes all five tape sites read them. §B (user legs) → Task 1 defines them and proves the definition by making `_token_flow` adopt it, Tasks 4 and 5 make the two per-user sites read them. §Indexes → Task 2. §Testing's three invariants → Task 2 Steps 1 (`test_a_normal_match_yields_exactly_one_print`, `test_a_mint_yields_a_print_on_each_token_summing_to_one_dollar`, `test_the_sql_and_the_python_truth_table_agree`). §Out of scope is enforced by the Global Constraints line forbidding matcher changes.

**Placeholders.** None. Every code step carries the code; every test step carries the assertions; the one `... unchanged ...` in Task 5 Step 4 points at a block the implementer is explicitly told not to modify, in the file they have open.

**One defect found while writing this, folded into Task 5.** `trade_service.py` reads `outcome` from `maker_orders[0]` for BOTH perspectives, so a MINT's taker is handed the complement's outcome label. It hid because a NORMAL match's two legs share a token and therefore a label. Fixing it is what forces `_to_wire` to take a connection.

**Type consistency.** `Leg` is defined in Task 1 with fields `token_id`, `side`, `price_micro`, `size_micro`, `is_taker`, and Tasks 3-5 use exactly those names. `legs_for_user(row, api_key)` keeps that argument order everywhere. `TOKEN_PRINTS_CTE` is defined in Task 2 as a class attribute of `TableRead` and referenced as `TableRead.TOKEN_PRINTS_CTE` in Tasks 3; its columns are `TOKEN_ID, MATCH_TIME, TRADE_SIZE, PRICE, SIDE` and every consumer selects from that set. `MICRO` is defined once, in `match_leg.py`; the CTE spells `1000000` literally because SQL cannot import it, and Task 2's test asserts the two agree.

**Ordering risk, flagged deliberately.** Task 1 changes `_token_flow`, which the previous branch shipped to production last night. Task 1 Step 6 is the guard: the existing position tests must pass untouched, or the extraction is not behaviour-preserving.
