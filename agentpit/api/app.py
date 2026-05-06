import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentpit.api.deps import get_db_session
from agentpit.api.exception_handlers import register_exception_handlers
from agentpit.api.routes import (
    agents,
    markets,
    personalities,
    portfolio,
    positions,
    system,
    usdc,
    users,
)
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.polymarket.polymarket_sync import fetch_and_sync_polymarket_markets

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


def _run_polymarket_sync(db: DbSession) -> int:
    with db.write() as conn:
        created = fetch_and_sync_polymarket_markets(conn)
    return len(created)


async def _polymarket_sync_loop(db: DbSession, interval_seconds: int) -> None:
    while True:
        try:
            count = await asyncio.to_thread(_run_polymarket_sync, db)
            log.info("Polymarket sync added %d new markets", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Polymarket sync failed")
        await asyncio.sleep(interval_seconds)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    _configure_root_logging()

    db_session = DbSession(settings.db_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        sync_task: asyncio.Task | None = None
        if settings.sync_enabled:
            log.info(
                "Polymarket sync enabled (interval=%ds)", settings.sync_interval_seconds
            )
            sync_task = asyncio.create_task(
                _polymarket_sync_loop(db_session, settings.sync_interval_seconds)
            )
        else:
            log.info("Polymarket sync disabled (set SYNC=true to enable)")
        try:
            yield
        finally:
            if sync_task is not None:
                sync_task.cancel()
                try:
                    await sync_task
                except asyncio.CancelledError:
                    pass
            db_session.close()

    app = FastAPI(title="AgentPit", lifespan=lifespan)
    app.dependency_overrides[get_db_session] = lambda: db_session

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(system.router)
    app.include_router(markets.router)
    app.include_router(positions.router)
    app.include_router(usdc.router)
    app.include_router(users.router)
    app.include_router(personalities.router)
    app.include_router(agents.router)
    app.include_router(portfolio.router)

    return app
