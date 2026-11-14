"""Unit tests for Durable Fault Tolerance, Worker Eviction, and Unknown Outcome Reconciliation (Milestone 5)."""

from datetime import UTC, datetime, timedelta

import pytest
from atlas_coordination.action_ledger import NonIdempotentActionUncertaintyError
from atlas_core.contracts.worker import WorkerStatus
from atlas_distributed.enrollment import WorkerEnrollmentAuthority
from atlas_distributed.fault_tolerance import DistributedRecoveryManager
from atlas_distributed.models import (
    AssignmentResult,
    AssignmentStatus,
    EnrollmentRequest,
    WorkerCapabilities,
)
from atlas_distributed.scheduler import DistributedScheduler, TaskRequirements
from atlas_storage.interfaces import StaleWorkerError


@pytest.fixture
def authority() -> WorkerEnrollmentAuthority:
    return WorkerEnrollmentAuthority()


def enroll_worker(authority: WorkerEnrollmentAuthority, tenant_id: str = "default"):
    token, _ = authority.create_enrollment_token(tenant_id=tenant_id)
    req = EnrollmentRequest(
        provisioning_token=token,
        hostname="node-ft",
        capabilities=WorkerCapabilities(drivers=["bash", "playwright", "desktop"]),
        tenant_id=tenant_id,
    )
    return authority.enroll_worker(req)


def test_dead_worker_detection_on_heartbeat_timeout(authority):
    """Verify dead worker detection when heartbeats miss the deadline."""
    resp1 = enroll_worker(authority)
    resp2 = enroll_worker(authority)

    scheduler = DistributedScheduler(enrollment_authority=authority)
    recovery_mgr = DistributedRecoveryManager(
        enrollment_authority=authority,
        scheduler=scheduler,
        heartbeat_timeout_seconds=10.0,
    )

    # Worker 1 is healthy (recent heartbeat)
    authority.authenticate_worker(resp1.worker_id, resp1.auth_token)

    # Worker 2 is unresponsive (heartbeat 25 seconds in the past)
    worker2 = authority.get_worker(resp2.worker_id)
    assert worker2 is not None
    worker2.last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=25.0)

    # Run dead worker detection
    evicted = recovery_mgr.detect_and_handle_dead_workers()

    assert resp2.worker_id in evicted
    assert resp1.worker_id not in evicted
    assert worker2.status == WorkerStatus.DISCONNECTED


def test_stale_worker_fencing_rejection(authority):
    """Verify stale worker completing an obsolete generation lease is rejected with StaleWorkerError."""
    resp = enroll_worker(authority)
    scheduler = DistributedScheduler(enrollment_authority=authority)
    recovery_mgr = DistributedRecoveryManager(
        enrollment_authority=authority,
        scheduler=scheduler,
    )

    # Schedule task at generation 1
    _, payload = scheduler.schedule_task(TaskRequirements(task_id="t_fenced"))
    assert payload.generation == 1
    recovery_mgr.register_assignment(payload)

    # Simulate generation bump (e.g. timeout reassignment happened, generation became 2)
    payload.generation = 2

    # Stale worker tries to complete at generation 1
    stale_result = AssignmentResult(
        assignment_id=payload.assignment_id,
        task_id=payload.task_id,
        worker_id=resp.worker_id,
        generation=1,  # Stale!
        status=AssignmentStatus.COMPLETED,
    )

    with pytest.raises(StaleWorkerError) as exc_info:
        recovery_mgr.validate_fencing_and_complete(stale_result)

    assert "Stale worker completion rejected" in str(exc_info.value)
    assert "generation 1 < active generation 2" in str(exc_info.value)


def test_idempotent_action_safe_automatic_reassignment(authority):
    """Verify idempotent actions (e.g. screenshot, navigate) reassign automatically on worker crash."""
    resp1 = enroll_worker(authority)
    enroll_worker(authority)  # Backup worker

    scheduler = DistributedScheduler(enrollment_authority=authority)
    recovery_mgr = DistributedRecoveryManager(
        enrollment_authority=authority,
        scheduler=scheduler,
    )

    # Idempotent action assignment
    _, payload = scheduler.schedule_task(
        TaskRequirements(
            task_id="t_idemp",
            action_type="screenshot",
            objective="Capture page screenshot",
        )
    )
    recovery_mgr.register_assignment(payload)

    # Worker 1 crashes / partitions
    recovered_states = recovery_mgr.recover_worker_assignments(resp1.worker_id)
    assert len(recovered_states) == 1
    state = recovered_states[0]
    assert state.requires_reconciliation is False

    # Check recovery state record
    rec = recovery_mgr.get_recovery_state(payload.assignment_id)
    assert rec is not None
    assert rec.requires_reconciliation is False


def test_non_idempotent_action_uncertainty_safety_and_reconciliation(authority):
    """Verify non-idempotent actions in flight on crashed workers halt and require reconciliation."""
    resp1 = enroll_worker(authority)
    enroll_worker(authority)  # Backup worker

    scheduler = DistributedScheduler(enrollment_authority=authority)
    recovery_mgr = DistributedRecoveryManager(
        enrollment_authority=authority,
        scheduler=scheduler,
    )

    # Non-idempotent action assignment (e.g. submit_payment or database delete)
    _, payload = scheduler.schedule_task(
        TaskRequirements(
            task_id="t_danger",
            action_type="submit_payment",
            objective="Submit credit card charge",
        )
    )
    recovery_mgr.register_assignment(payload)

    # Worker 1 crashes while executing non-idempotent action
    recovered_states = recovery_mgr.recover_worker_assignments(resp1.worker_id)
    assert len(recovered_states) == 1
    state = recovered_states[0]
    assert state.requires_reconciliation is True
    assert "Non-idempotent action" in (state.reconciliation_reason or "")

    # Attempting to reassign blindly MUST raise NonIdempotentActionUncertaintyError
    with pytest.raises(NonIdempotentActionUncertaintyError) as exc_info:
        recovery_mgr.reassign_assignment(payload)
    assert "reconciliation" in str(exc_info.value).lower()

    # Reconcile external state (operator inspects payment gateway and verifies charge was not made)
    reconciled = recovery_mgr.reconcile_external_action(
        assignment_id=payload.assignment_id,
        verified_status="VERIFIED_NOT_EXECUTED",
        notes="Payment gateway log confirms no transaction received",
    )
    assert reconciled.reconciled is True
    assert reconciled.reconciled_status == "VERIFIED_NOT_EXECUTED"

    # Now reassignment is permitted safely!
    new_assignment = recovery_mgr.reassign_assignment(payload, force_after_reconciliation=True)
    assert new_assignment.task_id == payload.task_id
    assert new_assignment.generation > payload.generation
