"""Storage protocol and exception definitions for ATLAS task, event, checkpoint, worker, and ledger persistence."""

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.event import ExecutionEvent
from atlas_core.contracts.ledger import ActionExecutionRecord, ActionExecutionStatus
from atlas_core.contracts.task import Task, TaskStatus
from atlas_core.contracts.worker import WorkerLease, WorkerRecord, WorkerStatus


class StorageError(Exception):
    """Base exception for all storage engine errors."""


class TaskNotFoundError(StorageError):
    """Raised when an operation targets a nonexistent task."""


class SequenceCollisionError(StorageError):
    """Raised when an event sequence number collides with an existing event for the same task."""


class OptimisticLockError(StorageError):
    """Raised when a task update fails due to an expected status/version mismatch."""


class StaleWorkerError(StorageError):
    """Raised when a worker attempts a commit with a stale or expired lease generation (fencing token)."""


class LeaseExpiredError(StorageError):
    """Raised when an operation targets an expired task lease."""


class CorruptedCheckpointError(StorageError):
    """Raised when a checkpoint fails cryptographic integrity hash verification."""


class CheckpointNotFoundError(StorageError):
    """Raised when an operation targets a nonexistent checkpoint."""


class ActionNotFoundError(StorageError):
    """Raised when an operation targets a nonexistent action ledger record."""


@runtime_checkable
class TaskStoreProtocol(Protocol):
    """Protocol for reading and writing materialized task projections."""

    def save_task(self, task: Task) -> None:
        """Persist or overwrite a materialized task record."""
        ...

    def get_task(self, task_id: str) -> Task | None:
        """Retrieve a materialized task by its unique identifier."""
        ...

    def update_task_status(
        self,
        task_id: str,
        new_status: TaskStatus,
        expected_status: TaskStatus | None = None,
    ) -> Task:
        """Update the status of a task with optional optimistic concurrency check."""
        ...

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks with optional status filter and pagination."""
        ...


@runtime_checkable
class EventStoreProtocol(Protocol):
    """Protocol for append-only execution event persistence."""

    def append_event(self, event: ExecutionEvent) -> None:
        """Append an immutable event to the event stream."""
        ...

    def append_events(self, events: list[ExecutionEvent]) -> None:
        """Batch append multiple events atomically."""
        ...

    def get_events(
        self,
        task_id: str,
        since_sequence: int = 0,
    ) -> list[ExecutionEvent]:
        """Retrieve events for a given task, ordered strictly by sequence number."""
        ...

    def get_latest_event(self, task_id: str) -> ExecutionEvent | None:
        """Retrieve the event with the highest sequence number for a given task."""
        ...

    def get_latest_sequence(self, task_id: str) -> int:
        """Retrieve the highest sequence number recorded for a task (0 if none exist)."""
        ...


@runtime_checkable
class CheckpointStoreProtocol(Protocol):
    """Protocol for durable versioned checkpoint persistence."""

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Persist a versioned, sealed task checkpoint."""
        ...

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Retrieve a checkpoint by its unique ID."""
        ...

    def get_latest_checkpoint(self, task_id: str) -> Checkpoint | None:
        """Retrieve the most recent checkpoint recorded for a task."""
        ...

    def list_checkpoints(self, task_id: str, limit: int = 50) -> list[Checkpoint]:
        """List checkpoints for a task ordered from newest to oldest."""
        ...


@runtime_checkable
class ActionLedgerStoreProtocol(Protocol):
    """Protocol for durable action execution tracking and idempotency checking."""

    def record_action_attempt(self, record: ActionExecutionRecord) -> None:
        """Record an initial or retried action execution attempt."""
        ...

    def update_action_status(
        self,
        task_id: str,
        idempotency_key: str,
        attempt: int,
        status: ActionExecutionStatus,
        output: dict[str, Any] | None = None,
        verification_result: dict[str, Any] | None = None,
        error: str | None = None,
        completed_at: datetime | None = None,
    ) -> ActionExecutionRecord:
        """Update the execution outcome and verification result of an action attempt."""
        ...

    def get_action_record(
        self, task_id: str, idempotency_key: str, attempt: int = 1
    ) -> ActionExecutionRecord | None:
        """Retrieve an action execution record by task ID, idempotency key, and attempt number."""
        ...

    def get_latest_action(self, task_id: str, idempotency_key: str) -> ActionExecutionRecord | None:
        """Retrieve the latest attempt for a given action by its idempotency key."""
        ...

    def get_task_actions(self, task_id: str) -> list[ActionExecutionRecord]:
        """Retrieve all action execution records recorded for a given task."""
        ...


@runtime_checkable
class WorkerStoreProtocol(Protocol):
    """Protocol for worker registration, heartbeat tracking, and lease fencing management."""

    def register_worker(self, worker: WorkerRecord) -> None:
        """Register a worker in the worker registry."""
        ...

    def heartbeat_worker(self, worker_id: str, status: WorkerStatus | None = None) -> None:
        """Record a heartbeat timestamp and optional status update for a worker."""
        ...

    def get_worker(self, worker_id: str) -> WorkerRecord | None:
        """Retrieve a worker record by worker ID."""
        ...

    def list_workers(self, status: WorkerStatus | None = None) -> list[WorkerRecord]:
        """List workers with optional status filter."""
        ...

    def acquire_lease(self, task_id: str, worker_id: str, ttl_seconds: float = 30.0) -> WorkerLease:
        """Acquire an exclusive task lease, incrementing generation fencing token."""
        ...

    def renew_lease(self, lease_id: str, worker_id: str, ttl_seconds: float = 30.0) -> WorkerLease:
        """Renew an existing active task lease."""
        ...

    def release_lease(self, lease_id: str, worker_id: str) -> None:
        """Explicitly release an active task lease."""
        ...

    def get_active_lease(self, task_id: str) -> WorkerLease | None:
        """Retrieve the active lease for a task if not expired."""
        ...

    def validate_lease_fencing(self, task_id: str, expected_generation: int) -> bool:
        """Validate whether the specified generation matches the active lease fencing token."""
        ...
