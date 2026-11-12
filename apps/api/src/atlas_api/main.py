"""ATLAS API Service - Application entrypoint and factory."""

import os
from contextlib import asynccontextmanager

from atlas_observability import get_logger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atlas_api.routes.health import router as health_router

logger = get_logger("atlas.api")
API_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager handling startup and shutdown initialization."""
    logger.info("Initializing ATLAS API service", extra={"version": API_VERSION})
    db_path = os.getenv("ATLAS_DB_PATH", ":memory:")
    try:
        from atlas_storage.sqlite import SQLiteStorage

        storage = SQLiteStorage(db_path)
        storage.initialize()
        app.state.storage = storage
        logger.info("Storage backend initialized", extra={"db_path": db_path})
    except Exception as exc:
        logger.error("Failed to initialize storage backend", extra={"error": str(exc)})
        app.state.storage = None
    yield
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

    app.include_router(health_router)

    return app


app = create_app()
