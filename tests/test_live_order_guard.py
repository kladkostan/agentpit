"""Nobody gets to redefine a live order in passing.

`TableRead.LIVE_ORDER` is the definition, and it is only a definition while
every query uses it. Sixteen queries had spelled the rule out by hand before
this existed; the seventeenth is the one that would quietly trade an expired
order, and it would be written by someone who had never heard of any of this.

The partial index in `table_create.py` is exempt: an index predicate cannot
reference a query parameter, so it indexes the status alone and the
expiration is filtered over the rows it returns.

The regex is case-insensitive (SQL is) and matches both `STATUS = 'live'`
and `STATUS IN ('live')`. Known blind spot: it matches per line, so a
predicate split across two source lines -- the column on one line, `'live'`
on the next -- would slip past uncaught. No such site exists today.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "agentpit"
RAW = re.compile(r"STATUS\s*=\s*'live'|STATUS\s+IN\s*\(\s*'live'\s*\)", re.IGNORECASE)
ALLOWED = {
    pathlib.Path("db/table_read.py"),    # the definition itself
    pathlib.Path("db/table_create.py"),  # the partial index
}


def test_no_query_spells_out_a_live_order_by_hand():
    offenders = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel in ALLOWED:
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if RAW.search(line):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert not offenders, (
        "use TableRead.LIVE_ORDER instead of spelling the predicate out:\n"
        + "\n".join(offenders)
    )
