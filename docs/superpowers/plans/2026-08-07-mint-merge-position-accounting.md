# MINT/MERGE Position Accounting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an account's holdings and realized P&L reconstructable from the trade history, so the Arena's Invested and Realized P/L columns stop being wrong for anyone who mints or merges.

**Architecture:** A trade row records one `ASSET_ID` — the taker's. For a NORMAL match both parties transact in that token, so one id suffices. For a MINT (both sides buying) and a MERGE (both sides selling) the maker's token is the market's OTHER outcome, and today nothing records it — `_insert_trade` even writes the taker's id into the maker payload. This adds the maker's real token and the match kind to the row, backfills both for existing rows (derivable), and rewrites the flow reader to attribute each leg to the token that party actually moved.

**Tech Stack:** Python 3.13, FastAPI, psycopg3 + Postgres.

## The evidence this fixes

Measured on production for `RichChilliPine` (460 trades, the only account that mints):

```
token             net by trades    on chain      gap
15988202205565…        -55,142           0    +55,142
75264874349915…        +45,052      91,527    +46,475
11001445524949…        -23,578           0    +23,578

total on chain 227,351 shares   |   net-bought by trades 170,777
```

Trade nets go NEGATIVE — the table says the account sold more than it bought, which cannot happen — and 56,574 shares exist on chain with no buy fill behind them. Both are the same artefact: a mint gives the maker a token no row mentions, and a merge burns one.

Consequences on the board: `Invested` multiplies a per-token average by an on-chain balance the trade history cannot explain (a token acquired as a mint maker has no buy rows at all, so its average is 0 and its cost basis reads as $0), and `Realized P/L` is derived as a residual from `Invested`, so it inherits the error amplified. Realized for that account shows $2,855 where a direct reconstruction gives $21,638; two $0 redeems account for only $667 of the $18,116 gap.

## The model this establishes

The stored `PRICE` is always the MAKER's price (`order_service.py`, `_match` builds each match with `"price": int(maker["PRICE"])`). Per leg:

| kind | taker | maker |
| --- | --- | --- |
| NORMAL | asset A, at price p, direction = its own side | asset A, at price p, opposite direction |
| MINT | asset A, ACQUIRES, pays `1 − p` | asset B (complement), ACQUIRES, pays `p` |
| MERGE | asset A, DISPOSES, receives `1 − p` | asset B (complement), DISPOSES, receives `p` |

A mint costs the pair exactly $1 and a merge returns exactly $1, which is why the two legs' prices sum to one.

## Global Constraints

- Branch is `mvp`. Work directly in the repo; no worktree.
- Backend tests: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`. **NEVER source `.env` before pytest** — `tests/conftest.py` uses `os.environ.setdefault`, so a sourced `.env` defeats every default and causes live-sync flakes.
- Every DDL statement must be idempotent (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) — `create_all_tables` runs on every app construction against the live database.
- All DB rows are dict-style and case-insensitive (`ci_dict_row`): `row["SLUG"]` and `row["slug"]` both work.
- `TableCreate`, `TableRead`, `TableWrite` are classes of `@staticmethod`s.
- `pyright` is NOT installed in `.venv`; use the global `pyright` binary WITH `--pythonversion 3.13` (`pyrightconfig.json` pins no version, so without the flag every `X | None` reads as a 3.10-syntax error).
- The match kind is derivable from the two sides and must agree with what the matcher decided: taker BUY + maker BUY → MINT; taker SELL + maker SELL → MERGE; anything else → NORMAL.
- **Never widen a test double or edit an assertion to make a failure go away.** If a test fails, read the failure.

---

## Task 1: Record the maker's real token and the match kind

**Files:**
- Modify: `agentpit/db/table_create.py` (`create_trades_table`)
- Modify: `agentpit/services/order_service.py` (`_insert_trade`)
- Test: `tests/services/test_mint_merge_accounting.py` (create)

**Interfaces:**
- Produces: `trades.MAKER_ASSET_ID TEXT` and `trades.MATCH_KIND TEXT`, both nullable; `_insert_trade` populates them on every new row.

- [ ] **Step 1: Write the failing test**

Create `tests/services/test_mint_merge_accounting.py`:

```python
"""A trade row must name BOTH tokens that moved.

One ASSET_ID is enough for a NORMAL match, where both parties transact in the
same token. A MINT gives the maker the market's OTHER outcome and a MERGE
burns it, and nothing recorded that — so an account that mints could not have
its holdings reconstructed from its own trade history.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from tests.db_helpers import fresh_test_conn


@pytest.fixture()
def db() -> Any:
    conn = fresh_test_conn()
    yield conn
    conn.close()


def test_the_trades_table_carries_both_tokens(db):
    """The columns exist and accept the two new values."""
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, MAKER_ASSET_ID, MATCH_KIND, "
        "SIDE, PRICE, TRADE_SIZE, STATUS) "
        "VALUES (%s, 'tok-a', 'tok-b', 'MINT', 'BUY', 400000, 100, 'matched')",
        (uuid.uuid4().hex,),
    )
    row = db.execute(
        "SELECT ASSET_ID, MAKER_ASSET_ID, MATCH_KIND FROM trades "
        "WHERE MATCH_KIND = 'MINT' LIMIT 1"
    ).fetchone()
    assert row["ASSET_ID"] == "tok-a"
    assert row["MAKER_ASSET_ID"] == "tok-b"
    assert row["MATCH_KIND"] == "MINT"


def test_the_columns_are_nullable_for_rows_written_before_they_existed(db):
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, SIDE, PRICE, TRADE_SIZE, STATUS) "
        "VALUES (%s, 'tok-a', 'BUY', 400000, 100, 'matched')",
        (uuid.uuid4().hex,),
    )
    row = db.execute(
        "SELECT MAKER_ASSET_ID, MATCH_KIND FROM trades WHERE ASSET_ID='tok-a' "
        "AND MATCH_KIND IS NULL LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["MAKER_ASSET_ID"] is None


def test_maker_orders_payload_names_the_maker_token_not_the_takers():
    """`_insert_trade` used to copy the TAKER's token into the maker payload.
    For a mint that is the wrong token entirely — it is the one asset the
    maker did NOT receive."""
    import inspect

    from agentpit.services.order_service import OrderService

    src = inspect.getsource(OrderService._insert_trade)
    assert '"asset_id": token_id' not in src, (
        "the maker payload still claims the taker's token"
    )
    assert "maker_asset_id" in src
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/services/test_mint_merge_accounting.py -q`
Expected: FAIL — `column "maker_asset_id" of relation "trades" does not exist`.

- [ ] **Step 3: Add the columns**

In `agentpit/db/table_create.py`, inside `create_trades_table`, after the existing statements:

```python
        # The token the MAKER moved. Equal to ASSET_ID for a NORMAL match, but
        # for a MINT the maker receives the market's other outcome and for a
        # MERGE it burns one — and with only the taker's id recorded, an
        # account's holdings could not be rebuilt from its own trades.
        conn.execute(
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS MAKER_ASSET_ID TEXT"
        )
        # NORMAL | MINT | MERGE. Derivable from the two sides, but stored so a
        # reader never has to re-derive the matcher's own decision.
        conn.execute(
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS MATCH_KIND TEXT"
        )
```

- [ ] **Step 4: Populate them on write**

In `agentpit/services/order_service.py`, in `_insert_trade`:

Read the current body first. `maker_row = match["maker_row"]` is already in scope and `match["match_kind"]` is already computed by `_match`. Derive the maker's token from the maker's own order row — never from the taker's:

```python
        # The maker's order is booked against ITS token, which for a
        # MINT/MERGE is the complement of the taker's. Reading it from the
        # maker row is what makes the leg reconstructable; copying `token_id`
        # here is the bug this replaces.
        maker_asset_id = maker_row["TOKEN_ID"]
        match_kind = match.get("match_kind", "NORMAL")
```

Use `maker_asset_id` in the `maker_orders_payload` entry in place of `token_id`, then add both columns to the INSERT's column list and values tuple.

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/services/test_mint_merge_accounting.py -q`
Expected: PASS, 3 tests.

- [ ] **Step 6: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add agentpit/db/table_create.py agentpit/services/order_service.py \
        tests/services/test_mint_merge_accounting.py
git commit -m "feat(trades): record the maker's token and the match kind"
```

---

## Task 2: Backfill the two columns for existing rows

**Files:**
- Modify: `agentpit/db/table_create.py` (`create_trades_table`, after the ALTERs)
- Test: `tests/services/test_mint_merge_accounting.py` (append)

**Interfaces:**
- Consumes: the two columns from Task 1.
- Produces: `TableCreate.backfill_trade_match_kind(conn)`, called from `create_trades_table` so it runs on startup; idempotent (it only touches rows where `MATCH_KIND IS NULL`).

**Why this is derivable rather than lost:** the kind follows from the two sides — the taker's is `SIDE`, the maker's is inside `MAKER_ORDERS`. Given the kind, the maker's token is `ASSET_ID` for NORMAL and the market's other outcome for MINT/MERGE, and `markets.ERC1155_TOKENS` still holds both.

- [ ] **Step 1: Write the failing test**

Append to `tests/services/test_mint_merge_accounting.py`:

```python
# ----- backfilling rows written before the columns existed --------------------

from agentpit.datastructures.condition_id import ConditionId  # noqa: E402
from agentpit.datastructures.create_market_request import (  # noqa: E402
    CreateMarketRequest,
)
from agentpit.datastructures.market_state import MarketState  # noqa: E402
from agentpit.db.table_create import TableCreate  # noqa: E402
from agentpit.db.table_write import TableWrite  # noqa: E402


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


def _binary_market(db, seed: str):
    """A two-outcome market whose tokens are `<seed>-y` and `<seed>-n`."""
    return TableWrite.create_market(
        db,
        CreateMarketRequest(
            question=f"{seed}?",
            description="d",
            erc1155_tokens=[(f"{seed}-y", "Yes"), (f"{seed}-n", "No")],
            slug=seed,
            condition_id=ConditionId(_hex32(seed)),
            state=MarketState.ACTIVE,
        ),
        is_polygon_market=False,
    )


def _legacy_trade(db, *, market, asset, taker_side, maker_side):
    """A row in the pre-column shape: no MAKER_ASSET_ID, no MATCH_KIND."""
    db.execute(
        "INSERT INTO trades (TRADE_ID, MARKET, ASSET_ID, SIDE, PRICE, "
        "TRADE_SIZE, STATUS, MAKER_ORDERS) "
        "VALUES (%s, %s, %s, %s, 400000, 100, 'matched', %s)",
        (
            uuid.uuid4().hex,
            market.condition_id.value,
            asset,
            taker_side,
            json.dumps([{"side": maker_side, "asset_id": asset}]),
        ),
    )


def _kinds(db):
    rows = db.execute(
        "SELECT ASSET_ID, MAKER_ASSET_ID, MATCH_KIND FROM trades "
        "WHERE MATCH_KIND IS NOT NULL ORDER BY ASSET_ID"
    ).fetchall()
    return [(r["ASSET_ID"], r["MAKER_ASSET_ID"], r["MATCH_KIND"]) for r in rows]


def test_backfill_labels_a_normal_match_and_keeps_one_token(db):
    m = _binary_market(db, "bfn")
    _legacy_trade(db, market=m, asset="bfn-y", taker_side="BUY", maker_side="SELL")
    TableCreate.backfill_trade_match_kind(db)
    assert _kinds(db) == [("bfn-y", "bfn-y", "NORMAL")]


def test_backfill_gives_a_mint_maker_the_complementary_token(db):
    """Both sides buying is a mint: the maker receives the OTHER outcome."""
    m = _binary_market(db, "bfm")
    _legacy_trade(db, market=m, asset="bfm-y", taker_side="BUY", maker_side="BUY")
    TableCreate.backfill_trade_match_kind(db)
    assert _kinds(db) == [("bfm-y", "bfm-n", "MINT")]


def test_backfill_gives_a_merge_maker_the_complementary_token(db):
    """Both sides selling is a merge: the maker burns the OTHER outcome."""
    m = _binary_market(db, "bfg")
    _legacy_trade(db, market=m, asset="bfg-n", taker_side="SELL", maker_side="SELL")
    TableCreate.backfill_trade_match_kind(db)
    assert _kinds(db) == [("bfg-n", "bfg-y", "MERGE")]


def test_backfill_leaves_already_labelled_rows_alone(db):
    """Idempotent: it only fills rows the columns never reached."""
    m = _binary_market(db, "bfi")
    db.execute(
        "INSERT INTO trades (TRADE_ID, MARKET, ASSET_ID, MAKER_ASSET_ID, "
        "MATCH_KIND, SIDE, PRICE, TRADE_SIZE, STATUS, MAKER_ORDERS) "
        "VALUES (%s, %s, 'bfi-y', 'DELIBERATE', 'NORMAL', 'BUY', 1, 1, "
        "'matched', %s)",
        (uuid.uuid4().hex, m.condition_id.value,
         json.dumps([{"side": "BUY"}])),
    )
    TableCreate.backfill_trade_match_kind(db)
    # Were it re-derived, the BUY/BUY pair would relabel this MINT.
    assert _kinds(db) == [("bfi-y", "DELIBERATE", "NORMAL")]


def test_backfill_is_a_no_op_on_a_second_run(db):
    m = _binary_market(db, "bft")
    _legacy_trade(db, market=m, asset="bft-y", taker_side="BUY", maker_side="BUY")
    TableCreate.backfill_trade_match_kind(db)
    first = _kinds(db)
    TableCreate.backfill_trade_match_kind(db)
    assert _kinds(db) == first
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/services/test_mint_merge_accounting.py -q -k backfill`
Expected: FAIL — `AttributeError: type object 'TableCreate' has no attribute 'backfill_trade_match_kind'`.

- [ ] **Step 3: Write the implementation**

In `agentpit/db/table_create.py`, add this method to `TableCreate` and call it from the end of `create_trades_table`:

```python
    @staticmethod
    def backfill_trade_match_kind(conn: psycopg.Connection) -> None:
        """Label rows written before MATCH_KIND existed, and name their maker's
        token.

        Nothing is lost, so nothing has to be guessed: the taker's side is on
        the row, the maker's is inside MAKER_ORDERS, and those two decide the
        kind exactly as the matcher decided it. The maker's token is then the
        same asset for a NORMAL match, or the market's other outcome for a
        MINT/MERGE — and `markets.ERC1155_TOKENS` still holds the pair.

        Touches only rows where MATCH_KIND IS NULL, so it is idempotent and
        never overwrites what the write path recorded first-hand.
        """
        rows = conn.execute(
            "SELECT TRADE_ID, MARKET, ASSET_ID, SIDE, MAKER_ORDERS FROM trades "
            "WHERE MATCH_KIND IS NULL"
        ).fetchall()
        if not rows:
            return
        # One read of every binary market, rather than one per trade row.
        complements: dict[str, str] = {}
        for m in conn.execute(
            "SELECT ERC1155_TOKENS FROM markets"
        ).fetchall():
            try:
                pairs = json.loads(m["ERC1155_TOKENS"])
            except (TypeError, ValueError):
                continue
            if len(pairs) != 2:
                continue
            a, b = pairs[0][0], pairs[1][0]
            complements[a] = b
            complements[b] = a

        updates: list[tuple[str, str, str]] = []
        for r in rows:
            taker_side = r["SIDE"]
            mo = r["MAKER_ORDERS"]
            try:
                parsed = json.loads(mo) if isinstance(mo, str) else mo
                maker_side = parsed[0].get("side") if parsed else None
            except (TypeError, ValueError, IndexError, KeyError, AttributeError):
                maker_side = None
            asset = r["ASSET_ID"]
            if taker_side == "BUY" and maker_side == "BUY":
                kind = "MINT"
            elif taker_side == "SELL" and maker_side == "SELL":
                kind = "MERGE"
            else:
                kind = "NORMAL"
            # A complement we cannot resolve (non-binary market, or a token no
            # market claims) falls back to the taker's asset: wrong for a mint,
            # but no worse than the NULL it replaces, and it keeps the column
            # total so readers need no second code path.
            maker_asset = (
                asset if kind == "NORMAL" else complements.get(asset, asset)
            )
            updates.append((maker_asset, kind, r["TRADE_ID"]))

        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE trades SET MAKER_ASSET_ID = %s, MATCH_KIND = %s "
                "WHERE TRADE_ID = %s",
                updates,
            )
```

**`json` is NOT imported in `agentpit/db/table_create.py`** — its import block is
only `import psycopg` and the `MarketState` import. Add `import json` at the top,
keeping the existing order.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/services/test_mint_merge_accounting.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agentpit/db/table_create.py tests/services/test_mint_merge_accounting.py
git commit -m "feat(trades): backfill the maker token and match kind"
```

---

## Task 3: Attribute every leg to the token that party actually moved

**Files:**
- Modify: `agentpit/services/account_service.py` (`_token_flow`)
- Test: `tests/services/test_mint_merge_accounting.py` (append)

**Interfaces:**
- Consumes: `trades.MAKER_ASSET_ID`, `trades.MATCH_KIND` (Tasks 1–2).
- Produces: `_token_flow(conn, api_key, token_id)` returning a `_TokenFlow` whose `bought_size`/`bought_cost`/`sold_size`/`sold_proceeds` are correct for a party on either side of any match kind. Its public shape is unchanged, so `_net_bought`, `_avg_fill_price`, `list_positions`, `list_closed_positions` and the leaderboard all inherit the fix.

**The rule to implement**, from the matcher's own semantics — the stored `PRICE` is always the MAKER's price:

| kind | this user is taker | this user is maker |
| --- | --- | --- |
| NORMAL | token `ASSET_ID`, direction = `SIDE`, price `p` | token `ASSET_ID`, direction = opposite of `SIDE`, price `p` |
| MINT | token `ASSET_ID`, ACQUIRES, price `1 − p` | token `MAKER_ASSET_ID`, ACQUIRES, price `p` |
| MERGE | token `ASSET_ID`, DISPOSES, price `1 − p` | token `MAKER_ASSET_ID`, DISPOSES, price `p` |

- [ ] **Step 1: Write the failing test**

Append to `tests/services/test_mint_merge_accounting.py`:

```python
# ----- flows across every match kind -----------------------------------------

from agentpit.services.account_service import AccountService  # noqa: E402


def _trade(db, *, market, asset, maker_asset, kind, taker_side, price,
           size, taker="taker-key", maker="maker-key"):
    db.execute(
        "INSERT INTO trades (TRADE_ID, MARKET, ASSET_ID, MAKER_ASSET_ID, "
        "MATCH_KIND, SIDE, PRICE, TRADE_SIZE, STATUS, TAKER_API_KEY, "
        "MAKER_API_KEY) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'matched',%s,%s)",
        (uuid.uuid4().hex, market.condition_id.value, asset, maker_asset,
         kind, taker_side, price, size, taker, maker),
    )


def test_a_mint_maker_acquires_the_complement_at_the_stored_price(db):
    """The bug in one test: the maker of a mint receives the OTHER token, and
    before this its holdings had no row at all."""
    m = _binary_market(db, "fm1")
    _trade(db, market=m, asset="fm1-y", maker_asset="fm1-n", kind="MINT",
           taker_side="BUY", price=300_000, size=100)
    flow = AccountService._token_flow(db, "maker-key", "fm1-n")
    assert flow.bought_size == 100
    assert flow.avg_buy_price_micro == 300_000
    assert flow.sold_size == 0
    # And nothing landed on the taker's token for this user.
    assert AccountService._token_flow(db, "maker-key", "fm1-y").bought_size == 0


def test_a_mint_taker_pays_the_complement_of_the_stored_price(db):
    m = _binary_market(db, "fm2")
    _trade(db, market=m, asset="fm2-y", maker_asset="fm2-n", kind="MINT",
           taker_side="BUY", price=300_000, size=100)
    flow = AccountService._token_flow(db, "taker-key", "fm2-y")
    assert flow.bought_size == 100
    # The pair costs $1: the maker put up 0.30, so the taker put up 0.70.
    assert flow.avg_buy_price_micro == 700_000


def test_a_merge_disposes_on_both_sides(db):
    m = _binary_market(db, "fg1")
    _trade(db, market=m, asset="fg1-y", maker_asset="fg1-n", kind="MERGE",
           taker_side="SELL", price=400_000, size=100)
    taker = AccountService._token_flow(db, "taker-key", "fg1-y")
    maker = AccountService._token_flow(db, "maker-key", "fg1-n")
    assert taker.sold_size == 100 and maker.sold_size == 100
    assert taker.bought_size == 0 and maker.bought_size == 0
    # Proceeds sum to the $1 the merge returns.
    assert taker.sold_proceeds + maker.sold_proceeds == 1_000_000 * 100


def test_a_normal_match_still_moves_one_token_in_two_directions(db):
    m = _binary_market(db, "fn1")
    _trade(db, market=m, asset="fn1-y", maker_asset="fn1-y", kind="NORMAL",
           taker_side="BUY", price=250_000, size=100)
    assert AccountService._token_flow(db, "taker-key", "fn1-y").bought_size == 100
    assert AccountService._token_flow(db, "maker-key", "fn1-y").sold_size == 100


def test_net_size_can_no_longer_go_negative_on_a_mint_heavy_account(db):
    """The production symptom: trade nets reading -55,142 shares, which is
    impossible for real holdings and meant the maker's leg was landing on the
    wrong token."""
    m = _binary_market(db, "fn2")
    for _ in range(3):
        _trade(db, market=m, asset="fn2-y", maker_asset="fn2-n", kind="MINT",
               taker_side="BUY", price=300_000, size=100)
    for key, tok in (("taker-key", "fn2-y"), ("maker-key", "fn2-n")):
        assert AccountService._token_flow(db, key, tok).net_size == 300
    for key, tok in (("taker-key", "fn2-n"), ("maker-key", "fn2-y")):
        assert AccountService._token_flow(db, key, tok).net_size == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/services/test_mint_merge_accounting.py -q -k "mint or merge or normal_match or net_size"`
Expected: FAIL — the mint-maker flow reports 0 bought, because `_token_flow` filters on `ASSET_ID` only.

- [ ] **Step 3: Write the implementation**

In `agentpit/services/account_service.py`, replace `_token_flow`'s query and its per-row logic. Read the current method first; keep the `_TokenFlow` dataclass and the method's signature exactly as they are.

The query must find rows where the user's token is EITHER side:

```python
        rows = conn.execute(
            "SELECT SIDE, PRICE, TRADE_SIZE, MATCH_TIME, MATCH_KIND, "
            "ASSET_ID, MAKER_ASSET_ID, TAKER_API_KEY, MAKER_API_KEY "
            "FROM trades WHERE STATUS != 'FAILED' "
            "AND ((TAKER_API_KEY = %s AND ASSET_ID = %s) "
            "  OR (MAKER_API_KEY = %s AND COALESCE(MAKER_ASSET_ID, ASSET_ID) = %s))",
            (api_key, token_id, api_key, token_id),
        ).fetchall()
```

and the body becomes, per row:

```python
        for r in rows:
            is_taker = r["TAKER_API_KEY"] == api_key
            kind = r["MATCH_KIND"] or "NORMAL"
            price = int(r["PRICE"])  # always the MAKER's price
            size = int(r["TRADE_SIZE"])
            if kind == "MINT":
                # Both sides acquire, of different tokens, and their prices
                # sum to the $1 the mint costs.
                acquiring = True
                if is_taker:
                    price = 1_000_000 - price
            elif kind == "MERGE":
                # Both sides dispose; their proceeds sum to the $1 returned.
                acquiring = False
                if is_taker:
                    price = 1_000_000 - price
            else:
                # One token, opposite directions, one price.
                acquiring = (r["SIDE"] == "BUY") == is_taker
            if acquiring:
                bought_size += size
                bought_cost += price * size
            else:
                sold_size += size
                sold_proceeds += price * size
                last_sell_time = max(last_sell_time, int(r["MATCH_TIME"] or 0))
```

Rewrite the docstring to describe the table above rather than the old
maker-side heuristic — the `SIDE == "BUY") == is_taker` rule survives only for
NORMAL matches now, and the MINT price flip is no longer inferred from the
maker's side but taken from the recorded kind.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/services/test_mint_merge_accounting.py -q`
Expected: PASS, 13 tests.

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. `tests/db/test_cost_basis.py` and `tests/services/test_closed_positions.py` exercise `_avg_fill_price` and the closed-position reconstruction, which both route through `_token_flow`. Their fixtures write no `MATCH_KIND`, so those rows take the NORMAL path — the same behaviour they asserted before. If one fails, read the failure; do not adjust an assertion.

- [ ] **Step 6: Commit**

```bash
git add agentpit/services/account_service.py \
        tests/services/test_mint_merge_accounting.py
git commit -m "fix(positions): attribute each match leg to the token it moved"
```

---

## Task 4: Prove the books balance

**Files:** none — this task only runs and reports.

**Why:** the three tasks above are only worth having if an account's reconstructed holdings now agree with the chain. That is the check the original bug would have failed.

- [ ] **Step 1: Backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. Do NOT source `.env`.

- [ ] **Step 2: Reconcile trade nets against on-chain balances**

```bash
.venv/bin/python - <<'PY'
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.services.account_service import AccountService

db = DbSession(Settings().database_url)
with db.read() as conn:
    for acct in TableRead.list_traded_accounts(conn):
        # TradedAccount carries user_id / eth_address / handle — NOT api_key.
        user = TableRead.get_user_by_eth_address(conn, acct.eth_address)
        if user is None:
            continue
        markets = TableRead.list_markets_with_user_activity(conn, user.api_key)
        negatives = []
        for mkt in markets:
            for token_id, _label in mkt.erc1155_tokens:
                flow = AccountService._token_flow(conn, user.api_key, token_id)
                if flow.net_size < 0:
                    negatives.append((mkt.slug[:28], token_id[:12], flow.net_size))
        print(f"{acct.eth_address[:10]}  tokens with a NEGATIVE net: {len(negatives)}")
        for n in negatives[:3]:
            print("   ", n)
db.close()
PY
```
Expected: **zero** negative nets for every account. A negative net means the
history still claims an account sold more than it ever held — the signature of
a leg landing on the wrong token.

- [ ] **Step 3: Check the two board figures move to something defensible**

```bash
.venv/bin/python - <<'PY'
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.onchain.admin import OnchainAdmin
from agentpit.services.account_service import AccountService
from agentpit.db.table_read import TableRead

db = DbSession(Settings().database_url)
accounts = AccountService(db, OnchainAdmin())
with db.read() as conn:
    for acct in TableRead.list_traded_accounts(conn):
        value, cost = accounts.value_and_cost(acct.eth_address)
        print(f"{acct.eth_address[:10]}  positions worth ${value:,.2f}  cost ${cost:,.2f}")
db.close()
PY
```
Expected: for every account the cost basis is plausible against its $100,000
grant — the pre-fix symptom was an account showing $101,970 of cost basis while
its whole capital was $92,571.

- [ ] **Step 4: Report**

State the backend test count, the negative-net count per account (Step 2), and
the cost-basis figures (Step 3). If any account still shows a negative net,
report it rather than summarising — that is the fix failing.

---

## Self-Review

**Coverage.** The diagnosis named three defects and each has a task: the maker's token is unrecorded (Task 1), existing rows carry no way to tell the kind (Task 2), and the flow reader attributes legs by `ASSET_ID` alone (Task 3). Task 4 is the reconciliation that would have caught the original bug.

**Placeholders.** None. Every code step carries the code; every test step carries the assertions.

**Type consistency.** `MAKER_ASSET_ID` / `MATCH_KIND` are created in Task 1, filled for history in Task 2, and read in Task 3's query. `backfill_trade_match_kind(conn)` is defined in Task 2 and called from `create_trades_table` in the same task. `_TokenFlow`'s public shape is deliberately unchanged, so `_net_bought`, `_avg_fill_price`, `list_positions`, `list_closed_positions` and the leaderboard need no edits — Task 3 says so explicitly, and Task 4 verifies it end to end.

**Known risk flagged in-task.** Task 2's backfill falls back to the taker's asset when a complement cannot be resolved, and says why that is acceptable. Task 3 warns that the existing cost-basis and closed-position tests write no `MATCH_KIND` and must keep passing on the NORMAL path — with an explicit instruction not to adjust their assertions.
