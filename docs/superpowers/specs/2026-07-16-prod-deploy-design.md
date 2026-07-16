# Production deploy (single instance, docker compose) — Design + Runbook

**Date:** 2026-07-16 · **Target:** root@23.88.62.130 (Ubuntu 26.04, 2 vCPU / 3.7 GB / 75 GB, clean) · **Branch:** `mvp` · **Status:** approved in chat (compose + Caddy + IP/http for now; domain/TLS later)

## Topology

```
internet ──▶ :80   caddy — static UI (dist/ baked into image) + /arena JSONs
        ──▶ :8000  caddy — reverse_proxy → api:8000
internal docker network (nothing else published):
   api (uvicorn, 1 worker) ─▶ postgres:5432, anvil:8545, outbound Polymarket WSS/HTTPS
   chain-init (one-shot, profile "init") ─▶ deploys CTF+USD+Faucet+Exchange, writes deployments/local.json
```

- **No domain yet** → plain http on the IP. `VITE_API_BASE_URL=http://23.88.62.130:8000`
  is baked into the UI at build time (get-started snippets display it). When a domain
  appears: point A-records, switch Caddyfile sites to the hostnames (Caddy gets TLS
  automatically), rebuild UI with the new base URL, update `AGENTPIT_CORS_ORIGINS`.
  Note: clipboard copy buttons need https — known http limitation, accepted for now.
- **Firewall:** none needed (ufw stays off) — compose publishes only 80/8000; postgres
  and anvil are unpublished, internal-network only. anvil MUST never be published:
  unlocked accounts + operator key.

## Services (deploy/docker-compose.prod.yml, project name `agentpit`)

| service | image | notes |
|---|---|---|
| postgres | postgres:16 | named volume `agentpit_pg`; password from `.env` |
| anvil | ghcr.io/foundry-rs/foundry | `anvil --host 0.0.0.0 --chain-id 31337 --state /state/anvil-state.json --state-interval 30`, named volume `agentpit_anvil` |
| chain-init | deploy/Dockerfile.chain-init (foundry + jq/git/bash) | `profiles: [init]`, bind-mounts the repo at /repo, runs `scripts/deploy_exchange.sh` (sources repo .env; RPC_URL=http://anvil:8545), writes `deployments/local.json` on the host |
| api | deploy/Dockerfile.api (python:3.13-slim) | env from repo `.env` + overrides (DATABASE_URL→postgres, RPC_URL→anvil); mounts `../deployments` ro at /app/deployments (Settings default path). Schema is rebuilt by the app on startup (ephemeral-by-design), SYNC pulls markets on boot |
| caddy | deploy/Dockerfile.ui (node build → caddy:2) | publishes 80+8000; serves dist/ with SPA fallback; `/leaderboard.json` + `/bot-status*.json` served from bind-mounted `deploy/arena-data/` (rsync/scp target from the laptop bot) |

## Configuration (one server-side `.env` at repo root, never committed)

Consumed by BOTH compose (`--env-file`) and `deploy_exchange.sh` (sources it):
- `PK` / `ADMIN` — anvil dev account #0 (paper chain; the standard well-known key)
- `RPC_URL=http://anvil:8545`
- `POSTGRES_PASSWORD`, `JWT_SECRET`, `AGENTPIT_ADMIN_TOKEN` — `openssl rand -hex 32` on the server, never printed
- `VITE_API_BASE_URL=http://23.88.62.130:8000` (build arg)
- `AGENTPIT_CORS_ORIGINS=["http://23.88.62.130"]`
- `SYNC=true`, `SYNC_MAX_MARKETS`, `LIQUIDITY_ENGINE=true`, mirror/auto-redeem flags mirroring the dev config

## Runbook (first deploy)

1. Server prep: `apt-get install docker.io docker-compose-v2`; add 2 GB swapfile (3.7 GB RAM is tight).
2. `git pull` (repo already cloned at /root/dev/agentpit, branch mvp); `git submodule update --init vendor/ctf-exchange` (deploy_exchange.sh auto-inits the 4 nested libs).
3. Write `.env` (secrets generated in place); `mkdir deploy/arena-data` + scp current arena JSONs from the laptop.
4. `docker compose -f deploy/docker-compose.prod.yml --env-file .env build`
5. `up -d postgres anvil` → wait healthy → `run --rm chain-init` (writes deployments/local.json) → `up -d api caddy`.
6. Verify from outside: `GET :8000/markets` 200 + synced list; `POST :8000/register` returns funded user; place an order via the get-started flow; `GET :80/` serves UI; `/leaderboard.json` 200; operator endpoints 401 without X-Admin-Token.

## Ops notes

- **Update:** `git pull && compose build && compose up -d` (api/caddy only unless deps changed).
- **Backups (pair or nothing):** DB and chain must snapshot together or balances diverge. `deploy/backup.sh`: `pg_dump` + copy of anvil state file from the volume into /root/backups, dated. Wire to cron later.
- **Arena data:** the laptop bot keeps writing `ui/public/*.json` locally; delivery to prod = `scp ui/public/{leaderboard,bot-status-*}.json root@23.88.62.130:/root/dev/agentpit/deploy/arena-data/` (bot-side follow-up: add to its publish step).
- **uvicorn stays at 1 worker** — in-process caches + lifespan background loops (sync, liquidity engine, resolution mirror) must not run in N copies.
- **anvil degrades as state grows** (seen in dev) — paper-reset ritual = stop stack, wipe `agentpit_anvil` volume + drop DB, re-run chain-init (documented, deliberate, wipes balances).

## Out of scope (this pass)

- Domain/TLS (3-line switch later), CI builds/registry (build on server), moving the
  trader bots off the laptop, monitoring beyond `docker compose logs`/`restart: unless-stopped`.
