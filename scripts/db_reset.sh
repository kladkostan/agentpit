#!/usr/bin/env bash
# Reset (drop + recreate) agentpit Postgres database(s) to a clean, empty state.
#
# agentpit is ephemeral by design: on startup it rebuilds its schema
# (db.table_create) and re-syncs markets from Polymarket, so an empty database
# is all a "clean slate" needs — no datadir surgery required.
#
# Usage:
#   ./scripts/db_reset.sh                       # reset the dev DB (agentpit)
#   ./scripts/db_reset.sh agentpit_test         # reset a specific DB
#   ./scripts/db_reset.sh agentpit agentpit_test  # reset both
#
# Note: --force terminates any open connections (e.g. a running app's pool),
# so stop the app first if you don't want it to error mid-request.
set -euo pipefail

DBS=("${@:-agentpit}")

if ! pg_isready -q 2>/dev/null; then
  echo "Postgres is not reachable. Start it first: scripts/run_postgres.sh" >&2
  exit 1
fi

for db in "${DBS[@]}"; do
  dropdb --if-exists --force "$db"   # --force (PG 13+) drops even with open connections
  createdb "$db"
  echo "reset: $db (empty — schema is rebuilt on the next app start / test run)"
done
