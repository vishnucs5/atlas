"""REST API endpoints for ATLAS Distributed Execution Network (Phase 9)."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from atlas_core.contracts.worker import WorkerStatus
from atlas_distributed.coordinator import DistributedTaskCoordinator
from atlas_distributed.enrollment import (
    EnrollmentError,
    SessionZeroInteractiveError,
    WorkerEnrollmentAuthority,
)
from atlas_distributed.fault_tolerance import DistributedRecoveryManager
from atlas_distributed.models import (
    AssignmentProgress,
    AssignmentResult,
    EnrollmentRequest,
    EnrollmentResponse,
    WorkerHeartbeat,
)
from atlas_distributed.scheduler import (
    DistributedScheduler,
    NoEligibleWorkerError,
    SchedulerQueueFullError,
    TaskRequirements,
)
from atlas_storage.interfaces import StaleWorkerError
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("atlas.api.distributed")

router = APIRouter(prefix="/api/v1/distributed", tags=["Distributed Network"])

_authority: WorkerEnrollmentAuthority | None = None
_scheduler: DistributedScheduler | None = None
_recovery_manager: DistributedRecoveryManager | None = None
_coordinator: DistributedTaskCoordinator | None = None


def get_distributed_services() -> tuple[
    WorkerEnrollmentAuthority,
    DistributedScheduler,
    DistributedRecoveryManager,
    DistributedTaskCoordinator,
]:
    """Provide singleton distributed network services."""
    global _authority, _scheduler, _recovery_manager, _coordinator
    if _authority is None:
        _authority = WorkerEnrollmentAuthority()
        _scheduler = DistributedScheduler(enrollment_authority=_authority)
        _recovery_manager = DistributedRecoveryManager(
            enrollment_authority=_authority,
            scheduler=_scheduler,
        )
        _coordinator = DistributedTaskCoordinator(scheduler=_scheduler)
    return _authority, _scheduler, _recovery_manager, _coordinator


def reset_distributed_services() -> None:
    """Reset singletons for fresh test runs."""
    global _authority, _scheduler, _recovery_manager, _coordinator
    _authority = None
    _scheduler = None
    _recovery_manager = None
    _coordinator = None


class CreateTokenRequest(BaseModel):
    """Payload to generate a new worker provisioning token."""

    model_config = ConfigDict(validate_assignment=True)

    tenant_id: str = "default"
    max_uses: int = 1
    ttl_hours: float = 24.0
    created_by: str = "admin"


class RevokeWorkerRequest(BaseModel):
    """Payload to revoke an active worker node."""

    model_config = ConfigDict(validate_assignment=True)

    reason: str = "Administrative revocation"


class ReconcileRequest(BaseModel):
    """Payload to manually reconcile in-doubt action outcome."""

    model_config = ConfigDict(validate_assignment=True)

    assignment_id: str
    verified_status: str
    notes: str = ""


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
def create_enrollment_token(req: CreateTokenRequest) -> dict[str, Any]:
    """Generate a cryptographic provisioning token for candidate worker enrollment."""
    authority, _, _, _ = get_distributed_services()
    raw_token, token_record = authority.create_enrollment_token(
        tenant_id=req.tenant_id,
        ttl=timedelta(hours=req.ttl_hours),
        max_uses=req.max_uses,
        created_by=req.created_by,
    )
    return {
        "provisioning_token": raw_token,
        "token_id": token_record.token_id,
        "tenant_id": token_record.tenant_id,
        "expires_at": token_record.expires_at.isoformat(),
        "max_uses": token_record.max_uses,
    }


@router.post("/enroll", status_code=status.HTTP_201_CREATED)
def enroll_worker(req: EnrollmentRequest) -> EnrollmentResponse:
    """Enroll a new worker node into the distributed execution network."""
    authority, _, _, _ = get_distributed_services()
    try:
        response = authority.enroll_worker(req)
        logger.info("Enrolled worker %s for tenant %s", response.worker_id, response.tenant_id)
        return response
    except SessionZeroInteractiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session 0 Invariant Violation: {exc}",
        ) from exc
    except EnrollmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Enrollment rejected: {exc}",
        ) from exc


@router.post("/workers/{worker_id}/heartbeat")
def record_heartbeat(worker_id: str, heartbeat: WorkerHeartbeat) -> dict[str, Any]:
    """Ingest periodic worker heartbeat and health telemetry."""
    authority, _, recovery_mgr, _ = get_distributed_services()
    worker = authority.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")

    worker.last_heartbeat_at = datetime.now(UTC)
    worker.status = heartbeat.status
    worker.metadata["cpu_percent"] = heartbeat.cpu_percent
    worker.metadata["memory_percent"] = heartbeat.memory_percent

    return {
        "acknowledged": True,
        "worker_id": worker_id,
        "sequence_number": heartbeat.sequence_number,
    }


@router.post("/workers/{worker_id}/revoke")
def revoke_worker(worker_id: str, req: RevokeWorkerRequest) -> dict[str, Any]:
    """Revoke worker authorization and append to CRL."""
    authority, _, _, _ = get_distributed_services()
    try:
        authority.revoke_worker(worker_id, reason=req.reason)
        return {"revoked": True, "worker_id": worker_id, "reason": req.reason}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/workers")
def list_workers(tenant_id: str | None = Query(None)) -> list[dict[str, Any]]:
    """List enrolled workers with credentials securely redacted."""
    authority, _, _, _ = get_distributed_services()
    workers = authority.list_workers(tenant_id=tenant_id)
    result = []
    for w in workers:
        data = w.model_dump(mode="json")
        data.pop("auth_token_hash", None)
        result.append(data)
    return result


@router.get("/workers/{worker_id}")
def get_worker(worker_id: str) -> dict[str, Any]:
    """Retrieve details for a specific worker node."""
    authority, _, _, _ = get_distributed_services()
    worker = authority.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    data = worker.model_dump(mode="json")
    data.pop("auth_token_hash", None)
    return data


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
def schedule_assignment(req: TaskRequirements) -> dict[str, Any]:
    """Submit a task to the distributed scheduler for immediate matching or priority queuing."""
    _, scheduler, recovery_mgr, _ = get_distributed_services()
    try:
        worker, payload = scheduler.schedule_task(req)
        recovery_mgr.register_assignment(payload)
        return {
            "worker_id": worker.worker_id,
            "assignment": payload.model_dump(mode="json"),
        }
    except NoEligibleWorkerError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except SchedulerQueueFullError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc


@router.post("/assignments/{assignment_id}/progress")
def record_progress(assignment_id: str, progress: AssignmentProgress) -> dict[str, Any]:
    """Stream real-time progress update for an active assignment."""
    logger.debug(
        "Progress received for %s: step=%d, msg=%s",
        assignment_id,
        progress.step_index,
        progress.message,
    )
    return {"acknowledged": True, "assignment_id": assignment_id}


@router.post("/assignments/{assignment_id}/complete")
def complete_assignment(assignment_id: str, result: AssignmentResult) -> dict[str, Any]:
    """Deliver assignment execution result and validate monotonic fencing token."""
    _, _, recovery_mgr, _ = get_distributed_services()
    try:
        verified = recovery_mgr.validate_fencing_and_complete(result)
        return {
            "acknowledged": True,
            "verified": verified,
            "status": result.status.value,
        }
    except StaleWorkerError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Stale worker fencing violation: {exc}",
        ) from exc


@router.post("/reconcile")
def reconcile_outcome(req: ReconcileRequest) -> dict[str, Any]:
    """Manually reconcile physical outcome of an in-doubt action after worker crash or partition."""
    _, _, recovery_mgr, _ = get_distributed_services()
    try:
        state = recovery_mgr.reconcile_external_action(
            assignment_id=req.assignment_id,
            verified_status=req.verified_status,
            notes=req.notes,
        )
        return {
            "reconciled": state.reconciled,
            "assignment_id": state.assignment_id,
            "task_id": state.task_id,
            "status": state.reconciled_status,
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/fleet/metrics")
def get_fleet_metrics() -> dict[str, Any]:
    """Retrieve aggregated fleet health, capacity, queue depth, and platform distribution."""
    authority, scheduler, recovery_mgr, _ = get_distributed_services()

    # Check for dead workers first
    recovery_mgr.detect_and_handle_dead_workers()

    workers = authority.list_workers()
    total_workers = len(workers)
    active_workers = sum(
        1 for w in workers if not w.is_revoked and w.status != WorkerStatus.TERMINATED
    )
    busy_workers = sum(1 for w in workers if w.status == WorkerStatus.BUSY)
    disconnected_workers = sum(1 for w in workers if w.status == WorkerStatus.DISCONNECTED)

    platforms: dict[str, int] = {}
    sessions: dict[str, int] = {}
    for w in workers:
        p = w.capabilities.platform.value
        platforms[p] = platforms.get(p, 0) + 1
        s = w.capabilities.session_type.value
        sessions[s] = sessions.get(s, 0) + 1

    return {
        "total_workers": total_workers,
        "active_workers": active_workers,
        "busy_workers": busy_workers,
        "disconnected_workers": disconnected_workers,
        "queue_depth": scheduler.get_queue_depth(),
        "platforms": platforms,
        "sessions": sessions,
    }
