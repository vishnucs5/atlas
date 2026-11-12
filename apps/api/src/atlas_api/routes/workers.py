"""Worker registration, fleet discovery, and heartbeat routes."""

from typing import Annotated, Any

from atlas_core.contracts.worker import WorkerRecord, WorkerStatus
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from atlas_api.auth import AuthenticatedUser, Role, require_role

router = APIRouter(prefix="/api/v1/workers", tags=["Workers"])


class RegisterWorkerPayload(BaseModel):
    """Payload for worker node registration."""

    worker_id: str | None = None
    hostname: str = "localhost"
    capabilities: list[str] = ["browser", "desktop"]
    metadata: dict[str, Any] = {}


def _get_runtime(request: Request):
    runtime = getattr(request.app.state, "runtime", None)
    if not runtime:
        from atlas_agent.runtime import ProductionRuntime

        storage = getattr(request.app.state, "storage", None)
        runtime = ProductionRuntime(storage=storage)
        request.app.state.runtime = runtime
    return runtime


@router.get("", response_model=list[WorkerRecord])
async def list_workers(
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
) -> list[WorkerRecord]:
    """List all registered worker nodes and their current status."""
    runtime = _get_runtime(request)
    return runtime.storage.list_workers()


@router.post("/register", response_model=WorkerRecord, status_code=status.HTTP_201_CREATED)
async def register_worker(
    payload: RegisterWorkerPayload,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.WORKER, Role.ADMIN))],
) -> WorkerRecord:
    """Register or refresh a worker node identity in the worker registry."""
    runtime = _get_runtime(request)
    worker_id = payload.worker_id or "worker_node"
    worker = runtime.worker_registry.register(
        worker_id=worker_id,
        hostname=payload.hostname,
        capabilities=payload.capabilities,
        metadata=payload.metadata,
    )
    return worker


@router.post("/{worker_id}/heartbeat", response_model=WorkerRecord)
async def worker_heartbeat(
    worker_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.WORKER, Role.ADMIN))],
    status_update: WorkerStatus | None = None,
) -> WorkerRecord:
    """Record heartbeat and health signal from an active worker node."""
    runtime = _get_runtime(request)
    try:
        runtime.worker_registry.heartbeat(worker_id, status=status_update)
        worker = runtime.worker_registry.get_worker(worker_id)
        if not worker:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Worker '{worker_id}' is not registered.",
            )
        return worker
    except KeyError as k_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker '{worker_id}' is not registered.",
        ) from k_err
