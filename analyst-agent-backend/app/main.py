import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import queue
from app.agent.store import setup_store
from app.api import (
    routes_auth,
    routes_connections,
    routes_health,
    routes_runs,
    routes_usage,
)
from app.config import get_settings
from app.db.session import SessionLocal
from app.forecasting.service import load_forecaster
from app.llm import configure_tracing
from app.logging import configure_logging, log
from app.mcp_client import probe_mcp
from app.services.errors import DomainError
from app.services.runs import reap_stale_runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    configure_tracing()
    s = get_settings()
    if s.queue_enabled:
        # Fail the boot rather than the first question if Redis is not running.
        await queue.connect()
    if s.mcp_startup_probe:
        # Same reasoning: without the MCP server no Postgres connection can answer anything.
        await probe_mcp()
    if s.forecast_engine != "off" and not s.queue_enabled:
        # Off the event loop: loading the checkpoint takes seconds. A model that will not load
        # fails the boot, for the same reason a missing MCP server does. In queue mode the
        # worker runs every tool, so the API would hold a gigabyte it never uses.
        await asyncio.to_thread(load_forecaster)
    # Idempotent, and not per run: it issues CREATE INDEX CONCURRENTLY.
    setup_store()
    db = SessionLocal()
    try:
        # Covers a process killed mid-run, which no in-process teardown can reach.
        reap_stale_runs(db)
    finally:
        db.close()
    log.info("startup", env=s.env, queue=s.queue_enabled)
    yield
    await queue.close()
    log.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(title="Analyst Agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        content = {"error": str(exc)}
        if exc.code:
            content["code"] = exc.code
        return JSONResponse(status_code=exc.status_code, content=content)

    app.include_router(routes_health.router)
    app.include_router(routes_auth.router, prefix="/auth", tags=["auth"])
    app.include_router(routes_connections.router, prefix="/connections", tags=["connections"])
    app.include_router(routes_runs.router, prefix="/runs", tags=["runs"])
    app.include_router(routes_usage.router, prefix="/usage", tags=["usage"])
    return app


app = create_app()
