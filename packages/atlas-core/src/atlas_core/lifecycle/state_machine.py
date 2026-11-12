"""Deterministic 14-state task state machine enforcing ATLAS lifecycle invariants."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.task import Task, TaskStatus
from atlas_core.lifecycle.exceptions import InvalidStateTransitionError

_STATUS_TO_EVENT_TYPE: dict[TaskStatus, EventType] = {
    TaskStatus.CREATED: EventType.TASK_CREATED,
    TaskStatus.QUEUED: EventType.TASK_QUEUED,
    TaskStatus.PLANNING: EventType.PLAN_GENERATED,
    TaskStatus.READY: EventType.ENVIRONMENT_ALLOCATED,
    TaskStatus.RUNNING: EventType.ACTION_STARTED,
    TaskStatus.PAUSED: EventType.TASK_PAUSED,
    TaskStatus.WAITING_APPROVAL: EventType.APPROVAL_REQUESTED,
    TaskStatus.WAITING_FOR_ENVIRONMENT: EventType.ENVIRONMENT_ALLOCATED,
    TaskStatus.RECOVERING: EventType.RECOVERY_STARTED,
    TaskStatus.VERIFYING: EventType.VERIFICATION_COMPLETED,
    TaskStatus.COMPLETED: EventType.TASK_COMPLETED,
    TaskStatus.FAILED: EventType.TASK_FAILED,
    TaskStatus.CANCELLED: EventType.TASK_CANCELLED,
    TaskStatus.EXPIRED: EventType.TASK_FAILED,
}


_TERMINAL_STATES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.EXPIRED,
    }
)

_NON_TERMINAL_STATES: frozenset[TaskStatus] = frozenset(
    s for s in TaskStatus if s not in _TERMINAL_STATES
)


class TaskStateMachine:
    """Finite State Machine governing task lifecycle progression and event emission."""

    TERMINAL_STATES: frozenset[TaskStatus] = _TERMINAL_STATES
    NON_TERMINAL_STATES: frozenset[TaskStatus] = _NON_TERMINAL_STATES

    VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
        TaskStatus.CREATED: {
            TaskStatus.QUEUED,
            TaskStatus.CANCELLED,
            TaskStatus.EXPIRED,
        },
        TaskStatus.QUEUED: {
            TaskStatus.PLANNING,
            TaskStatus.CANCELLED,
            TaskStatus.EXPIRED,
        },
        TaskStatus.PLANNING: {
            TaskStatus.READY,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.EXPIRED,
        },
        TaskStatus.READY: {
            TaskStatus.RUNNING,
            TaskStatus.CANCELLED,
            TaskStatus.EXPIRED,
        },
        TaskStatus.RUNNING: {
            TaskStatus.PAUSED,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.WAITING_FOR_ENVIRONMENT,
            TaskStatus.RECOVERING,
            TaskStatus.VERIFYING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.EXPIRED,
        },
        TaskStatus.PAUSED: {
            TaskStatus.RUNNING,
            TaskStatus.CANCELLED,
            TaskStatus.EXPIRED,
        },
        TaskStatus.WAITING_APPROVAL: {
            TaskStatus.RUNNING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.EXPIRED,
        },
        TaskStatus.WAITING_FOR_ENVIRONMENT: {
            TaskStatus.RUNNING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.EXPIRED,
        },
        TaskStatus.RECOVERING: {
            TaskStatus.RUNNING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.EXPIRED,
        },
        TaskStatus.VERIFYING: {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.RECOVERING,
            TaskStatus.CANCELLED,
            TaskStatus.EXPIRED,
        },
        TaskStatus.COMPLETED: set(),
        TaskStatus.FAILED: set(),
        TaskStatus.CANCELLED: set(),
        TaskStatus.EXPIRED: set(),
    }

    def __init__(self) -> None:
        self._hooks: list[Callable[[ExecutionEvent], None]] = []

    def is_terminal(self, status: TaskStatus) -> bool:
        """Check whether a given status is a terminal state."""
        return TaskStatus(status) in self.TERMINAL_STATES

    def get_valid_transitions(self, from_status: TaskStatus) -> set[TaskStatus]:
        """Return the set of valid next states from the given status."""
        return set(self.VALID_TRANSITIONS.get(TaskStatus(from_status), set()))

    def can_transition(self, from_status: TaskStatus, to_status: TaskStatus) -> bool:
        """Evaluate if transition from from_status to to_status is allowed."""
        return TaskStatus(to_status) in self.get_valid_transitions(from_status)

    def register_hook(self, hook: Callable[[ExecutionEvent], None]) -> None:
        """Register a transition callback hook."""
        if hook not in self._hooks:
            self._hooks.append(hook)

    def unregister_hook(self, hook: Callable[[ExecutionEvent], None]) -> None:
        """Unregister a transition callback hook."""
        if hook in self._hooks:
            self._hooks.remove(hook)

    def create_transition_event(
        self,
        task_id: str,
        from_status: TaskStatus,
        to_status: TaskStatus,
        *,
        sequence: int = 1,
        session_id: str | None = None,
        correlation_id: str | None = None,
        reason: str | None = None,
        actor: str = "system",
        event_type: EventType | None = None,
        timestamp: datetime | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> ExecutionEvent:
        """Construct an immutable ExecutionEvent capturing the state transition."""
        payload: dict[str, Any] = {
            "from_status": from_status.value,
            "to_status": to_status.value,
            "reason": reason,
            "actor": actor,
        }
        if extra_payload:
            payload.update(extra_payload)

        resolved_event_type = (
            event_type
            if event_type is not None
            else _STATUS_TO_EVENT_TYPE.get(to_status, EventType.TASK_CREATED)
        )

        return ExecutionEvent(
            event_id=f"evt_{uuid4().hex[:16]}",
            task_id=task_id,
            session_id=session_id,
            sequence=sequence,
            event_type=resolved_event_type,
            timestamp=timestamp or datetime.now(UTC),
            payload=payload,
            correlation_id=correlation_id or f"corr_{uuid4().hex[:16]}",
            schema_version="1.0",
        )

    def transition(
        self,
        current: TaskStatus | Task,
        target: TaskStatus,
        *,
        reason: str | None = None,
        actor: str = "system",
    ) -> TaskStatus:
        """Validate and apply a transition between task states."""
        if isinstance(current, Task):
            self.transition_task(current, target, reason=reason, actor=actor)
            return target

        current_status = TaskStatus(current)
        target_status = TaskStatus(target)

        if not self.can_transition(current_status, target_status):
            raise InvalidStateTransitionError(
                from_status=current_status,
                to_status=target_status,
            )

        return target_status

    def transition_task(
        self,
        task: Task,
        target_status: TaskStatus,
        *,
        reason: str | None = None,
        actor: str = "system",
        session_id: str | None = None,
        correlation_id: str | None = None,
        sequence: int = 1,
        event_type: EventType | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> ExecutionEvent:
        """Validate transition, mutate task state, and emit ExecutionEvent to hooks."""
        from_status = task.status
        self.transition(from_status, target_status)

        now = datetime.now(UTC)
        event = self.create_transition_event(
            task_id=task.task_id,
            from_status=from_status,
            to_status=target_status,
            sequence=sequence,
            session_id=session_id,
            correlation_id=correlation_id,
            reason=reason,
            actor=actor,
            event_type=event_type,
            timestamp=now,
            extra_payload=extra_payload,
        )

        task.status = target_status
        task.updated_at = now

        for hook in list(self._hooks):
            hook(event)

        return event
