"""Unit tests for EnvironmentReconciler and RecoveryCoordinator."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from atlas_coordination.action_ledger import ActionLedger
from atlas_coordination.checkpoint_manager import CheckpointManager
from atlas_coordination.lease_manager import WorkerLeaseManager
from atlas_coordination.reconciler import EnvironmentReconciler
from atlas_coordination.recovery_coordinator import RecoveryCoordinator
from atlas_coordination.worker_registry import WorkerRegistryManager
from atlas_core.contracts.event import EventType
from atlas_core.contracts.ledger import ActionExecutionRecord, ActionExecutionStatus
from atlas_core.contracts.recovery import (
    FailureClassification,
    ReconciliationDecision,
    RecoveryStrategy,
)
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_policy.firewall import ActionFirewall
from atlas_storage.interfaces import CorruptedCheckpointError, StaleWorkerError
from atlas_storage.sqlite import SQLiteStorage


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStorage:
    db = tmp_path / "test_rec.db"
    s = SQLiteStorage(str(db))
    s.initialize()
    return s


def test_failure_classification(store: SQLiteStorage) -> None:
    chk_mgr = CheckpointManager(store)
    ledger = ActionLedger(store)
    reconciler = EnvironmentReconciler()
    coord = RecoveryCoordinator(chk_mgr, ledger, reconciler)

    assert (
        coord.classify_failure(CorruptedCheckpointError("hash mismatch"))
        == FailureClassification.CORRUPTED_CHECKPOINT
    )
    assert (
        coord.classify_failure(StaleWorkerError("fencing failed"))
        == FailureClassification.LEASE_EXPIRED
    )
    assert (
        coord.classify_failure(Exception("Target closed: browser crashed"))
        == FailureClassification.BROWSER_DISCONNECTION
    )
    assert (
        coord.classify_failure(Exception("network connection refused"))
        == FailureClassification.NETWORK_DISCONNECTION
    )
    assert (
        coord.classify_failure(Exception("postcondition verification failed"))
        == FailureClassification.VERIFICATION_FAILED
    )


def test_environment_reconciliation_logic(store: SQLiteStorage) -> None:
    chk_mgr = CheckpointManager(store)
    reconciler = EnvironmentReconciler()

    chk = chk_mgr.create_checkpoint(
        task_id="t_rec_1",
        state=TaskStatus.RUNNING,
        sequence=1,
        state_snapshot={"url": "https://example.com/checkout", "title": "Checkout"},
    )

    # 1. Exact match
    res1 = reconciler.reconcile(
        checkpoint=chk,
        live_environment={"url": "https://example.com/checkout", "title": "Checkout"},
    )
    assert res1.matches_expected is True
    assert res1.decision == ReconciliationDecision.RESUME

    # 2. Drifted URL, no pending actions
    res2 = reconciler.reconcile(
        checkpoint=chk,
        live_environment={"url": "https://example.com/other", "title": "Other"},
    )
    assert res2.matches_expected is False
    assert res2.decision == ReconciliationDecision.RESTART_STEP

    # 3. Uncertain non-idempotent action with physical confirmation
    act_record = ActionExecutionRecord(
        action_id="act_submit",
        task_id="t_rec_1",
        idempotency_key="key_sub",
        attempt=1,
        status=ActionExecutionStatus.UNKNOWN,
        worker_id="w1",
        action_type="click",
        parameters={"selector": "#confirm-order"},
    )
    # Physical environment navigated to order receipt page
    res3 = reconciler.reconcile(
        checkpoint=chk,
        live_environment={
            "url": "https://example.com/order-receipt",
            "dom": "<h1>Order Placed Successfully</h1>",
        },
        pending_actions=[act_record],
    )
    assert res3.pending_action_handled is True
    assert res3.decision == ReconciliationDecision.RESUME

    # 4. Uncertain non-idempotent action WITHOUT physical confirmation
    res4 = reconciler.reconcile(
        checkpoint=chk,
        live_environment={
            "url": "https://example.com/checkout",
            "dom": "<form id='checkout'></form>",
        },
        pending_actions=[act_record],
    )
    assert res4.pending_action_handled is False
    assert res4.decision == ReconciliationDecision.REQUEST_APPROVAL


def test_recovery_lifecycle_and_bounded_retries(store: SQLiteStorage) -> None:
    now = datetime.now(UTC)
    task = Task(
        task_id="t_recover_1",
        objective="Order testing",
        status=TaskStatus.RUNNING,
        priority=TaskPriority.HIGH,
        created_at=now,
        updated_at=now,
    )
    store.save_task(task)

    chk_mgr = CheckpointManager(store, event_store=store)
    chk_mgr.create_checkpoint(task_id="t_recover_1", state=TaskStatus.RUNNING, sequence=1)
    chk2 = chk_mgr.create_checkpoint(task_id="t_recover_1", state=TaskStatus.RUNNING, sequence=2)

    registry = WorkerRegistryManager(store)
    registry.register("w1", "h1", ["browser"])
    lease_mgr = WorkerLeaseManager(store)
    lease = lease_mgr.acquire_lease("t_recover_1", "w1", ttl_seconds=30.0)

    ledger = ActionLedger(store, lease_manager=lease_mgr)
    act = ledger.start_action(
        action_id="act_checkout",
        task_id="t_recover_1",
        action_type="click",
        parameters={"selector": "#buy"},
        worker_id="w1",
        lease_generation=lease.generation,
    )
    ledger.mark_unknown("t_recover_1", act.idempotency_key, 1, "Process killed")

    reconciler = EnvironmentReconciler()
    coord = RecoveryCoordinator(
        checkpoint_manager=chk_mgr,
        action_ledger=ledger,
        reconciler=reconciler,
        lease_manager=lease_mgr,
        task_store=store,
        event_store=store,
        max_retries=2,
    )

    # Recovery with physical evidence of completion
    strategy, recovered_chk, summary = coord.execute_recovery(
        task_id="t_recover_1",
        error="Browser disconnected unexpectedly",
        current_worker_id="w1",
        expected_lease_generation=lease.generation,
        live_environment={"url": "https://example.com/success", "dom": "Your order is confirmed"},
        retry_count=0,
    )
    assert strategy == RecoveryStrategy.RESUME_FROM_CHECKPOINT
    assert recovered_chk is not None
    assert recovered_chk.checkpoint_id == chk2.checkpoint_id

    # Ledger record should now be VERIFIED
    latest_act = ledger.get_latest_action("t_recover_1", act.idempotency_key)
    assert latest_act is not None
    assert latest_act.status == ActionExecutionStatus.VERIFIED

    # Check event was emitted
    events = store.get_events("t_recover_1")
    rec_events = [e for e in events if e.event_type == EventType.RECOVERY_STARTED]
    assert len(rec_events) == 1

    # Bounded retries: exceeding max_retries marks task FAILED
    strat_fail, _, _ = coord.execute_recovery(
        task_id="t_recover_1",
        error="Crash repeated",
        retry_count=3,
    )
    assert strat_fail == RecoveryStrategy.FAIL_TASK
    failed_task = store.get_task("t_recover_1")
    assert failed_task is not None
    assert failed_task.status == TaskStatus.FAILED


def test_firewall_enforcement_during_recovery(store: SQLiteStorage) -> None:
    now = datetime.now(UTC)
    task = Task(
        task_id="t_fw_rec",
        objective="Payment check",
        status=TaskStatus.RUNNING,
        priority=TaskPriority.HIGH,
        created_at=now,
        updated_at=now,
    )
    store.save_task(task)

    chk_mgr = CheckpointManager(store, event_store=store)
    chk_mgr.create_checkpoint(task_id="t_fw_rec", state=TaskStatus.RUNNING, sequence=1)

    ledger = ActionLedger(store)
    reconciler = EnvironmentReconciler()
    firewall = ActionFirewall()

    coord = RecoveryCoordinator(
        checkpoint_manager=chk_mgr,
        action_ledger=ledger,
        reconciler=reconciler,
        firewall=firewall,
        task_store=store,
        event_store=store,
    )

    # Recovery from unknown action outcome with firewall configured and operator_approved=False
    # MUST enforce REQUEST_APPROVAL (Rule 2: Action Firewall controls execution)
    strat, chk, summary = coord.execute_recovery(
        task_id="t_fw_rec",
        error="NonIdempotentActionUncertaintyError: payment outcome unknown",
        operator_approved=False,
    )
    assert strat == RecoveryStrategy.REQUEST_APPROVAL
    assert "operator approval" in summary.lower()
