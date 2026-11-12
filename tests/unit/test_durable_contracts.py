"""Unit tests for Phase 4 durable execution and recovery contracts."""

from datetime import UTC, datetime, timedelta

from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.ledger import (
    ActionExecutionRecord,
    ActionExecutionStatus,
)
from atlas_core.contracts.recovery import (
    FailureClassification,
    ReconciliationDecision,
    ReconciliationResult,
    RecoveryStrategy,
)
from atlas_core.contracts.task import TaskStatus
from atlas_core.contracts.worker import (
    LeaseStatus,
    WorkerLease,
    WorkerRecord,
    WorkerStatus,
)


def test_checkpoint_creation_and_tamper_evident_hash():
    """Verify Checkpoint creates deterministic hashes and detects tampering."""
    now = datetime.now(UTC)
    cp = Checkpoint(
        checkpoint_id="cp_test_001",
        task_id="task_001",
        sequence=5,
        state=TaskStatus.RUNNING,
        timestamp=now,
        session_id="sess_001",
        worker_id="worker_alpha",
        lease_generation=2,
        plan_id="plan_001",
        plan_version=1,
        current_step_id="step_2",
        completed_action_ids=["act_1"],
        pending_action_ids=["act_2"],
        uncertain_action_ids=[],
        last_event_sequence=12,
        state_snapshot={"var_x": 42},
        environment_metadata={"url": "https://example.com/checkout"},
        verification_evidence_refs=["evidence_001"],
    )

    # Initial state without seal has no hash
    assert cp.checkpoint_hash is None
    assert not cp.verify_hash()

    # Seal computes and sets hash
    cp.seal()
    assert cp.checkpoint_hash is not None
    assert len(cp.checkpoint_hash) == 64
    assert cp.verify_hash()

    # Tampering with any field invalidates the integrity hash
    cp.state = TaskStatus.FAILED
    assert not cp.verify_hash()


def test_worker_record_and_status():
    """Verify WorkerRecord model and capability tracking."""
    now = datetime.now(UTC)
    worker = WorkerRecord(
        worker_id="w_node_1",
        hostname="worker-vm-01",
        status=WorkerStatus.IDLE,
        capabilities=["browser", "playwright", "chromium"],
        registered_at=now,
        last_heartbeat_at=now,
    )
    assert worker.status == WorkerStatus.IDLE
    assert "chromium" in worker.capabilities

    data = worker.model_dump()
    assert data["worker_id"] == "w_node_1"
    assert data["status"] == "IDLE"


def test_worker_lease_expiration_and_fencing():
    """Verify WorkerLease tracking and is_expired deadline check."""
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=30)
    lease = WorkerLease(
        lease_id="lease_001",
        task_id="task_001",
        worker_id="w_node_1",
        generation=3,
        status=LeaseStatus.ACTIVE,
        acquired_at=now,
        expires_at=expires,
    )

    assert not lease.is_expired(now)
    assert lease.generation == 3

    # Check after expiry
    past_expiry = now + timedelta(seconds=35)
    assert lease.is_expired(past_expiry)

    # Revoked lease is expired even before deadline
    lease.status = LeaseStatus.REVOKED
    assert lease.is_expired(now)


def test_action_execution_record():
    """Verify ActionExecutionRecord supports detailed tri-state tracking."""
    now = datetime.now(UTC)
    record = ActionExecutionRecord(
        action_id="act_checkout_submit",
        task_id="task_001",
        idempotency_key="hash_abc123",
        attempt=1,
        status=ActionExecutionStatus.UNKNOWN,
        worker_id="w_node_1",
        lease_generation=1,
        started_at=now,
        action_type="browser.click",
        parameters={"selector": "#confirm-payment"},
    )
    assert record.status == ActionExecutionStatus.UNKNOWN
    assert record.attempt == 1
    assert record.completed_at is None


def test_recovery_and_reconciliation_contracts():
    """Verify RecoveryStrategy, FailureClassification, and ReconciliationResult."""
    result = ReconciliationResult(
        matches_expected=False,
        observed_url="https://example.com/order-success",
        observed_title="Order Success",
        pending_action_handled=True,
        decision=ReconciliationDecision.RESUME,
        reason="Order already submitted successfully before process interruption",
    )
    assert not result.matches_expected
    assert result.decision == ReconciliationDecision.RESUME
    assert result.pending_action_handled is True

    assert FailureClassification.WORKER_CRASH == "WORKER_CRASH"
    assert RecoveryStrategy.RECONCILE_ENVIRONMENT == "RECONCILE_ENVIRONMENT"
