"""Fill `events.LIQUIDITY` / `events.COMPETITIVE` for events the rolling sync
will never reach again.

The sync only re-binds markets inside its current Gamma window — the top
`SYNC_MAX_MARKETS` clearing `SYNC_LIQUIDITY_MIN` (1000 and 5000 on
production). Events that have since dropped out of that window would keep
NULL metrics forever and sort last under Liquidity and Competitive on the
markets page. The same gap bit the tag rollout (`backfill_market_tags.py`),
where 522 of 929 live events were affected.

Widening the sync's own floor is NOT the fix: `create_polygon_market_if_does_not_exist`
mints any market it has not seen, so a zero-floor pass would grow the
catalogue on chain as a side effect of a metadata backfill.

This reads the two figures straight from Gamma's `/events` endpoint instead,
and only ever FILLS: it selects rows where a metric IS NULL, so re-running it
is a no-op over what it already wrote — a later pass never overwrites a value
the sync itself captured.

    .venv/bin/python -m scripts.backfill_event_metrics [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_write import TableWrite

GAMMA = "https://gamma-api.polymarket.com"
#: Gamma caps a response at 100 rows; 50 ids per call leaves headroom.
BATCH = 50


def _as_float(value: object) -> float | None:
    """A number, or None for anything unparseable.

    None is the signal `update_event_metrics` skips on, so an event upstream
    has no figure for keeps whatever it already had rather than being blanked.
    """
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _fetch_event_metrics(pm_event_ids: list[str]) -> dict[str, dict[str, object]]:
    """`{polymarket_event_id: event_payload}` for one batch."""
    query = "&".join(f"id={urllib.parse.quote(i)}" for i in pm_event_ids)
    req = urllib.request.Request(
        f"{GAMMA}/events?limit=100&{query}",
        # Gamma 403s a bare urllib user-agent.
        headers={"User-Agent": "agentpit-backfill"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if not isinstance(payload, list):
        return {}
    out: dict[str, dict[str, object]] = {}
    for event in payload:
        if not isinstance(event, dict) or event.get("id") is None:
            continue
        out[str(event["id"])] = event
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be written without touching the database",
    )
    args = parser.parse_args()

    db = DbSession(Settings().database_url)
    with db.read() as conn:
        rows = conn.execute(
            """
            SELECT EVENT_ID, POLYMARKET_EVENT_ID AS PM_ID
            FROM events
            WHERE POLYMARKET_EVENT_ID IS NOT NULL
              AND (LIQUIDITY IS NULL OR COMPETITIVE IS NULL)
            """
        ).fetchall()

    event_id_by_pm_id: dict[str, int] = {
        str(row["PM_ID"]): int(row["EVENT_ID"]) for row in rows
    }

    print(
        f"{len(event_id_by_pm_id)} events missing liquidity/competitive"
        f"{' (dry run)' if args.dry_run else ''}"
    )

    pm_ids = sorted(event_id_by_pm_id)
    filled = missing_upstream = 0
    for i in range(0, len(pm_ids), BATCH):
        batch = pm_ids[i : i + BATCH]
        try:
            fetched = _fetch_event_metrics(batch)
        except Exception as exc:  # one bad batch must not lose the rest
            print(f"  batch {i // BATCH}: FAILED ({exc.__class__.__name__})")
            continue
        for pm_id in batch:
            payload = fetched.get(pm_id)
            if payload is None:
                # Upstream dropped the event, or returned it without figures.
                # NOT a failed request — a batch that raises is caught above
                # and skipped whole, so its events never reach this loop.
                # Leave the row as-is rather than inventing a figure.
                missing_upstream += 1
                continue
            liquidity = _as_float(payload.get("liquidity"))
            competitive = _as_float(payload.get("competitive"))
            if liquidity is None and competitive is None:
                missing_upstream += 1
                continue
            if args.dry_run:
                filled += 1
                continue
            with db.write() as conn:
                TableWrite.update_event_metrics(
                    conn, event_id_by_pm_id[pm_id], liquidity, competitive
                )
                filled += 1
        print(f"  {min(i + BATCH, len(pm_ids))}/{len(pm_ids)} events")

    print(
        f"done: {filled} events filled, "
        f"{missing_upstream} events upstream had no figures"
    )
    # Without this the pool's worker threads outlive main() and psycopg prints
    # a "couldn't stop thread" warning per worker on the way out.
    db.close()


if __name__ == "__main__":
    main()
