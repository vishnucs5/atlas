"""Health, readiness, and component status routes for ATLAS API."""

from datetime import UTC, datetime
from typing import Any

from atlas_observability import get_logger
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = get_logger("atlas.api.health")
API_VERSION = "0.1.0"

router = APIRouter(tags=["Health & Status"])


class HealthResponse(BaseModel):
    """Liveness probe response payload."""

    status: str = Field(default="healthy", description="Service liveness state")
    version: str = Field(default=API_VERSION, description="ATLAS API version")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Current UTC timestamp in ISO 8601 format",
    )


class StatusResponse(BaseModel):
    """Detailed component status and readiness response payload."""

    status: str = Field(default="ok", description="Overall system health status")
    version: str = Field(default=API_VERSION, description="ATLAS API version")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Current UTC timestamp in ISO 8601 format",
    )
    components: dict[str, str] = Field(
        default_factory=dict,
        description="Individual subsystem readiness states",
    )


def check_storage_status(request: Request) -> str:
    """Evaluate storage backend readiness.

    Returns:
        'ok' if storage is reachable and responsive, otherwise 'error'.
    """
    custom_checker = getattr(request.app.state, "storage_check", None)
    if callable(custom_checker):
        try:
            return "ok" if custom_checker() else "error"
        except Exception as exc:
            logger.error("Custom storage check failed", extra={"error": str(exc)})
            return "error"

    storage: Any = getattr(request.app.state, "storage", None)
    if storage is None:
        logger.warning("Storage backend not initialized on application state")
        return "error"

    if hasattr(storage, "list_tasks"):
        try:
            storage.list_tasks(limit=1)
            return "ok"
        except Exception as exc:
            logger.error("Configured storage check failed", extra={"error": str(exc)})
            return "error"

    logger.error("Storage backend does not implement required interface")
    return "error"


@router.get("/health", response_model=HealthResponse, summary="Liveness Probe")
@router.get("/healthz", response_model=HealthResponse, summary="Liveness Probe (Kubernetes alias)")
def get_health() -> HealthResponse:
    """Return basic service health for liveness checks."""
    return HealthResponse()


@router.get(
    "/v1/status",
    response_model=StatusResponse,
    summary="Component Status",
)
@router.get(
    "/api/v1/status",
    response_model=StatusResponse,
    summary="Component Status (API prefix alias)",
)
def get_v1_status(request: Request) -> StatusResponse:
    """Return detailed system and component status."""
    storage_state = check_storage_status(request)
    overall_status = "ok" if storage_state == "ok" else "degraded"
    return StatusResponse(
        status=overall_status,
        version=API_VERSION,
        timestamp=datetime.now(UTC).isoformat(),
        components={
            "api": "ok",
            "storage": storage_state,
        },
    )


@router.get(
    "/readyz",
    response_model=StatusResponse,
    summary="Readiness Probe",
    responses={
        200: {"description": "All critical components are ready"},
        503: {"description": "One or more critical components are unready"},
    },
)
def get_readyz(request: Request) -> JSONResponse:
    """Evaluate readiness of all required subsystems for traffic admission."""
    storage_state = check_storage_status(request)
    is_ready = storage_state == "ok"
    overall_status = "ok" if is_ready else "degraded"
    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE

    payload = StatusResponse(
        status=overall_status,
        version=API_VERSION,
        timestamp=datetime.now(UTC).isoformat(),
        components={
            "api": "ok",
            "storage": storage_state,
        },
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())
