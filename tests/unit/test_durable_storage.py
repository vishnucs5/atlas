"""Unit tests for Phase 4 durable storage: checkpoints, action ledger, and worker leases."""

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.ledger import ActionExecutionRecord, ActionExecutionStatus
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_core.contracts.worker import LeaseStatus, WorkerRecord, WorkerStatus
from atlas_storage.interfaces import (
    StaleWorkerError,
    StorageError,
)
from atlas_storage.sqlite import SQLiteStorage


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStorage:
    db_path = tmp_path / "test_durable.db"
    store = SQLiteStorage(str(db_path))
    store.initialize()
    return store


def test_checkpoint_save_and_retrieve(store: SQLiteStorage) -> None:
    now = datetime.now(UTC)
    task = Task(
        task_id="task_chk_1",
        objective="Verify checkpointing",
        status=TaskStatus.RUNNING,
        priority=TaskPriority.HIGH,
        created_at=now,
        updated_at=now,
    )
    store.save_task(task)

    checkpoint = Checkpoint(
        checkpoint_id="chk_001",
        task_id="task_chk_1",
        session_id="sess_1",
        worker_id="worker_alpha",
        lease_generation=1,
        state=TaskStatus.RUNNING,
        sequence=10,
        plan_id="plan_1",
        plan_version=1,
        current_step_id="step_1",
        completed_action_ids=["act_1"],
        pending_action_ids=["act_2"],
        uncertain_action_ids=[],
        last_event_sequence=15,
        state_snapshot={"url": "https://example.com", "step": "form_fill"},
        environment_metadata={"browser": "chromium", "viewport": "1280x720"},
        verification_evidence_refs=["evidence_1"],
        recovery_metadata={"retry_count": 0},
    )
    checkpoint.seal()

    store.save_checkpoint(checkpoint)

    # Verify task pointer updated
    retrieved_task = store.get_task("task_chk_1")
    assert retrieved_task is not None
    assert retrieved_task.current_checkpoint_id == "chk_001"

    # Verify get_checkpoint
    retrieved_chk = store.get_checkpoint("chk_001")
    assert retrieved_chk is not None
    assert retrieved_chk.checkpoint_id == "chk_001"
    assert retrieved_chk.task_id == "task_chk_1"
    assert retrieved_chk.lease_generation == 1
    assert retrieved_chk.verify_hash() is True
    assert retrieved_chk.completed_action_ids == ["act_1"]
    assert retrieved_chk.pending_action_ids == ["act_2"]
    assert retrieved_chk.state_snapshot["step"] == "form_fill"

    # Save second checkpoint
    checkpoint_2 = Checkpoint(
        checkpoint_id="chk_002",
        task_id="task_chk_1",
        session_id="sess_1",
        worker_id="worker_alpha",
        lease_generation=1,
        state=TaskStatus.COMPLETED,
        sequence=20,
    )
    checkpoint_2.seal()
    store.save_checkpoint(checkpoint_2)

    latest = store.get_latest_checkpoint("task_chk_1")
    assert latest is not None
    assert latest.checkpoint_id == "chk_002"

    chk_list = store.list_checkpoints("task_chk_1")
    assert len(chk_list) == 2
    assert chk_list[0].checkpoint_id == "chk_002"
    assert chk_list[1].checkpoint_id == "chk_001"


def test_action_ledger_lifecycle(store: SQLiteStorage) -> None:
    record_1 = ActionExecutionRecord(
        action_id="act_001",
        task_id="task_led_1",
        idempotency_key="idemp_click_submit",
        attempt=1,
        status=ActionExecutionStatus.STARTED,
        worker_id="worker_alpha",
        lease_generation=1,
        action_type="click",
        parameters={"selector": "#submit-btn"},
    )
    store.record_action_attempt(record_1)

    # Integrity collision on duplicate attempt
    with pytest.raises(StorageError):
        store.record_action_attempt(record_1)

    # Retrieve record
    retrieved = store.get_action_record("task_led_1", "idemp_click_submit", 1)
    assert retrieved is not None
    assert retrieved.action_id == "act_001"
    assert retrieved.status == ActionExecutionStatus.STARTED

    # Update status to UNKNOWN (simulating crash)
    updated = store.update_action_status(
        task_id="task_led_1",
        idempotency_key="idemp_click_submit",
        attempt=1,
        status=ActionExecutionStatus.UNKNOWN,
        error="Worker disconnected unexpectedly",
    )
    assert updated.status == ActionExecutionStatus.UNKNOWN
    assert updated.error == "Worker disconnected unexpectedly"

    # Record retry attempt 2
    record_2 = ActionExecutionRecord(
        action_id="act_001",
        task_id="task_led_1",
        idempotency_key="idemp_click_submit",
        attempt=2,
        status=ActionExecutionStatus.STARTED,
        worker_id="worker_beta",
        lease_generation=2,
        action_type="click",
        parameters={"selector": "#submit-btn"},
    )
    store.record_action_attempt(record_2)

    latest = store.get_latest_action("task_led_1", "idemp_click_submit")
    assert latest is not None
    assert latest.attempt == 2
    assert latest.worker_id == "worker_beta"
    assert latest.lease_generation == 2

    # Update attempt 2 to VERIFIED
    verified = store.update_action_status(
        task_id="task_led_1",
        idempotency_key="idemp_click_submit",
        attempt=2,
        status=ActionExecutionStatus.VERIFIED,
        output={"clicked": True},
        verification_result={"element_disappeared": True},
    )
    assert verified.status == ActionExecutionStatus.VERIFIED
    assert verified.output == {"clicked": True}

    all_actions = store.get_task_actions("task_led_1")
    assert len(all_actions) == 2
    assert all_actions[0].attempt == 1
    assert all_actions[1].attempt == 2


def test_worker_registry_and_leases(store: SQLiteStorage) -> None:
    worker_1 = WorkerRecord(
        worker_id="worker_alpha",
        hostname="worker-box-1",
        status=WorkerStatus.IDLE,
        capabilities=["browser", "playwright"],
    )
    store.register_worker(worker_1)

    retrieved_w = store.get_worker("worker_alpha")
    assert retrieved_w is not None
    assert retrieved_w.hostname == "worker-box-1"
    assert "browser" in retrieved_w.capabilities

    # Heartbeat
    store.heartbeat_worker("worker_alpha", status=WorkerStatus.BUSY)
    busy_w = store.get_worker("worker_alpha")
    assert busy_w is not None
    assert busy_w.status == WorkerStatus.BUSY

    workers = store.list_workers(status=WorkerStatus.BUSY)
    assert len(workers) == 1
    assert workers[0].worker_id == "worker_alpha"

    # Acquire lease for task_1
    lease = store.acquire_lease("task_1", "worker_alpha", ttl_seconds=1.0)
    assert lease.task_id == "task_1"
    assert lease.worker_id == "worker_alpha"
    assert lease.generation == 1
    assert lease.status == LeaseStatus.ACTIVE

    # Fencing check
    assert store.validate_lease_fencing("task_1", 1) is True
    assert store.validate_lease_fencing("task_1", 2) is False

    # Second worker cannot acquire active lease
    with pytest.raises(StorageError):
        store.acquire_lease("task_1", "worker_beta", ttl_seconds=1.0)

    # Worker renews lease
    renewed = store.renew_lease(lease.lease_id, "worker_alpha", ttl_seconds=10.0)
    assert renewed.lease_id == lease.lease_id

    # Wrong worker cannot renew
    with pytest.raises(StaleWorkerError):
        store.renew_lease(lease.lease_id, "worker_beta", ttl_seconds=10.0)

    # Active lease check
    active = store.get_active_lease("task_1")
    assert active is not None
    assert active.worker_id == "worker_alpha"

    # Worker releases lease
    store.release_lease(lease.lease_id, "worker_alpha")
    active_after_release = store.get_active_lease("task_1")
    # After release, active status is RELEASED
    assert active_after_release is None


def test_lease_expiry_and_fencing_generation_bump(store: SQLiteStorage) -> None:
    # Acquire very short lease (0.05 seconds)
    lease_1 = store.acquire_lease("task_fenced", "worker_alpha", ttl_seconds=0.05)
    assert lease_1.generation == 1

    time.sleep(0.06)

    # After expiry, validate_lease_fencing returns False
    assert store.validate_lease_fencing("task_fenced", 1) is False

    # New worker can now acquire lease because previous expired
    lease_2 = store.acquire_lease("task_fenced", "worker_beta", ttl_seconds=5.0)
    # Monotonic generation MUST increment
    assert lease_2.generation == 2
    assert lease_2.worker_id == "worker_beta"

    # Generation 1 is completely fenced out
    assert store.validate_lease_fencing("task_fenced", 1) is False
    assert store.validate_lease_fencing("task_fenced", 2) is True
