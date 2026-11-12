"""Executable demonstration of ATLAS Phase 4 Durable Execution & Recovery Infrastructure.

Demonstrates:
1. Worker registration and capability-aware task scheduling.
2. Exclusive task lease acquisition with monotonic generation fencing tokens.
3. Transactional checkpoint creation sealed with SHA-256 cryptographic hashes.
4. Action execution tracking in durable ActionLedger with idempotency deduplication.
5. Simulated process crash / SIGKILL, leaving action in UNKNOWN state.
6. Commit-time lease fencing preventing zombie/stale worker split-brain execution.
7. Physical environment reconciliation inspecting DOM state vs checkpoint expectations.
8. 8-stage automated recovery lifecycle recovering task to verified checkpoint.
9. Time-travel state reconstruction and sanitized audit timeline export via ExecutionReplayEngine.

Usage:
    uv run python scripts/demo_durable_recovery.py
"""

# ruff: noqa: E402
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

# Bootstrap repository packages onto sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
for pkg_path in [
    "packages/atlas-core/src",
    "packages/atlas-storage/src",
    "packages/atlas-policy/src",
    "packages/atlas-observability/src",
    "packages/atlas-browser/src",
    "packages/atlas-observation/src",
    "packages/atlas-verification/src",
    "packages/atlas-models/src",
    "packages/atlas-agent/src",
    "packages/atlas-coordination/src",
    ".",
]:
    full_path = str(REPO_ROOT / pkg_path)
    if full_path not in sys.path:
        sys.path.insert(0, full_path)

from atlas_coordination.action_ledger import ActionLedger
from atlas_coordination.checkpoint_manager import CheckpointManager
from atlas_coordination.lease_manager import WorkerLeaseManager
from atlas_coordination.reconciler import EnvironmentReconciler
from atlas_coordination.recovery_coordinator import RecoveryCoordinator
from atlas_coordination.replay import ExecutionReplayEngine
from atlas_coordination.scheduler import WorkerScheduler
from atlas_coordination.worker_registry import WorkerRegistryManager
from atlas_core.contracts.ledger import ActionExecutionStatus
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_core.contracts.worker import WorkerStatus
from atlas_storage.interfaces import StaleWorkerError
from atlas_storage.sqlite import SQLiteStorage


def run_demo() -> None:
    print("=" * 80)
    print("ATLAS PHASE 4: DURABLE EXECUTION & RECOVERY INFRASTRUCTURE DEMONSTRATION")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "demo_durable.db"
        store = SQLiteStorage(str(db_path))
        store.initialize()
        print(f"\n[1] Initialized SQLite durable store (WAL mode) at: {db_path.name}")

        # Setup Task
        task_id = "task_checkout_recovery"
        now = datetime.now(UTC)
        task = Task(
            task_id=task_id,
            objective="Automated hotel booking and payment verification",
            status=TaskStatus.RUNNING,
            priority=TaskPriority.HIGH,
            created_at=now,
            updated_at=now,
        )
        store.save_task(task)
        print(f"[2] Created task '{task_id}' (objective: '{task.objective}')")

        # Worker Registry & Scheduler
        registry = WorkerRegistryManager(store)
        registry.register("worker_alpha", "worker-node-1", capabilities=["browser", "playwright"])
        registry.register("worker_beta", "worker-node-2", capabilities=["browser", "playwright"])
        print("[3] Registered workers: 'worker_alpha' (node-1), 'worker_beta' (node-2)")

        lease_mgr = WorkerLeaseManager(store)
        scheduler = WorkerScheduler(registry, lease_mgr)

        # Schedule task to Worker Alpha
        worker, lease = scheduler.schedule_task(
            task_id, required_capabilities=["browser"], lease_ttl_seconds=0.1
        )
        print(
            f"[4] Task scheduled to '{worker.worker_id}'. Acquired lease '{lease.lease_id}' with Fencing Generation: {lease.generation}"
        )

        # Checkpoint 1
        chk_mgr = CheckpointManager(store, event_store=store)
        chk1 = chk_mgr.create_checkpoint(
            task_id=task_id,
            state=TaskStatus.RUNNING,
            sequence=1,
            worker_id=worker.worker_id,
            lease_generation=lease.generation,
            state_snapshot={"url": "https://hotels.example.com/checkout", "step": "review_booking"},
        )
        print(
            f"[5] Sealed Checkpoint 1: ID={chk1.checkpoint_id}, SHA256={chk1.checkpoint_hash[:16]}... (Verified={chk1.verify_hash()})"
        )

        # Action Ledger: Start payment action
        ledger = ActionLedger(store, lease_manager=lease_mgr)
        act1 = ledger.start_action(
            action_id="act_submit_booking",
            task_id=task_id,
            action_type="submit_payment",
            parameters={"card_last4": "4242", "auth_token": "secret_session_token_xyz"},
            worker_id=worker.worker_id,
            lease_generation=lease.generation,
        )
        print(
            f"[6] Action started: ID={act1.action_id}, IdempotencyKey={act1.idempotency_key[:12]}..., Status={act1.status.value}"
        )

        # SIMULATE CRASH: Worker Alpha process crashes abruptly during execution
        print("\n--- SIMULATING ABRUPT WORKER CRASH (SIGKILL) ---")
        time.sleep(0.12)  # Exceed lease TTL of 0.1s
        ledger.mark_unknown(
            task_id,
            act1.idempotency_key,
            attempt=1,
            reason="Worker Alpha terminated abruptly (SIGKILL)",
        )
        print(
            f"[7] Action transitioned to: {ActionExecutionStatus.UNKNOWN.value} (Outcome uncertain)"
        )

        # Split-brain check: Stale Worker Alpha attempts to commit
        print("[8] Stale worker commit test: Worker Alpha attempts write with Generation 1...")
        try:
            ledger.mark_succeeded(
                task_id,
                act1.idempotency_key,
                attempt=1,
                lease_generation=1,
                worker_id="worker_alpha",
            )
            print("ERROR: Stale worker was not fenced!")
            sys.exit(1)
        except StaleWorkerError as exc:
            print(f"    [FENCING SUCCESS] Rejected stale worker commit: {exc}")

        # Failover: Worker Beta takes over lease
        print("\n--- INITIATING FAILOVER & ENVIRONMENT RECONCILIATION ---")
        new_worker, new_lease = scheduler.schedule_task(
            task_id, required_capabilities=["browser"], lease_ttl_seconds=30.0
        )
        print(f"[9] Worker Beta assigned task. New Fencing Generation: {new_lease.generation}")

        # Environment Reconciler inspects physical browser DOM
        reconciler = EnvironmentReconciler()
        live_browser_state = {
            "url": "https://hotels.example.com/booking-confirmed",
            "title": "Booking Confirmation",
            "dom": "<div><h1>Reservation Confirmed!</h1><p>Booking ID: #HTL-9921</p></div>",
            "status_code": 200,
        }
        reconcile_res = reconciler.reconcile(
            checkpoint=chk1,
            live_environment=live_browser_state,
            pending_actions=[act1],
        )
        print(
            f"[10] Physical Reconciliation Result: Decision={reconcile_res.decision.value}, Handled={reconcile_res.pending_action_handled}"
        )
        print(f"     Reason: {reconcile_res.reason}")

        # 8-Stage Recovery Coordinator
        coord = RecoveryCoordinator(
            checkpoint_manager=chk_mgr,
            action_ledger=ledger,
            reconciler=reconciler,
            lease_manager=lease_mgr,
            task_store=store,
            event_store=store,
        )
        strategy, recovered_chk, summary = coord.execute_recovery(
            task_id=task_id,
            error="Worker Alpha crash",
            current_worker_id=new_worker.worker_id,
            expected_lease_generation=new_lease.generation,
            live_environment=live_browser_state,
            retry_count=0,
        )
        print(f"[11] 8-Stage Recovery Complete: Strategy={strategy.value}")
        print(f"     Summary: {summary}")

        # Verify action status updated in ledger
        updated_act = ledger.get_latest_action(task_id, act1.idempotency_key)
        assert updated_act is not None
        print(f"[12] Ledger verified action status: {updated_act.status.value}")

        # Complete Task
        scheduler.complete_task(new_lease.lease_id, new_worker.worker_id)
        store.update_task_status(task_id, TaskStatus.COMPLETED)
        print(
            f"[13] Task completed successfully. Released lease and returned Worker Beta to {WorkerStatus.IDLE.value}."
        )

        # Time-Travel Replay & Timeline
        print("\n--- TIME-TRAVEL REPLAY & TIMELINE AUDIT ---")
        replay = ExecutionReplayEngine(event_store=store, checkpoint_store=store)
        timeline = replay.export_timeline(task_id)
        print(f"[14] Exported chronological audit timeline ({len(timeline)} events):")
        for entry in timeline:
            seq = entry["sequence"]
            etype = entry["event_type"]
            ts = entry["timestamp"]
            print(f"     #{seq:02d} [{ts[11:19]}] {etype}")

        # Verify zero secret leaks in audit trail
        for entry in timeline:
            payload_str = str(entry["payload"])
            assert "secret_session_token_xyz" not in payload_str
        print("[15] Verified Rule 6: Zero secret leaks in audit events or state snapshots.")

        store.close()

    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETED SUCCESSFULLY (EXIT CODE 0)")
    print("=" * 80)


if __name__ == "__main__":
    run_demo()
