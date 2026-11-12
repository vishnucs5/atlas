"""WorkerRegistryManager for worker lifecycle, capability matching, and heartbeat tracking."""

from datetime import UTC, datetime, timedelta
from typing import Any

from atlas_core.contracts.worker import WorkerRecord, WorkerStatus
from atlas_storage.interfaces import WorkerStoreProtocol


class WorkerRegistryManager:
    """Manages worker registration, heartbeats, health sweeps, and capability-aware worker discovery."""

    def __init__(self, worker_store: WorkerStoreProtocol) -> None:
        self.store = worker_store

    def register(
        self,
        worker_id: str,
        hostname: str,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkerRecord:
        """Register a new worker or update an existing worker registration."""
        record = WorkerRecord(
            worker_id=worker_id,
            hostname=hostname,
            status=WorkerStatus.IDLE,
            capabilities=capabilities or [],
            metadata=metadata or {},
            registered_at=datetime.now(UTC),
            last_heartbeat_at=datetime.now(UTC),
        )
        self.store.register_worker(record)
        return record

    def heartbeat(
        self,
        worker_id: str,
        status: WorkerStatus | None = None,
    ) -> None:
        """Update last heartbeat timestamp and optional status for a worker."""
        self.store.heartbeat_worker(worker_id, status=status)

    def mark_busy(self, worker_id: str, current_task_id: str | None = None) -> None:
        """Mark worker as busy processing a task."""
        worker = self.store.get_worker(worker_id)
        if worker is not None:
            worker.status = WorkerStatus.BUSY
            worker.current_task_id = current_task_id
            worker.last_heartbeat_at = datetime.now(UTC)
            self.store.register_worker(worker)

    def mark_idle(self, worker_id: str) -> None:
        """Mark worker as idle and ready for new task assignments."""
        worker = self.store.get_worker(worker_id)
        if worker is not None:
            worker.status = WorkerStatus.IDLE
            worker.current_task_id = None
            worker.last_heartbeat_at = datetime.now(UTC)
            self.store.register_worker(worker)

    def mark_draining(self, worker_id: str) -> None:
        """Mark worker as draining: completes existing workload but accepts no new leases."""
        self.store.heartbeat_worker(worker_id, status=WorkerStatus.DRAINING)

    def mark_disconnected(self, worker_id: str) -> None:
        """Mark worker as disconnected."""
        self.store.heartbeat_worker(worker_id, status=WorkerStatus.DISCONNECTED)

    def sweep_stale_workers(self, timeout_seconds: float = 15.0) -> list[str]:
        """Detect workers that missed heartbeats and transition them to DISCONNECTED."""
        now = datetime.now(UTC)
        threshold = now - timedelta(seconds=timeout_seconds)
        all_workers = self.store.list_workers()
        disconnected_ids: list[str] = []

        for w in all_workers:
            if w.status in (WorkerStatus.IDLE, WorkerStatus.BUSY, WorkerStatus.DRAINING):
                if w.last_heartbeat_at < threshold:
                    self.mark_disconnected(w.worker_id)
                    disconnected_ids.append(w.worker_id)

        return disconnected_ids

    def find_eligible_workers(
        self,
        required_capabilities: list[str] | None = None,
    ) -> list[WorkerRecord]:
        """Find active, IDLE workers that satisfy all required capabilities."""
        idle_workers = self.store.list_workers(status=WorkerStatus.IDLE)
        if not required_capabilities:
            return idle_workers

        required_set = set(required_capabilities)
        return [w for w in idle_workers if required_set.issubset(set(w.capabilities))]

    def get_worker(self, worker_id: str) -> WorkerRecord | None:
        """Retrieve worker by ID."""
        return self.store.get_worker(worker_id)

    def list_workers(self, status: WorkerStatus | None = None) -> list[WorkerRecord]:
        """List workers with optional status filter."""
        return self.store.list_workers(status=status)
