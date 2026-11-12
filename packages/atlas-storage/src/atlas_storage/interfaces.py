"""Storage protocol and exception definitions for ATLAS task and event persistence."""

from typing import Protocol, runtime_checkable

from atlas_core.contracts.event import ExecutionEvent
from atlas_core.contracts.task import Task, TaskStatus


class StorageError(Exception):
    """Base exception for all storage engine errors."""


class TaskNotFoundError(StorageError):
    """Raised when an operation targets a nonexistent task."""


class SequenceCollisionError(StorageError):
    """Raised when an event sequence number collides with an existing event for the same task."""


class OptimisticLockError(StorageError):
    """Raised when a task update fails due to an expected status/version mismatch."""


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
