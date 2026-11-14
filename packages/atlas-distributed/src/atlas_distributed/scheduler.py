"""Resource-aware, multi-dimensional distributed scheduler for ATLAS execution network."""

import heapq
import itertools
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from atlas_core.contracts.worker import LeaseStatus, WorkerLease, WorkerStatus
from pydantic import BaseModel, ConfigDict, Field

from atlas_distributed.enrollment import WorkerEnrollmentAuthority
from atlas_distributed.models import (
    AssignmentPayload,
    SessionType,
    WorkerIdentity,
    WorkerPlatform,
)

logger = logging.getLogger("atlas.distributed.scheduler")


class SchedulerError(Exception):
    """Base exception for distributed scheduler errors."""


class NoEligibleWorkerError(SchedulerError):
    """Raised when no enrolled worker satisfies task scheduling requirements."""


class SchedulerQueueFullError(SchedulerError):
    """Raised when priority queue capacity is exceeded (backpressure)."""


class TaskRequirements(BaseModel):
    """Multi-dimensional requirements and constraints for scheduling a task."""

    model_config = ConfigDict(validate_assignment=True)

    task_id: str
    tenant_id: str = "default"
    priority: int = 0  # Higher number = higher priority
    objective: str = ""
    action_type: str = "task_execution"
    required_platform: WorkerPlatform | None = None
    required_session_type: SessionType | None = None
    requires_interactive_desktop: bool = False
    required_drivers: list[str] = Field(default_factory=list)
    required_browsers: list[str] = Field(default_factory=list)
    min_cpu_cores: int = 1
    min_memory_bytes: int = 0
    require_gpu: bool = False
    required_tags: list[str] = Field(default_factory=list)
    security_level: str = "standard"
    lease_ttl_seconds: float = 30.0
    timeout_seconds: float = 300.0
    parameters: dict[str, str | int | float | bool | list | dict] = Field(default_factory=dict)


class InMemoryLeaseTracker:
    """Thread-safe fallback lease manager with monotonic generation tokens."""

    def __init__(self) -> None:
        self._leases: dict[str, WorkerLease] = {}
        self._task_generations: dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire_lease(self, task_id: str, worker_id: str, ttl_seconds: float = 30.0) -> WorkerLease:
        with self._lock:
            gen = self._task_generations.get(task_id, 0) + 1
            self._task_generations[task_id] = gen
            lease_id = f"lease_{uuid.uuid4().hex[:12]}"
            now = datetime.now(UTC)
            lease = WorkerLease(
                lease_id=lease_id,
                task_id=task_id,
                worker_id=worker_id,
                generation=gen,
                status=LeaseStatus.ACTIVE,
                acquired_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
            self._leases[lease_id] = lease
            return lease

    def release_lease(self, lease_id: str, worker_id: str) -> None:
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease and lease.worker_id == worker_id:
                lease.status = LeaseStatus.RELEASED

    def get_lease(self, lease_id: str) -> WorkerLease | None:
        with self._lock:
            return self._leases.get(lease_id)

    def validate_fencing(self, task_id: str, generation: int) -> bool:
        with self._lock:
            current_gen = self._task_generations.get(task_id, 0)
            return generation == current_gen


class PrioritizedTask:
    """Wrapper for heap ordering: priority descending, arrival ascending."""

    _counter = itertools.count()

    def __init__(self, requirements: TaskRequirements) -> None:
        self.requirements = requirements
        self.priority = requirements.priority
        self.order = next(self._counter)

    def __lt__(self, other: "PrioritizedTask") -> bool:
        # Higher priority first; if equal, earlier order first
        if self.priority != other.priority:
            return self.priority > other.priority
        return self.order < other.order


class DistributedScheduler:
    """Resource-aware, multi-tenant distributed scheduler matching tasks to workers."""

    def __init__(
        self,
        enrollment_authority: WorkerEnrollmentAuthority,
        lease_manager: Any | None = None,
        max_queue_depth: int = 1000,
        worker_lookup_fn: Callable[[], list[WorkerIdentity]] | None = None,
    ) -> None:
        self.enrollment_authority = enrollment_authority
        self.lease_manager = lease_manager or InMemoryLeaseTracker()
        self.max_queue_depth = max_queue_depth
        self.worker_lookup_fn = worker_lookup_fn

        self._task_queue: list[PrioritizedTask] = []
        self._active_worker_tasks: dict[str, set[str]] = {}  # worker_id -> set of assignment_ids
        self._active_assignments: dict[str, tuple[str, str, str]] = {}  # asgn_id -> (task_id, worker_id, lease_id)
        self._lock = threading.Lock()

    def get_active_workers(self) -> list[WorkerIdentity]:
        """Fetch all currently enrolled and non-revoked workers."""
        if self.worker_lookup_fn:
            return self.worker_lookup_fn()
        return self.enrollment_authority.list_workers()

    def submit_task(self, requirements: TaskRequirements) -> AssignmentPayload:
        """Enqueue task according to priority and attempt immediate scheduling."""
        with self._lock:
            if len(self._task_queue) >= self.max_queue_depth:
                raise SchedulerQueueFullError(
                    f"Scheduler queue depth limit reached ({self.max_queue_depth}). Backpressure active."
                )

            # Try immediate scheduling first
            try:
                return self._schedule_now(requirements)
            except NoEligibleWorkerError:
                # Enqueue into priority queue
                heapq.heappush(self._task_queue, PrioritizedTask(requirements))
                logger.info(
                    "Task %s enqueued with priority %d. Current queue length: %d",
                    requirements.task_id,
                    requirements.priority,
                    len(self._task_queue),
                )
                raise

    def schedule_task(self, requirements: TaskRequirements) -> tuple[WorkerIdentity, AssignmentPayload]:
        """Directly schedule task against available workers or raise NoEligibleWorkerError."""
        with self._lock:
            return self._schedule_now_with_worker(requirements)

    def _schedule_now(self, requirements: TaskRequirements) -> AssignmentPayload:
        _, payload = self._schedule_now_with_worker(requirements)
        return payload

    def _schedule_now_with_worker(
        self,
        requirements: TaskRequirements,
    ) -> tuple[WorkerIdentity, AssignmentPayload]:
        workers = self.get_active_workers()
        eligible_workers: list[tuple[WorkerIdentity, int]] = []
        diagnostic_rejections: list[str] = []

        for worker in workers:
            # Skip revoked, terminated, or disconnected workers
            if worker.is_revoked:
                diagnostic_rejections.append(f"Worker '{worker.worker_id}': revoked")
                continue
            if worker.status in (WorkerStatus.TERMINATED, WorkerStatus.DISCONNECTED):
                diagnostic_rejections.append(f"Worker '{worker.worker_id}': status {worker.status.value}")
                continue

            # 1. Tenant Isolation
            if worker.tenant_id != requirements.tenant_id:
                diagnostic_rejections.append(
                    f"Worker '{worker.worker_id}': tenant mismatch ('{worker.tenant_id}' != '{requirements.tenant_id}')"
                )
                continue

            # 2. Concurrency limit
            current_tasks = self._active_worker_tasks.get(worker.worker_id, set())
            if len(current_tasks) >= worker.capabilities.max_concurrent_tasks:
                diagnostic_rejections.append(
                    f"Worker '{worker.worker_id}': capacity exhausted ({len(current_tasks)}/{worker.capabilities.max_concurrent_tasks})"
                )
                continue

            # 3. Platform match
            if requirements.required_platform and worker.capabilities.platform != requirements.required_platform:
                diagnostic_rejections.append(
                    f"Worker '{worker.worker_id}': platform mismatch ('{worker.capabilities.platform}' != '{requirements.required_platform}')"
                )
                continue

            # 4. Windows Session 0 & Interactive Desktop Guard
            if (
                requirements.requires_interactive_desktop
                or requirements.required_session_type == SessionType.INTERACTIVE_USER
            ):
                if worker.capabilities.session_type == SessionType.SESSION_0:
                    diagnostic_rejections.append(
                        f"Worker '{worker.worker_id}': Session 0 rejected for interactive desktop"
                    )
                    continue
                if not worker.capabilities.supports_interactive_desktop():
                    diagnostic_rejections.append(
                        f"Worker '{worker.worker_id}': lacks interactive desktop support"
                    )
                    continue

            # 5. Session type requirement
            if (
                requirements.required_session_type
                and worker.capabilities.session_type != requirements.required_session_type
            ):
                diagnostic_rejections.append(
                    f"Worker '{worker.worker_id}': session mismatch ('{worker.capabilities.session_type}' != '{requirements.required_session_type}')"
                )
                continue

            # 6. Required drivers
            missing_drivers = [d for d in requirements.required_drivers if d not in worker.capabilities.drivers]
            if missing_drivers:
                diagnostic_rejections.append(
                    f"Worker '{worker.worker_id}': missing drivers {missing_drivers}"
                )
                continue

            # 7. Required browsers
            missing_browsers = [b for b in requirements.required_browsers if b not in worker.capabilities.browsers]
            if missing_browsers:
                diagnostic_rejections.append(
                    f"Worker '{worker.worker_id}': missing browsers {missing_browsers}"
                )
                continue

            # 8. Hardware constraints (CPU, RAM, GPU)
            hw = worker.capabilities.hardware
            if hw.cpu_cores < requirements.min_cpu_cores:
                diagnostic_rejections.append(
                    f"Worker '{worker.worker_id}': insufficient CPU ({hw.cpu_cores} < {requirements.min_cpu_cores})"
                )
                continue

            if hw.memory_bytes < requirements.min_memory_bytes:
                diagnostic_rejections.append(
                    f"Worker '{worker.worker_id}': insufficient RAM ({hw.memory_bytes} < {requirements.min_memory_bytes})"
                )
                continue

            if requirements.require_gpu and not hw.has_gpu:
                diagnostic_rejections.append(f"Worker '{worker.worker_id}': GPU required but not present")
                continue

            # 9. Required tags
            missing_tags = [t for t in requirements.required_tags if t not in worker.capabilities.tags]
            if missing_tags:
                diagnostic_rejections.append(f"Worker '{worker.worker_id}': missing tags {missing_tags}")
                continue

            # Candidate matched! Score by least-loaded
            eligible_workers.append((worker, len(current_tasks)))

        if not eligible_workers:
            diagnostic_summary = "; ".join(diagnostic_rejections[:5])
            if len(diagnostic_rejections) > 5:
                diagnostic_summary += f" ... ({len(diagnostic_rejections) - 5} more)"
            raise NoEligibleWorkerError(
                f"No eligible worker available for task '{requirements.task_id}'. Diagnosed: {diagnostic_summary}"
            )

        # Fairness & Load balancing: Select candidate with lowest active task count
        eligible_workers.sort(key=lambda item: item[1])
        selected_worker, _ = eligible_workers[0]

        # Acquire exclusive task lease with fencing generation
        lease = self.lease_manager.acquire_lease(
            task_id=requirements.task_id,
            worker_id=selected_worker.worker_id,
            ttl_seconds=requirements.lease_ttl_seconds,
        )

        assignment_id = f"asgn_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)
        payload = AssignmentPayload(
            assignment_id=assignment_id,
            task_id=requirements.task_id,
            worker_id=selected_worker.worker_id,
            tenant_id=requirements.tenant_id,
            lease_id=lease.lease_id,
            generation=lease.generation,
            objective=requirements.objective,
            action_type=requirements.action_type,
            parameters=requirements.parameters,
            required_capabilities=requirements.required_drivers,
            assigned_at=now,
            expires_at=now + timedelta(seconds=requirements.timeout_seconds),
            timeout_seconds=requirements.timeout_seconds,
        )

        # Update scheduler state
        if selected_worker.worker_id not in self._active_worker_tasks:
            self._active_worker_tasks[selected_worker.worker_id] = set()
        self._active_worker_tasks[selected_worker.worker_id].add(assignment_id)
        self._active_assignments[assignment_id] = (
            requirements.task_id,
            selected_worker.worker_id,
            lease.lease_id,
        )

        selected_worker.status = WorkerStatus.BUSY

        logger.info(
            "Task %s assigned to worker %s (assignment=%s, generation=%d)",
            requirements.task_id,
            selected_worker.worker_id,
            assignment_id,
            lease.generation,
        )
        return selected_worker, payload

    def complete_task(self, assignment_id: str) -> None:
        """Release lease, decrement worker task count, and trigger queue drain."""
        with self._lock:
            record = self._active_assignments.pop(assignment_id, None)
            if not record:
                logger.warning("Attempted to complete unknown assignment %s", assignment_id)
                return

            task_id, worker_id, lease_id = record
            if worker_id in self._active_worker_tasks:
                self._active_worker_tasks[worker_id].discard(assignment_id)

            self.lease_manager.release_lease(lease_id=lease_id, worker_id=worker_id)
            logger.info("Assignment %s completed; worker %s freed", assignment_id, worker_id)

        # Trigger drain of pending queued tasks
        self.drain_queue()

    def drain_queue(self) -> list[AssignmentPayload]:
        """Attempt to schedule pending tasks from priority queue."""
        dispatched: list[AssignmentPayload] = []
        with self._lock:
            temp_queue: list[PrioritizedTask] = []
            while self._task_queue:
                item = heapq.heappop(self._task_queue)
                try:
                    payload = self._schedule_now(item.requirements)
                    dispatched.append(payload)
                except NoEligibleWorkerError:
                    temp_queue.append(item)

            for item in temp_queue:
                heapq.heappush(self._task_queue, item)

        return dispatched

    def get_queue_depth(self) -> int:
        """Return count of tasks currently waiting in queue."""
        with self._lock:
            return len(self._task_queue)
