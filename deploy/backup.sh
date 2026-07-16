#!/usr/bin/env bash
# Snapshot the DB and the anvil chain state TOGETHER (they must roll back as a
# pair or balances diverge). Run from the repo root on the server; wire to
# cron when the stack settles.
#
#   ./deploy/backup.sh            # writes /root/backups/agentpit-<UTC stamp>/
set -euo pipefail

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_DIR:-/root/backups}/agentpit-$STAMP"
COMPOSE=(docker compose -f deploy/docker-compose.prod.yml --env-file .env)

mkdir -p "$DEST"

"${COMPOSE[@]}" exec -T postgres pg_dump -U agentpit agentpit | gzip > "$DEST/agentpit.sql.gz"

# anvil dumps state on interval/exit; copy the current file out of the volume.
docker run --rm -v agentpit_agentpit_anvil:/state:ro -v "$DEST":/out alpine \
  cp /state/anvil-state.json /out/anvil-state.json

cp deployments/local.json "$DEST/deployment.json"

echo "backup written: $DEST"
ls -lh "$DEST"
