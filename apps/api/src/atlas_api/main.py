"""ATLAS API Service - Application entrypoint and factory."""

import os
from contextlib import asynccontextmanager
from typing import Any

from atlas_agent.runtime import ProductionRuntime
from atlas_observability import REGISTRY, get_logger, get_tracer
from atlas_storage.sqlite import SQLiteStorage
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atlas_api.routes.approvals import router as approvals_router
from atlas_api.routes.artifacts import router as artifacts_router
from atlas_api.routes.collaboration import router as collaboration_router
from atlas_api.routes.dashboard import router as dashboard_router
from atlas_api.routes.distributed import router as distributed_router
from atlas_api.routes.enterprise import router as enterprise_router
from atlas_api.routes.events import router as events_router
from atlas_api.routes.health import router as health_router
from atlas_api.routes.marketplace import router as marketplace_router
from atlas_api.routes.orchestration import router as orchestration_router
from atlas_api.routes.tasks import router as tasks_router
from atlas_api.routes.workers import router as workers_router

logger = get_logger("atlas.api")
API_VERSION = "0.1.0"


def _cors_origins_from_environment() -> list[str]:
    """Read explicit browser origins and reject permissive CORS in production."""
    configured = os.getenv("ATLAS_CORS_ORIGINS", "")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    if origins:
        return origins
    if os.getenv("ATLAS_ENV", "development").lower() == "production":
        raise RuntimeError("ATLAS_CORS_ORIGINS must be set when ATLAS_ENV=production.")
    return ["*"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager handling startup and shutdown initialization."""
    logger.info("Initializing ATLAS API service", extra={"version": API_VERSION})
    db_url = os.getenv("ATLAS_DATABASE_URL")
    db_path = os.getenv("ATLAS_DB_PATH", ":memory:")
    storage: Any = None
    try:
        if db_url and (db_url.startswith("postgresql://") or db_url.startswith("postgres://")):
            from atlas_storage.postgres import PostgresStorage

            storage = PostgresStorage(db_url)
            storage.initialize()
            logger.info(
                "PostgresStorage initialized",
                extra={"db_target": db_url.split("@")[-1] if "@" in db_url else "configured"},
            )
        else:
            storage = SQLiteStorage(db_path)
            storage.initialize()
            logger.info("SQLiteStorage initialized", extra={"db_path": db_path})

        app.state.storage = storage
        runtime = ProductionRuntime(storage=storage)
        await runtime.initialize()
        app.state.runtime = runtime
        logger.info("ProductionRuntime initialized successfully")
    except Exception as exc:
        logger.error("Failed to initialize storage or runtime", extra={"error": str(exc)})
        app.state.storage = None
        app.state.runtime = None
        if db_url and (db_url.startswith("postgresql://") or db_url.startswith("postgres://")):
            # Never silently swallow PostgreSQL failure when explicitly configured
            raise

    yield

    runtime = getattr(app.state, "runtime", None)
    if runtime is not None:
        try:
            await runtime.shutdown()
        except Exception as exc:
            logger.error("Failed to cleanly shut down runtime", extra={"error": str(exc)})

    storage = getattr(app.state, "storage", None)
    if storage is not None and hasattr(storage, "close"):
        try:
            storage.close()
        except Exception as exc:
            logger.error("Failed to close storage backend", extra={"error": str(exc)})
    logger.info("Shutting down ATLAS API service")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="ATLAS API",
        description="Autonomous Task & Lifecycle Automation System API Service",
        version=API_VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins_from_environment(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    tracer = get_tracer("atlas-api")

    @app.middleware("http")
    async def tracing_middleware(request, call_next):
        parent_ctx = tracer.extract_context(dict(request.headers))
        path = request.url.path
        method = request.method
        with tracer.span(
            f"HTTP {method} {path}",
            parent_context=parent_ctx,
            attributes={"http.method": method, "http.target": path},
        ) as span:
            try:
                response = await call_next(request)
                span.set_attribute("http.status_code", response.status_code)
                response.headers["traceparent"] = span.context.to_traceparent()
                REGISTRY.inc_counter(
                    "atlas_http_requests_total",
                    labels={"method": method, "status": str(response.status_code)},
                )
                return response
            except Exception as exc:
                span.record_exception(exc)
                REGISTRY.inc_counter(
                    "atlas_http_requests_total",
                    labels={"method": method, "status": "500"},
                )
                raise

    # Health & status
    app.include_router(health_router)

    # Core API endpoints
    app.include_router(tasks_router)
    app.include_router(approvals_router)
    app.include_router(events_router)
    app.include_router(artifacts_router)
    app.include_router(workers_router)
    app.include_router(orchestration_router)
    app.include_router(marketplace_router)
    app.include_router(distributed_router)
    app.include_router(enterprise_router)
    app.include_router(collaboration_router)

    # Embedded Operator Dashboard
    app.include_router(dashboard_router)

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/dashboard")

    return app


app = create_app()
