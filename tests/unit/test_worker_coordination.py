"""Unit tests for WorkerRegistryManager, WorkerLeaseManager, and WorkerScheduler."""

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from atlas_coordination.lease_manager import WorkerLeaseManager
from atlas_coordination.scheduler import NoAvailableWorkerError, WorkerScheduler
from atlas_coordination.worker_registry import WorkerRegistryManager
from atlas_core.contracts.worker import LeaseStatus, WorkerStatus
from atlas_storage.interfaces import StaleWorkerError
from atlas_storage.sqlite import SQLiteStorage


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStorage:
    db = tmp_path / "test_workers.db"
    s = SQLiteStorage(str(db))
    s.initialize()
    return s


def test_worker_registration_and_capabilities(store: SQLiteStorage) -> None:
    registry = WorkerRegistryManager(store)

    registry.register(
        worker_id="w_browser_1",
        hostname="worker-vm-1",
        capabilities=["browser", "playwright"],
    )
    registry.register(
        worker_id="w_gpu_1",
        hostname="worker-vm-2",
        capabilities=["browser", "playwright", "gpu"],
    )

    # Capability matching
    browser_workers = registry.find_eligible_workers(["browser"])
    assert len(browser_workers) == 2

    gpu_workers = registry.find_eligible_workers(["gpu"])
    assert len(gpu_workers) == 1
    assert gpu_workers[0].worker_id == "w_gpu_1"

    non_matching = registry.find_eligible_workers(["unknown_cap"])
    assert len(non_matching) == 0


def test_worker_draining_and_stale_sweep(store: SQLiteStorage) -> None:
    registry = WorkerRegistryManager(store)

    registry.register(
        worker_id="w_drain",
        hostname="worker-vm-3",
        capabilities=["browser"],
    )

    # Mark draining
    registry.mark_draining("w_drain")
    worker = registry.get_worker("w_drain")
    assert worker is not None
    assert worker.status == WorkerStatus.DRAINING

    # Draining worker must NOT be eligible for new tasks
    eligible = registry.find_eligible_workers(["browser"])
    assert len(eligible) == 0

    # Backdate heartbeat for sweep test
    with store._lock:
        conn = store._get_connection()
        old_time = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
        conn.execute(
            "UPDATE worker_registry SET last_heartbeat_at = ? WHERE worker_id = 'w_drain';",
            (old_time,),
        )
        conn.commit()

    # Sweep stale workers
    disconnected = registry.sweep_stale_workers(timeout_seconds=15.0)
    assert "w_drain" in disconnected

    worker_after_sweep = registry.get_worker("w_drain")
    assert worker_after_sweep is not None
    assert worker_after_sweep.status == WorkerStatus.DISCONNECTED


def test_lease_manager_fencing_and_split_brain_protection(store: SQLiteStorage) -> None:
    registry = WorkerRegistryManager(store)
    registry.register("worker_alpha", "host-1", ["browser"])
    registry.register("worker_beta", "host-2", ["browser"])

    lease_mgr = WorkerLeaseManager(store)

    # Short lease
    lease1 = lease_mgr.acquire_lease("task_fence_1", "worker_alpha", ttl_seconds=0.05)
    assert lease1.generation == 1

    # Assert fencing passes for generation 1
    lease_mgr.assert_fencing("task_fence_1", 1, worker_id="worker_alpha")

    time.sleep(0.06)

    # After expiry, worker_beta acquires lease -> generation bumps to 2
    lease2 = lease_mgr.acquire_lease("task_fence_1", "worker_beta", ttl_seconds=10.0)
    assert lease2.generation == 2

    # worker_alpha attempts to commit with stale generation 1 -> rejected with StaleWorkerError
    with pytest.raises(StaleWorkerError) as exc_info:
        lease_mgr.assert_fencing("task_fence_1", 1, worker_id="worker_alpha")
    assert "Fencing token validation failed" in str(exc_info.value)

    # worker_beta with generation 2 succeeds
    lease_mgr.assert_fencing("task_fence_1", 2, worker_id="worker_beta")


def test_worker_scheduler_flow(store: SQLiteStorage) -> None:
    registry = WorkerRegistryManager(store)
    registry.register("w_exec_1", "host-exec", ["browser", "playwright"])

    lease_mgr = WorkerLeaseManager(store)
    scheduler = WorkerScheduler(registry=registry, lease_manager=lease_mgr)

    # Schedule task
    worker, lease = scheduler.schedule_task("task_sched_100", ["browser"])
    assert worker.worker_id == "w_exec_1"
    assert lease.task_id == "task_sched_100"
    assert lease.generation == 1
    assert lease.status == LeaseStatus.ACTIVE

    # Worker is now BUSY, so second attempt fails with NoAvailableWorkerError
    with pytest.raises(NoAvailableWorkerError):
        scheduler.schedule_task("task_sched_101", ["browser"])

    # Complete task
    scheduler.complete_task(lease.lease_id, worker.worker_id)

    # Worker is now IDLE again, so scheduling succeeds
    worker_next, lease_next = scheduler.schedule_task("task_sched_101", ["browser"])
    assert worker_next.worker_id == "w_exec_1"
    assert lease_next.task_id == "task_sched_101"
