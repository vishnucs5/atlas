"""ATLAS API Service - Application entrypoint and factory."""

import os
from contextlib import asynccontextmanager
from typing import Any

from atlas_agent.runtime import ProductionRuntime
from atlas_observability import get_logger
from atlas_storage.sqlite import SQLiteStorage
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atlas_api.routes.approvals import router as approvals_router
from atlas_api.routes.artifacts import router as artifacts_router
from atlas_api.routes.dashboard import router as dashboard_router
from atlas_api.routes.events import router as events_router
from atlas_api.routes.health import router as health_router
from atlas_api.routes.marketplace import router as marketplace_router
from atlas_api.routes.orchestration import router as orchestration_router
from atlas_api.routes.tasks import router as tasks_router
from atlas_api.routes.workers import router as workers_router

logger = get_logger("atlas.api")
API_VERSION = "0.1.0"


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
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    # Embedded Operator Dashboard
    app.include_router(dashboard_router)

    return app


app = create_app()
