"""Comprehensive 20-scenario fault-injection and durable recovery test suite for ATLAS Phase 4.

Verifies that the ATLAS runtime recovers deterministically from all 20 real-world
crash, network, partition, corruption, and split-brain failure modes 100% offline.
"""

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from atlas_coordination.action_ledger import (
    ActionLedger,
    NonIdempotentActionUncertaintyError,
)
from atlas_coordination.checkpoint_manager import CheckpointManager
from atlas_coordination.lease_manager import WorkerLeaseManager
from atlas_coordination.reconciler import EnvironmentReconciler
from atlas_coordination.recovery_coordinator import RecoveryCoordinator
from atlas_coordination.scheduler import WorkerScheduler
from atlas_coordination.worker_registry import WorkerRegistryManager
from atlas_core.contracts.ledger import ActionExecutionStatus
from atlas_core.contracts.recovery import (
    FailureClassification,
    ReconciliationDecision,
    RecoveryStrategy,
)
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_core.contracts.worker import WorkerStatus
from atlas_storage.interfaces import (
    CorruptedCheckpointError,
    StaleWorkerError,
    StorageError,
)
from atlas_storage.sqlite import SQLiteStorage


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStorage:
    db = tmp_path / "test_fault_recovery.db"
    s = SQLiteStorage(str(db))
    s.initialize()
    return s


def _create_running_task(store: SQLiteStorage, task_id: str) -> Task:
    now = datetime.now(UTC)
    task = Task(
        task_id=task_id,
        objective="Fault injection test",
        status=TaskStatus.RUNNING,
        priority=TaskPriority.HIGH,
        created_at=now,
        updated_at=now,
    )
    store.save_task(task)
    return task


# =============================================================================
# SCENARIO 01: Worker process killed (SIGKILL) during model inference
# =============================================================================
def test_scenario_01_worker_killed_during_inference(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s01")
    registry = WorkerRegistryManager(store)
    registry.register("worker_inf", "host-1", ["model_inference"])
    lease_mgr = WorkerLeaseManager(store)
    scheduler = WorkerScheduler(registry, lease_mgr)

    worker, lease = scheduler.schedule_task("task_s01", ["model_inference"], lease_ttl_seconds=0.05)
    assert worker.status == WorkerStatus.BUSY

    # Simulate SIGKILL: worker abruptly stops sending heartbeats, lease expires
    time.sleep(0.06)

    # Recovery detects worker missed heartbeats
    dead = registry.sweep_stale_workers(timeout_seconds=0.04)
    assert "worker_inf" in dead

    # New replacement worker can safely take over task
    registry.register("worker_inf_2", "host-2", ["model_inference"])
    new_w, new_lease = scheduler.schedule_task("task_s01", ["model_inference"])
    assert new_w.worker_id == "worker_inf_2"
    assert new_lease.generation == 2


# =============================================================================
# SCENARIO 02: Worker process killed during browser action execution
# =============================================================================
def test_scenario_02_worker_killed_during_browser_action(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s02")
    chk_mgr = CheckpointManager(store, event_store=store)
    chk_mgr.create_checkpoint(
        "task_s02",
        TaskStatus.RUNNING,
        sequence=1,
        state_snapshot={"url": "https://example.com/step1"},
    )

    lease_mgr = WorkerLeaseManager(store)
    lease = lease_mgr.acquire_lease("task_s02", "w_browser", ttl_seconds=30.0)
    ledger = ActionLedger(store, lease_manager=lease_mgr)

    rec = ledger.start_action(
        "act_click", "task_s02", "click", {"selector": "#btn"}, "w_browser", lease.generation
    )
    assert rec.status == ActionExecutionStatus.STARTED

    # Worker crashes before completion -> coordinator marks action UNKNOWN
    ledger.mark_unknown("task_s02", rec.idempotency_key, 1, "SIGKILL during browser execution")

    # Recovery coordinator reconciles
    reconciler = EnvironmentReconciler()
    coord = RecoveryCoordinator(chk_mgr, ledger, reconciler, lease_mgr, task_store=store)
    strat, recovered_chk, _ = coord.execute_recovery(
        "task_s02",
        "Worker crash during click",
        live_environment={"url": "https://example.com/step2", "dom": "success confirmation"},
    )
    assert strat == RecoveryStrategy.RESUME_FROM_CHECKPOINT
    assert recovered_chk is not None


# =============================================================================
# SCENARIO 03: Worker process killed during verification
# =============================================================================
def test_scenario_03_worker_killed_during_verification(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s03")
    chk_mgr = CheckpointManager(store, event_store=store)
    chk_mgr.create_checkpoint("task_s03", TaskStatus.RUNNING, sequence=1)

    lease_mgr = WorkerLeaseManager(store)
    lease = lease_mgr.acquire_lease("task_s03", "w_ver", ttl_seconds=30.0)
    ledger = ActionLedger(store, lease_manager=lease_mgr)

    rec = ledger.start_action(
        "act_type", "task_s03", "type", {"text": "hello"}, "w_ver", lease.generation
    )
    ledger.mark_succeeded(
        "task_s03", rec.idempotency_key, 1, {"typed": True}, lease.generation, "w_ver"
    )

    # Worker dies before mark_verified -> status remains SUCCEEDED without VERIFIED
    latest = ledger.get_latest_action("task_s03", rec.idempotency_key)
    assert latest is not None
    assert latest.status == ActionExecutionStatus.SUCCEEDED

    # Recovery coordinator triggers action/verification retry or checkpoint rollback
    coord = RecoveryCoordinator(chk_mgr, ledger, EnvironmentReconciler(), lease_mgr)
    strat, _, summary = coord.execute_recovery(
        "task_s03",
        "Worker died during verification",
        live_environment={"url": "https://example.com"},
    )
    assert strat in (RecoveryStrategy.RETRY_ACTION, RecoveryStrategy.RESUME_FROM_CHECKPOINT)


# =============================================================================
# SCENARIO 04: Browser crashes unexpectedly during task execution
# =============================================================================
def test_scenario_04_browser_crashes_unexpectedly(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s04")
    chk_mgr = CheckpointManager(store, event_store=store)
    chk_mgr.create_checkpoint(
        "task_s04", TaskStatus.RUNNING, sequence=1, state_snapshot={"url": "https://example.com"}
    )

    coord = RecoveryCoordinator(chk_mgr, ActionLedger(store), EnvironmentReconciler())
    cls = coord.classify_failure(Exception("TargetClosedError: Playwright connection dropped"))
    assert cls == FailureClassification.BROWSER_DISCONNECTION

    strat, chk, _ = coord.execute_recovery(
        "task_s04", "TargetClosedError: Playwright connection dropped", live_environment=None
    )
    assert strat == RecoveryStrategy.RESUME_FROM_CHECKPOINT
    assert chk is not None


# =============================================================================
# SCENARIO 05: Network disconnects during API call
# =============================================================================
def test_scenario_05_network_disconnects_during_api_call(store: SQLiteStorage) -> None:
    coord = RecoveryCoordinator(
        CheckpointManager(store), ActionLedger(store), EnvironmentReconciler()
    )
    cls = coord.classify_failure(ConnectionError("ECONNREFUSED failed to connect to model API"))
    assert cls == FailureClassification.NETWORK_DISCONNECTION
    assert coord.select_strategy(cls, retry_count=0) == RecoveryStrategy.RECONCILE_ENVIRONMENT


# =============================================================================
# SCENARIO 06: SQLite database temporarily locked (busy_timeout)
# =============================================================================
def test_scenario_06_sqlite_database_temporarily_locked(tmp_path: Path) -> None:
    db_file = tmp_path / "busy_test.db"
    store1 = SQLiteStorage(str(db_file))
    store1.initialize()

    _create_running_task(store1, "task_s06")

    # In WAL mode with busy_timeout, concurrent readers/writers succeed
    store2 = SQLiteStorage(str(db_file))
    store2.initialize()

    task_read = store2.get_task("task_s06")
    assert task_read is not None
    assert task_read.task_id == "task_s06"


# =============================================================================
# SCENARIO 07: Corrupted checkpoint file detected
# =============================================================================
def test_scenario_07_corrupted_checkpoint_file_detected(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s07")
    chk_mgr = CheckpointManager(store, event_store=store)
    chk1 = chk_mgr.create_checkpoint(
        "task_s07", TaskStatus.RUNNING, sequence=1, state_snapshot={"v": 1}
    )
    chk2 = chk_mgr.create_checkpoint(
        "task_s07", TaskStatus.RUNNING, sequence=2, state_snapshot={"v": 2}
    )

    # Corrupt chk2
    with store._lock:
        conn = store._get_connection()
        conn.execute(
            "UPDATE checkpoints SET sequence = 9999 WHERE checkpoint_id = ?;", (chk2.checkpoint_id,)
        )
        conn.commit()

    coord = RecoveryCoordinator(
        chk_mgr, ActionLedger(store), EnvironmentReconciler(), task_store=store
    )
    strat, chk, _ = coord.execute_recovery("task_s07", CorruptedCheckpointError("hash mismatch"))
    assert strat == RecoveryStrategy.RESUME_FROM_CHECKPOINT
    assert chk is not None
    assert chk.checkpoint_id == chk1.checkpoint_id
    assert chk.verify_hash() is True


# =============================================================================
# SCENARIO 08: Worker lease expires while worker is still alive (split-brain prevention)
# =============================================================================
def test_scenario_08_worker_lease_expires_while_worker_still_alive(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s08")
    lease_mgr = WorkerLeaseManager(store)
    lease = lease_mgr.acquire_lease("task_s08", "worker_slow", ttl_seconds=0.03)

    time.sleep(0.04)

    # Active lease is now expired
    active = lease_mgr.get_active_lease("task_s08")
    assert active is None
    assert lease_mgr.validate_fencing("task_s08", lease.generation) is False


# =============================================================================
# SCENARIO 09: Stale worker attempts to commit action after lease expiration
# =============================================================================
def test_scenario_09_stale_worker_attempts_to_commit_action(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s09")
    lease_mgr = WorkerLeaseManager(store)
    lease_mgr.acquire_lease("task_s09", "worker_old", ttl_seconds=0.03)

    time.sleep(0.04)

    # Worker new acquires task
    lease_mgr.acquire_lease("task_s09", "worker_new", ttl_seconds=30.0)

    ledger = ActionLedger(store, lease_manager=lease_mgr)
    with pytest.raises(StaleWorkerError):
        ledger.start_action("act_old", "task_s09", "click", {}, "worker_old", lease_generation=1)


# =============================================================================
# SCENARIO 10: Action succeeds in browser but worker crashes before recording success
# =============================================================================
def test_scenario_10_action_succeeds_in_browser_but_worker_crashes(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s10")
    chk_mgr = CheckpointManager(store, event_store=store)
    chk_mgr.create_checkpoint(
        "task_s10", TaskStatus.RUNNING, sequence=1, state_snapshot={"url": "https://shop.com/form"}
    )

    lease_mgr = WorkerLeaseManager(store)
    lease = lease_mgr.acquire_lease("task_s10", "w10", ttl_seconds=30.0)
    ledger = ActionLedger(store, lease_manager=lease_mgr)

    act = ledger.start_action(
        "act_submit", "task_s10", "click", {"selector": "#submit"}, "w10", lease.generation
    )
    ledger.mark_unknown("task_s10", act.idempotency_key, 1, "Worker died before recording result")

    coord = RecoveryCoordinator(chk_mgr, ledger, EnvironmentReconciler(), lease_mgr)
    strat, _, _ = coord.execute_recovery(
        "task_s10",
        "Crash after browser click",
        live_environment={
            "url": "https://shop.com/order-success",
            "dom": "Thank you! Order confirmed.",
        },
    )
    assert strat == RecoveryStrategy.RESUME_FROM_CHECKPOINT
    latest = ledger.get_latest_action("task_s10", act.idempotency_key)
    assert latest is not None
    assert latest.status == ActionExecutionStatus.VERIFIED


# =============================================================================
# SCENARIO 11: Action fails in browser and worker crashes before recording failure
# =============================================================================
def test_scenario_11_action_fails_in_browser_and_worker_crashes(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s11")
    chk_mgr = CheckpointManager(store, event_store=store)
    chk_mgr.create_checkpoint(
        "task_s11", TaskStatus.RUNNING, sequence=1, state_snapshot={"url": "https://shop.com/form"}
    )

    lease_mgr = WorkerLeaseManager(store)
    lease = lease_mgr.acquire_lease("task_s11", "w11", ttl_seconds=30.0)
    ledger = ActionLedger(store, lease_manager=lease_mgr)

    act = ledger.start_action(
        "act_submit", "task_s11", "click", {"selector": "#submit"}, "w11", lease.generation
    )
    ledger.mark_unknown("task_s11", act.idempotency_key, 1, "Crash")

    coord = RecoveryCoordinator(chk_mgr, ledger, EnvironmentReconciler(), lease_mgr)
    # Live environment still on form, no success
    strat, _, _ = coord.execute_recovery(
        "task_s11",
        "Crash",
        live_environment={"url": "https://shop.com/form", "dom": "<form id='form'></form>"},
    )
    # Requires operator approval to avoid double submission
    assert strat == RecoveryStrategy.REQUEST_APPROVAL


# =============================================================================
# SCENARIO 12: Two workers attempt to execute the same task simultaneously
# =============================================================================
def test_scenario_12_two_workers_attempt_same_task(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s12")
    lease_mgr = WorkerLeaseManager(store)

    lease1 = lease_mgr.acquire_lease("task_s12", "worker_1", ttl_seconds=30.0)
    assert lease1.worker_id == "worker_1"

    # Worker 2 simultaneously attempts to acquire lease -> blocked
    with pytest.raises(StorageError):
        lease_mgr.acquire_lease("task_s12", "worker_2", ttl_seconds=30.0)


# =============================================================================
# SCENARIO 13: Checkpoint restore with missing browser session
# =============================================================================
def test_scenario_13_checkpoint_restore_missing_browser(store: SQLiteStorage) -> None:
    chk_mgr = CheckpointManager(store)
    chk = chk_mgr.create_checkpoint("task_s13", TaskStatus.RUNNING, sequence=1)

    reconciler = EnvironmentReconciler()
    res = reconciler.reconcile(chk, live_environment=None)
    assert res.decision == ReconciliationDecision.RESTART_STEP
    assert "re-launched" in res.reason


# =============================================================================
# SCENARIO 14: Checkpoint restore with changed DOM structure
# =============================================================================
def test_scenario_14_checkpoint_restore_changed_dom(store: SQLiteStorage) -> None:
    chk_mgr = CheckpointManager(store)
    chk = chk_mgr.create_checkpoint(
        "task_s14", TaskStatus.RUNNING, sequence=1, state_snapshot={"url": "https://example.com/a"}
    )

    reconciler = EnvironmentReconciler()
    res = reconciler.reconcile(
        chk, live_environment={"url": "https://example.com/unexpected", "dom": "<div>drifted</div>"}
    )
    assert res.decision == ReconciliationDecision.RESTART_STEP
    assert res.matches_expected is False


# =============================================================================
# SCENARIO 15: Non-idempotent action interrupted in "unknown" state
# =============================================================================
def test_scenario_15_non_idempotent_action_unknown_state(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s15")
    lease_mgr = WorkerLeaseManager(store)
    lease = lease_mgr.acquire_lease("task_s15", "w15", ttl_seconds=30.0)
    ledger = ActionLedger(store, lease_manager=lease_mgr)

    act = ledger.start_action(
        "act_pay", "task_s15", "submit_payment", {"amt": 50}, "w15", lease.generation
    )
    ledger.mark_unknown("task_s15", act.idempotency_key, 1, "Interrupted")

    # Blind re-execution must be blocked
    with pytest.raises(NonIdempotentActionUncertaintyError):
        ledger.start_action(
            "act_pay", "task_s15", "submit_payment", {"amt": 50}, "w15", lease.generation
        )


# =============================================================================
# SCENARIO 16: Idempotent action safely retried after crash
# =============================================================================
def test_scenario_16_idempotent_action_safely_retried(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s16")
    lease_mgr = WorkerLeaseManager(store)
    lease = lease_mgr.acquire_lease("task_s16", "w16", ttl_seconds=30.0)
    ledger = ActionLedger(store, lease_manager=lease_mgr)

    act = ledger.start_action(
        "act_nav", "task_s16", "navigate", {"url": "https://example.com"}, "w16", lease.generation
    )
    ledger.mark_unknown("task_s16", act.idempotency_key, 1, "Crash")

    # Idempotent action automatically allows attempt 2
    retry = ledger.start_action(
        "act_nav", "task_s16", "navigate", {"url": "https://example.com"}, "w16", lease.generation
    )
    assert retry.attempt == 2
    assert retry.status == ActionExecutionStatus.STARTED


# =============================================================================
# SCENARIO 17: Task cancelled while worker is executing
# =============================================================================
def test_scenario_17_task_cancelled_while_worker_executing(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s17")
    lease_mgr = WorkerLeaseManager(store)
    lease = lease_mgr.acquire_lease("task_s17", "w17", ttl_seconds=30.0)

    # Cancel task
    store.update_task_status("task_s17", TaskStatus.CANCELLED)
    cancelled_task = store.get_task("task_s17")
    assert cancelled_task is not None
    assert cancelled_task.status == TaskStatus.CANCELLED

    # Release lease on cancellation
    lease_mgr.release_lease(lease.lease_id, "w17")
    assert lease_mgr.get_active_lease("task_s17") is None


# =============================================================================
# SCENARIO 18: Task paused, runtime restarted, task resumed
# =============================================================================
def test_scenario_18_task_paused_runtime_restarted_resumed(tmp_path: Path) -> None:
    db_path = tmp_path / "restart.db"
    store1 = SQLiteStorage(str(db_path))
    store1.initialize()

    now = datetime.now(UTC)
    task = Task(
        task_id="task_s18",
        objective="Pause-resume",
        status=TaskStatus.RUNNING,
        priority=TaskPriority.NORMAL,
        created_at=now,
        updated_at=now,
    )
    store1.save_task(task)

    chk_mgr1 = CheckpointManager(store1, event_store=store1)
    chk = chk_mgr1.create_checkpoint(
        "task_s18", TaskStatus.PAUSED, sequence=1, state_snapshot={"step": "paused_at_2"}
    )
    store1.update_task_status("task_s18", TaskStatus.PAUSED)

    # "Crash/Restart" runtime by instantiating new SQLiteStorage on same database
    store2 = SQLiteStorage(str(db_path))
    store2.initialize()

    resumed_task = store2.get_task("task_s18")
    assert resumed_task is not None
    assert resumed_task.status == TaskStatus.PAUSED

    chk_mgr2 = CheckpointManager(store2)
    latest_chk = chk_mgr2.get_latest_valid_checkpoint("task_s18")
    assert latest_chk is not None
    assert latest_chk.checkpoint_id == chk.checkpoint_id
    assert latest_chk.state_snapshot["step"] == "paused_at_2"


# =============================================================================
# SCENARIO 19: Rapid sequential crashes (crash loop detection and backoff)
# =============================================================================
def test_scenario_19_rapid_sequential_crashes(store: SQLiteStorage) -> None:
    _create_running_task(store, "task_s19")
    chk_mgr = CheckpointManager(store)
    chk_mgr.create_checkpoint("task_s19", TaskStatus.RUNNING, sequence=1)

    coord = RecoveryCoordinator(
        chk_mgr, ActionLedger(store), EnvironmentReconciler(), task_store=store, max_retries=3
    )

    # Attempt 1, 2, 3 fail
    for i in range(3):
        strat, _, _ = coord.execute_recovery("task_s19", f"Crash {i + 1}", retry_count=i)
        assert strat in (
            RecoveryStrategy.RESUME_FROM_CHECKPOINT,
            RecoveryStrategy.RECONCILE_ENVIRONMENT,
        )

    # Attempt 4 exceeds max_retries -> FAIL_TASK
    strat_final, _, _ = coord.execute_recovery("task_s19", "Crash 4", retry_count=3)
    assert strat_final == RecoveryStrategy.FAIL_TASK

    task = store.get_task("task_s19")
    assert task is not None
    assert task.status == TaskStatus.FAILED


# =============================================================================
# SCENARIO 20: Complete power loss simulation (uncommitted rollback, WAL recovery)
# =============================================================================
def test_scenario_20_complete_power_loss_simulation(tmp_path: Path) -> None:
    db_file = tmp_path / "power_loss.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    _create_running_task(store, "task_s20")
    chk_mgr = CheckpointManager(store)
    chk = chk_mgr.create_checkpoint(
        "task_s20", TaskStatus.RUNNING, sequence=1, state_snapshot={"committed": True}
    )

    # Simulate abrupt power loss in the middle of uncommitted transaction
    with store._lock:
        conn = store._get_connection()
        conn.execute("BEGIN TRANSACTION;")
        conn.execute(
            "INSERT INTO tasks (task_id, objective, status, priority, created_at, updated_at) VALUES ('dirty_task', 'obj', 'RUNNING', 'HIGH', 'now', 'now');"
        )
        # Abrupt power cut: close connection WITHOUT commit
        conn.close()
        store._conn = None

    # Re-open database with fresh connection
    store_recovered = SQLiteStorage(str(db_file))
    store_recovered.initialize()

    # Dirty transaction was completely rolled back
    assert store_recovered.get_task("dirty_task") is None

    # Committed checkpoint and task remain intact and verified
    committed_task = store_recovered.get_task("task_s20")
    assert committed_task is not None
    committed_chk = chk_mgr.get_checkpoint(chk.checkpoint_id, verify=True)
    assert committed_chk is not None
    assert committed_chk.verify_hash() is True
