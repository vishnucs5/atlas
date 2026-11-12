"""WorkerLeaseManager for lease acquisition, heartbeats, and commit-time fencing token enforcement."""

from atlas_core.contracts.worker import WorkerLease
from atlas_storage.interfaces import StaleWorkerError, WorkerStoreProtocol


class WorkerLeaseManager:
    """Manages exclusive task execution leases and verifies monotonic fencing tokens."""

    def __init__(self, worker_store: WorkerStoreProtocol) -> None:
        self.store = worker_store

    def acquire_lease(
        self,
        task_id: str,
        worker_id: str,
        ttl_seconds: float = 30.0,
    ) -> WorkerLease:
        """Acquire an exclusive lease for a task, incrementing generation fencing token."""
        return self.store.acquire_lease(task_id, worker_id, ttl_seconds=ttl_seconds)

    def renew_lease(
        self,
        lease_id: str,
        worker_id: str,
        ttl_seconds: float = 30.0,
    ) -> WorkerLease:
        """Renew an existing active lease."""
        return self.store.renew_lease(lease_id, worker_id, ttl_seconds=ttl_seconds)

    def release_lease(
        self,
        lease_id: str,
        worker_id: str,
    ) -> None:
        """Release an active lease explicitly on task completion or failure."""
        self.store.release_lease(lease_id, worker_id)

    def get_active_lease(self, task_id: str) -> WorkerLease | None:
        """Retrieve active lease if not expired."""
        return self.store.get_active_lease(task_id)

    def validate_fencing(self, task_id: str, expected_generation: int) -> bool:
        """Check if expected generation matches the active lease fencing token."""
        return self.store.validate_lease_fencing(task_id, expected_generation)

    def assert_fencing(
        self,
        task_id: str,
        expected_generation: int,
        worker_id: str | None = None,
    ) -> None:
        """Assert that the lease fencing token is valid at commit time, raising StaleWorkerError otherwise."""
        if not self.store.validate_lease_fencing(task_id, expected_generation):
            active_lease = self.store.get_active_lease(task_id)
            current_gen = active_lease.generation if active_lease else "none/expired"
            curr_worker = active_lease.worker_id if active_lease else "none"
            raise StaleWorkerError(
                f"Fencing token validation failed for task '{task_id}'. "
                f"Expected generation: {expected_generation} (worker: '{worker_id}'), "
                f"active generation: {current_gen} (active worker: '{curr_worker}'). "
                f"Commit rejected to prevent split-brain execution."
            )
