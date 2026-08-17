"""Fill `market_tags` for events the rolling sync will never reach again.

The sync only re-binds markets inside its current Gamma window — the top
`SYNC_MAX_MARKETS` clearing `SYNC_LIQUIDITY_MIN`. `events.CATEGORY` looks
complete only because it accumulated over months of hourly passes across a
shifting window; `market_tags` starts empty today, so every event that has
since dropped out of that window would sit under "All" and under no category
tab, permanently. On production that was 522 of 929 live events.

Widening the sync's own floor is NOT the fix: `create_polygon_market_if_does_not_exist`
mints any market it has not seen, so a zero-floor pass would grow the
catalogue on chain as a side effect of a metadata backfill.

This reads tags straight from Gamma's `/events` endpoint instead, and only
ever ADDS: a market that already carries tags is left alone, because the sync
writes per-market truth and this script only knows the event-level set. Safe
to re-run; each pass is a no-op over what it already filled.

    .venv/bin/python -m scripts.backfill_market_tags [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_write import TableWrite
from agentpit.polymarket.tag_taxonomy import normalize_slug

GAMMA = "https://gamma-api.polymarket.com"
#: Gamma caps a response at 100 rows; 50 ids per call leaves headroom.
BATCH = 50


def _fetch_event_tags(pm_event_ids: list[str]) -> dict[str, list[tuple[str, str]]]:
    """`{polymarket_event_id: [(slug, label), ...]}` for one batch."""
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
    out: dict[str, list[tuple[str, str]]] = {}
    for event in payload:
        if not isinstance(event, dict) or event.get("id") is None:
            continue
        tags: list[tuple[str, str]] = []
        for raw in event.get("tags") or []:
            if not isinstance(raw, dict):
                continue
            slug = normalize_slug(raw.get("slug"))
            if slug is None:
                continue
            label = raw.get("label")
            tags.append(
                (slug, label if isinstance(label, str) and label.strip() else slug)
            )
        out[str(event["id"])] = tags
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be written without touching the database",
    )
    args = parser.parse_args()

    # create_tables=False: the API has already migrated this database, and
    # re-running the DDL from a second process deadlocks against it — every
    # idempotent ADD COLUMN still takes an AccessExclusiveLock.
    db = DbSession(Settings().database_url, create_tables=False)
    with db.read() as conn:
        rows = conn.execute(
            """
            SELECT e.POLYMARKET_EVENT_ID AS PM_ID, m.MARKET_ID AS MARKET_ID
            FROM events e
            JOIN markets m ON m.EVENT_ID = e.EVENT_ID
            WHERE e.POLYMARKET_EVENT_ID IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM market_tags mt WHERE mt.MARKET_ID = m.MARKET_ID
              )
            """
        ).fetchall()

    markets_by_event: dict[str, list[int]] = {}
    for row in rows:
        markets_by_event.setdefault(str(row["PM_ID"]), []).append(int(row["MARKET_ID"]))

    print(
        f"{len(rows)} untagged markets across {len(markets_by_event)} events"
        f"{' (dry run)' if args.dry_run else ''}"
    )

    pm_ids = sorted(markets_by_event)
    written = untagged_upstream = 0
    for i in range(0, len(pm_ids), BATCH):
        batch = pm_ids[i : i + BATCH]
        try:
            fetched = _fetch_event_tags(batch)
        except Exception as exc:  # one bad batch must not lose the rest
            print(f"  batch {i // BATCH}: FAILED ({exc.__class__.__name__})")
            continue
        for pm_id in batch:
            tags = fetched.get(pm_id)
            if not tags:
                # Either upstream dropped the event, or it genuinely carries no
                # tags. Leave the rows empty rather than inventing a set.
                untagged_upstream += 1
                continue
            if args.dry_run:
                written += len(markets_by_event[pm_id])
                continue
            with db.write() as conn:
                for market_id in markets_by_event[pm_id]:
                    TableWrite.replace_market_tags(
                        conn, market_id=market_id, tags=tags
                    )
                    written += 1
        print(f"  {min(i + BATCH, len(pm_ids))}/{len(pm_ids)} events")

    print(
        f"done: {written} markets tagged, "
        f"{untagged_upstream} events upstream had no tags"
    )
    # Without this the pool's worker threads outlive main() and psycopg prints
    # a "couldn't stop thread" warning per worker on the way out.
    db.close()


if __name__ == "__main__":
    main()
