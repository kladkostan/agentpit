import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentpit.api.deps import (
    get_current_user,
    get_db_session,
    get_jwt_coder,
    get_onchain_admin,
    get_settings,
)
from agentpit.api.exception_handlers import register_exception_handlers
from agentpit.api.routes import (
    admin,
    agents,
    auth,
    data_api,
    events,
    market_data,
    markets,
    orders,
    personalities,
    positions,
    system,
    usdc,
    users,
)
from agentpit.auth.dependencies import make_current_user_dep
from agentpit.auth.jwt import JwtCoder
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.contracts import Contracts
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client
from agentpit.polymarket.polymarket_sync import fetch_and_sync_polymarket_markets
from agentpit.services.event_service import EventService
from agentpit.services.snapshot_service import SnapshotService

log = logging.getLogger(__name__)


def _configure_root_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root.handlers.clear()
    root.addHandler(handler)


def _run_polymarket_sync(db: DbSession, admin: OnchainAdmin) -> int:
    with db.write() as conn:
        created = fetch_and_sync_polymarket_markets(conn, admin)
    return len(created)


async def _polymarket_sync_loop(
    db: DbSession, admin: OnchainAdmin, interval_seconds: int
) -> None:
    while True:
        try:
            count = await asyncio.to_thread(_run_polymarket_sync, db, admin)
            log.info("Polymarket sync added %d new markets", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Polymarket sync failed")
        await asyncio.sleep(interval_seconds)


def _run_snapshot_tick(db: DbSession, retention_seconds: int) -> tuple[int, int]:
    service = SnapshotService(db)
    inserted = service.take_snapshot()
    deleted = service.prune_old(retention_seconds)
    return inserted, deleted


async def _snapshot_loop(
    db: DbSession, interval_seconds: int, retention_seconds: int
) -> None:
    while True:
        try:
            inserted, deleted = await asyncio.to_thread(
                _run_snapshot_tick, db, retention_seconds
            )
            log.info("Snapshot tick: %d inserted, %d pruned", inserted, deleted)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Snapshot tick failed")
        await asyncio.sleep(interval_seconds)


def _build_onchain_admin(settings: Settings) -> OnchainAdmin:
    if not settings.deployment_path.exists():
        raise RuntimeError(
            f"on-chain deployment file {settings.deployment_path} not found — "
            "run scripts/run_node.sh && scripts/deploy_exchange.sh first"
        )
    deployment = Deployment.load(settings.deployment_path)
    client = Web3Client(settings, deployment)
    client.verify_chain()
    contracts = Contracts(client.web3, deployment)
    log.info(
        "on-chain stack ready: usd=%s faucet=%s exchange=%s",
        deployment.usd,
        deployment.faucet,
        deployment.exchange,
    )
    return OnchainAdmin(client, contracts)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    _configure_root_logging()

    if settings.admin_token == "dev-admin-token":
        log.warning(
            "admin_token is the unsafe default — set AGENTPIT_ADMIN_TOKEN before "
            "exposing /admin/* to the network"
        )

    db_session = DbSession(settings.db_path)
    coder = JwtCoder(settings)
    onchain_admin = _build_onchain_admin(settings)
    current_user_fn = make_current_user_dep(coder)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            wrapped = EventService(db_session).ensure_singleton_events_for_orphans()
            if wrapped:
                log.info("Wrapped %d orphan market(s) in singleton events", wrapped)
        except Exception:
            log.exception("orphan-market auto-wrap failed at startup")

        sync_task: asyncio.Task | None = None
        if settings.sync_enabled:
            log.info(
                "Polymarket sync enabled (interval=%ds)", settings.sync_interval_seconds
            )
            sync_task = asyncio.create_task(
                _polymarket_sync_loop(
                    db_session, onchain_admin, settings.sync_interval_seconds
                )
            )
        else:
            log.info("Polymarket sync disabled (set SYNC=true to enable)")

        snapshot_task: asyncio.Task | None = None
        if settings.snapshot_enabled:
            retention_seconds = settings.snapshot_retention_days * 86_400
            log.info(
                "Snapshot loop enabled (interval=%ds, retention=%dd)",
                settings.snapshot_interval_seconds,
                settings.snapshot_retention_days,
            )
            snapshot_task = asyncio.create_task(
                _snapshot_loop(
                    db_session,
                    settings.snapshot_interval_seconds,
                    retention_seconds,
                )
            )
        else:
            log.info(
                "Snapshot loop disabled (set SNAPSHOT_ENABLED=true to enable)"
            )
        try:
            yield
        finally:
            for task in (sync_task, snapshot_task):
                if task is None:
                    continue
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            db_session.close()

    app = FastAPI(title="AgentPit", lifespan=lifespan)
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_jwt_coder] = lambda: coder
    app.dependency_overrides[get_onchain_admin] = lambda: onchain_admin
    app.dependency_overrides[get_current_user] = current_user_fn

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(admin.router)
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(markets.router)
    app.include_router(events.router)
    app.include_router(orders.router)
    app.include_router(market_data.router)
    app.include_router(positions.router)
    app.include_router(usdc.router)
    app.include_router(personalities.router)
    app.include_router(agents.router)
    app.include_router(data_api.router)

    return app
