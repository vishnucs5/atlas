"""Runtime interface protocol for ATLAS."""

from typing import Protocol, runtime_checkable

from atlas_core.contracts.task import Task, TaskRequest


@runtime_checkable
class AtlasRuntime(Protocol):
    """Protocol defining the core execution and orchestration runtime lifecycle."""

    async def submit_task(self, request: TaskRequest) -> Task:
        """Submit and initialize a new task in the runtime."""
        ...

    async def get_task(self, task_id: str) -> Task | None:
        """Retrieve the materialized state of a task by ID."""
        ...

    async def list_tasks(self, limit: int = 50, offset: int = 0) -> list[Task]:
        """List tasks ordered by creation time."""
        ...

    async def cancel_task(self, task_id: str, reason: str | None = None) -> Task:
        """Cancel an active or pending task."""
        ...

    async def pause_task(self, task_id: str, reason: str | None = None) -> Task:
        """Pause execution of a running task."""
        ...

    async def resume_task(self, task_id: str) -> Task:
        """Resume execution of a paused task."""
        ...
