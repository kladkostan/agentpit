#!/usr/bin/env bash
# Ensure a local Postgres is up and the agentpit dev + test databases exist.
#
# Primary path: native Homebrew Postgres (no Docker daemon needed on macOS).
# If you prefer Docker (OrbStack/colima/podman), run `docker compose up -d`
# instead and point AGENTPIT_DATABASE_URL at it.
set -euo pipefail

if ! pg_isready -q 2>/dev/null; then
  echo "Postgres not reachable — trying to start the Homebrew service..."
  brew services start postgresql@16 2>/dev/null \
    || brew services start postgresql@14 2>/dev/null \
    || { echo "Could not start Postgres. Install it (brew install postgresql) or run 'docker compose up -d'." >&2; exit 1; }
  # give it a moment
  for _ in $(seq 1 20); do pg_isready -q && break; sleep 0.5; done
fi

for db in agentpit agentpit_test; do
  if createdb "$db" 2>/dev/null; then
    echo "created database: $db"
  else
    echo "database already exists: $db"
  fi
done

echo "Postgres ready. DSNs:"
echo "  dev:  postgresql:///agentpit"
echo "  test: postgresql:///agentpit_test"
