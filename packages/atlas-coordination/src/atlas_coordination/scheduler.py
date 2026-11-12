"""WorkerScheduler for capability-aware task assignment and lease allocation."""

from atlas_core.contracts.worker import WorkerLease, WorkerRecord

from atlas_coordination.lease_manager import WorkerLeaseManager
from atlas_coordination.worker_registry import WorkerRegistryManager


class NoAvailableWorkerError(Exception):
    """Raised when no registered worker matches required task capabilities."""


class WorkerScheduler:
    """Capability-aware worker scheduler for distributed ATLAS execution."""

    def __init__(
        self,
        registry: WorkerRegistryManager,
        lease_manager: WorkerLeaseManager,
    ) -> None:
        self.registry = registry
        self.lease_manager = lease_manager

    def schedule_task(
        self,
        task_id: str,
        required_capabilities: list[str] | None = None,
        lease_ttl_seconds: float = 30.0,
    ) -> tuple[WorkerRecord, WorkerLease]:
        """Find an eligible IDLE worker matching capabilities, acquire lease, and mark worker BUSY."""
        eligible = self.registry.find_eligible_workers(required_capabilities)
        if not eligible:
            caps_str = ", ".join(required_capabilities) if required_capabilities else "any"
            raise NoAvailableWorkerError(
                f"No available idle worker found with required capabilities: [{caps_str}]"
            )

        selected_worker = eligible[0]

        # Acquire exclusive task lease
        lease = self.lease_manager.acquire_lease(
            task_id=task_id,
            worker_id=selected_worker.worker_id,
            ttl_seconds=lease_ttl_seconds,
        )

        # Mark worker busy with this task
        self.registry.mark_busy(selected_worker.worker_id, current_task_id=task_id)

        return selected_worker, lease

    def complete_task(
        self,
        lease_id: str,
        worker_id: str,
    ) -> None:
        """Release lease and return worker to IDLE status."""
        self.lease_manager.release_lease(lease_id=lease_id, worker_id=worker_id)
        self.registry.mark_idle(worker_id=worker_id)
