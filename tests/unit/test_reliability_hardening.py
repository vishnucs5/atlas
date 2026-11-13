"""Unit tests verifying Milestone 2 reliability engineering, crash resilience, and backup/restore."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from atlas_coordination.action_ledger import (
    ActionLedger,
    NonIdempotentActionUncertaintyError,
)
from atlas_coordination.checkpoint_manager import CheckpointManager
from atlas_coordination.lease_manager import WorkerLeaseManager
from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.ledger import ActionExecutionRecord, ActionExecutionStatus
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_storage.backup import (
    BackupIntegrityError,
    create_sqlite_backup,
    restore_sqlite_backup,
    verify_sqlite_backup,
)
from atlas_storage.interfaces import CorruptedCheckpointError, StaleWorkerError
from atlas_storage.sqlite import SQLiteStorage


def test_sqlite_online_backup_and_restore(tmp_path: Path) -> None:
    """Verify live SQLite online backup, SHA-256 metadata integrity, and clean restoration."""
    source_db = tmp_path / "production_source.db"
    backup_db = tmp_path / "backups" / "prod_backup.sqlite"
    restored_db = tmp_path / "restored" / "production_restored.db"

    # 1. Populate source database with tasks, events, checkpoints, leases, and ledger records
    storage = SQLiteStorage(str(source_db))
    storage.initialize()

    now = datetime.now(UTC)
    task = Task(
        task_id="task_live_1",
        objective="Run enterprise workflow",
        status=TaskStatus.RUNNING,
        priority=TaskPriority.HIGH,
        created_at=now,
        updated_at=now,
        metadata={"customer_id": "cust_123"},
    )
    storage.save_task(task)

    event = ExecutionEvent(
        event_id="evt_live_1",
        task_id="task_live_1",
        session_id="sess_1",
        sequence=1,
        event_type=EventType.TASK_CREATED,
        timestamp=now,
        payload={"msg": "created"},
        correlation_id="corr_1",
    )
    storage.append_event(event)

    checkpoint = Checkpoint(
        checkpoint_id="chk_live_1",
        task_id="task_live_1",
        state=TaskStatus.RUNNING,
        sequence=1,
        worker_id="worker_alpha",
        lease_generation=1,
        checkpoint_hash="valid_hash_1",
        created_at=now,
    )
    storage.save_checkpoint(checkpoint)

    record = ActionExecutionRecord(
        action_id="act_live_1",
        task_id="task_live_1",
        idempotency_key="idemp_live_1",
        attempt=1,
        status=ActionExecutionStatus.SUCCEEDED,
        worker_id="worker_alpha",
        lease_generation=1,
        started_at=now,
        completed_at=now,
        action_type="browser.navigate",
        parameters={"url": "https://service.local"},
    )
    storage.record_action_attempt(record)

    # 2. Perform online live backup
    backup_path = create_sqlite_backup(storage, backup_db)
    assert backup_path.is_file()

    meta_path = backup_path.with_name(f"{backup_path.name}.meta.json")
    assert meta_path.is_file()

    # 3. Verify backup checksum and SQLite integrity
    meta = verify_sqlite_backup(backup_path)
    assert meta["table_counts"]["tasks"] >= 1
    assert meta["table_counts"]["execution_events"] >= 1
    assert meta["table_counts"]["checkpoints"] >= 1
    assert meta["table_counts"]["action_ledger"] >= 1

    # 4. Tampering detection: modify byte in backup -> verify_sqlite_backup must fail
    tampered_bytes = bytearray(backup_path.read_bytes())
    tampered_bytes[100] = (tampered_bytes[100] + 1) % 256
    tampered_file = tmp_path / "tampered.db"
    tampered_file.write_bytes(tampered_bytes)

    # Duplicate metadata sidecar for tampered file
    tampered_meta = tampered_file.with_name(f"{tampered_file.name}.meta.json")
    tampered_meta.write_text(meta_path.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(BackupIntegrityError, match="checksum mismatch"):
        verify_sqlite_backup(tampered_file)

    # 5. Restore backup into target
    target_storage = SQLiteStorage(str(restored_db))
    target_storage.initialize()
    restore_sqlite_backup(backup_path, target_storage)

    # 6. Verify restored database has identical records
    restored_task = target_storage.get_task("task_live_1")
    assert restored_task is not None
    assert restored_task.objective == "Run enterprise workflow"
    assert restored_task.metadata.get("customer_id") == "cust_123"

    restored_events = target_storage.get_events("task_live_1")
    assert len(restored_events) == 1
    assert restored_events[0].event_type == EventType.TASK_CREATED

    restored_chk = target_storage.get_checkpoint("chk_live_1")
    assert restored_chk is not None
    assert restored_chk.checkpoint_hash == "valid_hash_1"

    restored_act = target_storage.get_action_record("task_live_1", "idemp_live_1", attempt=1)
    assert restored_act is not None
    assert restored_act.status == ActionExecutionStatus.SUCCEEDED

    storage.close()
    target_storage.close()


def test_action_ledger_unknown_side_effect_safety(tmp_path: Path) -> None:
    """Verify non-idempotent action in UNKNOWN state cannot be retried without reconciliation."""
    storage = SQLiteStorage(str(tmp_path / "ledger_safety.db"))
    storage.initialize()
    ledger = ActionLedger(store=storage)

    # 1. Start a non-idempotent action (e.g. billing charge)
    record = ledger.start_action(
        action_id="act_charge_1",
        task_id="task_charge_1",
        action_type="billing.charge_card",
        parameters={"amount_cents": 5000},
        worker_id="worker_alpha",
        lease_generation=1,
    )
    assert record.attempt == 1

    # 2. Worker network drops -> action outcome transitions to UNKNOWN
    ledger.mark_unknown(
        task_id="task_charge_1",
        idempotency_key=record.idempotency_key,
        attempt=1,
        reason="Worker crashed mid-charge before gateway response was logged",
    )

    # 3. Blind retry attempt must be strictly blocked by NonIdempotentActionUncertaintyError
    with pytest.raises(NonIdempotentActionUncertaintyError, match="cannot be re-executed"):
        ledger.start_action(
            action_id="act_charge_1",
            task_id="task_charge_1",
            action_type="billing.charge_card",
            parameters={"amount_cents": 5000},
            worker_id="worker_beta",
            lease_generation=2,
            force_retry=False,
        )

    # 4. Once explicitly reconciled with force_retry=True, attempt 2 is granted
    retried = ledger.start_action(
        action_id="act_charge_1",
        task_id="task_charge_1",
        action_type="billing.charge_card",
        parameters={"amount_cents": 5000},
        worker_id="worker_beta",
        lease_generation=2,
        force_retry=True,
    )
    assert retried.attempt == 2
    assert retried.status == ActionExecutionStatus.STARTED

    storage.close()


def test_stale_worker_fencing_token_enforcement(tmp_path: Path) -> None:
    """Verify monotonic fencing tokens reject stale worker commits."""
    storage = SQLiteStorage(str(tmp_path / "fencing.db"))
    storage.initialize()
    lease_mgr = WorkerLeaseManager(storage)
    ledger = ActionLedger(store=storage, lease_manager=lease_mgr)

    # Worker 1 acquires task lease at generation 1
    lease_1 = lease_mgr.acquire_lease("task_fence_1", "worker_1", ttl_seconds=30)
    assert lease_1.generation == 1

    # Worker 1 successfully logs action attempt
    rec = ledger.start_action(
        action_id="act_fence_1",
        task_id="task_fence_1",
        action_type="browser.navigate",
        parameters={"url": "https://example.com"},
        worker_id="worker_1",
        lease_generation=1,
    )
    assert rec.status == ActionExecutionStatus.STARTED

    # Worker 1 simulates network freeze; lease is released/re-acquired by Worker 2 at generation 2
    lease_mgr.release_lease(lease_1.lease_id, "worker_1")
    lease_2 = lease_mgr.acquire_lease("task_fence_1", "worker_2", ttl_seconds=30)
    assert lease_2.generation == 2

    # Stale Worker 1 attempts to commit action completion at generation 1 -> must fail with StaleWorkerError
    with pytest.raises(StaleWorkerError, match="Fencing token validation failed"):
        ledger.mark_succeeded(
            task_id="task_fence_1",
            idempotency_key=rec.idempotency_key,
            attempt=1,
            output={"result": "done"},
            lease_generation=1,
            worker_id="worker_1",
        )

    storage.close()


def test_corrupted_checkpoint_recovery_rollback(tmp_path: Path) -> None:
    """Verify CheckpointManager detects tampered SHA-256 seal and rolls back to last verified state."""
    storage = SQLiteStorage(str(tmp_path / "rollback.db"))
    storage.initialize()
    chk_mgr = CheckpointManager(checkpoint_store=storage, event_store=storage)

    # 1. Create valid Checkpoint 1
    chk_1 = chk_mgr.create_checkpoint(
        task_id="task_corrupt_1",
        state=TaskStatus.RUNNING,
        sequence=1,
        worker_id="worker_alpha",
        lease_generation=1,
        state_snapshot={"stage": "step_1_verified"},
    )
    assert chk_mgr.get_checkpoint(chk_1.checkpoint_id, verify=True) is not None

    # 2. Create valid Checkpoint 2
    chk_2 = chk_mgr.create_checkpoint(
        task_id="task_corrupt_1",
        state=TaskStatus.RUNNING,
        sequence=2,
        worker_id="worker_alpha",
        lease_generation=1,
        state_snapshot={"stage": "step_2_modified"},
    )
    assert chk_mgr.get_checkpoint(chk_2.checkpoint_id, verify=True) is not None

    # 3. Simulate database tampering or bit rot on Checkpoint 2's snapshot
    conn = storage._get_connection()
    with conn:
        conn.execute(
            "UPDATE checkpoints SET state_snapshot = ? WHERE checkpoint_id = ?",
            ('{"stage": "tampered_payload"}', chk_2.checkpoint_id),
        )

    # 4. Verification on Checkpoint 2 must raise CorruptedCheckpointError
    with pytest.raises(CorruptedCheckpointError, match="cryptographic integrity check"):
        chk_mgr.get_checkpoint(chk_2.checkpoint_id, verify=True)

    # 5. Rollback to last verified checkpoint (Checkpoint 1)
    reverted_chk = chk_mgr.rollback_to_last_valid(
        task_id="task_corrupt_1",
    )
    assert reverted_chk.checkpoint_id == chk_1.checkpoint_id
    assert reverted_chk.state_snapshot == {"stage": "step_1_verified"}

    storage.close()


def test_sqlite_wal_mode_and_busy_timeout(tmp_path: Path) -> None:
    """Verify file-based SQLite database configures WAL mode and busy timeout."""
    db_file = tmp_path / "wal_test.db"
    storage = SQLiteStorage(str(db_file))
    storage.initialize()

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
        assert mode.lower() == "wal"

        cursor.execute("PRAGMA busy_timeout;")
        timeout = cursor.fetchone()[0]
        assert timeout == 5000
    finally:
        conn.close()
        storage.close()
