from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import routes_connections, routes_health, routes_runs
from app.config import get_settings
from app.llm import configure_tracing
from app.logging import configure_logging, log
from app.services.errors import DomainError


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    configure_tracing()
    log.info("startup", env=get_settings().env)
    yield
    log.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(title="Analyst Agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})

    app.include_router(routes_health.router)
    app.include_router(routes_connections.router, prefix="/connections", tags=["connections"])
    app.include_router(routes_runs.router, prefix="/runs", tags=["runs"])
    return app


app = create_app()
