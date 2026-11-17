"""ATLAS Process and Task Lifecycle State Machines.

Defines deterministic state transitions for enterprise process instances and
individual process tasks, enforcing valid state invariants and terminal locking.
"""

from __future__ import annotations

from enum import StrEnum


class ProcessStatus(StrEnum):
    """Lifecycle states of an enterprise process instance."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ProcessTaskStatus(StrEnum):
    """Lifecycle states of a task execution within a process."""

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class InvalidProcessTransitionError(Exception):
    """Raised when an illegal process lifecycle state transition is attempted."""


class InvalidTaskTransitionError(Exception):
    """Raised when an illegal task lifecycle state transition is attempted."""


class ProcessStateMachine:
    """Finite State Machine governing ProcessInstance state progression."""

    TERMINAL_STATES = frozenset(
        {
            ProcessStatus.COMPLETED,
            ProcessStatus.COMPENSATED,
            ProcessStatus.FAILED,
            ProcessStatus.CANCELLED,
        }
    )

    VALID_TRANSITIONS: dict[ProcessStatus, set[ProcessStatus]] = {
        ProcessStatus.PENDING: {
            ProcessStatus.RUNNING,
            ProcessStatus.CANCELLED,
        },
        ProcessStatus.RUNNING: {
            ProcessStatus.SUSPENDED,
            ProcessStatus.COMPENSATING,
            ProcessStatus.COMPLETED,
            ProcessStatus.FAILED,
            ProcessStatus.CANCELLED,
        },
        ProcessStatus.SUSPENDED: {
            ProcessStatus.RUNNING,
            ProcessStatus.CANCELLED,
            ProcessStatus.FAILED,
        },
        ProcessStatus.COMPENSATING: {
            ProcessStatus.COMPENSATED,
            ProcessStatus.FAILED,
        },
        ProcessStatus.COMPENSATED: set(),
        ProcessStatus.COMPLETED: set(),
        ProcessStatus.FAILED: set(),
        ProcessStatus.CANCELLED: set(),
    }

    @classmethod
    def validate_transition(cls, current: ProcessStatus, target: ProcessStatus) -> None:
        """Validate whether a transition is allowed."""
        if current in cls.TERMINAL_STATES:
            raise InvalidProcessTransitionError(
                f"Cannot transition from terminal process state '{current}' to '{target}'."
            )
        allowed = cls.VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidProcessTransitionError(
                f"Invalid process state transition from '{current}' to '{target}'."
            )


class ProcessTaskStateMachine:
    """Finite State Machine governing ProcessTaskInstance state progression."""

    TERMINAL_STATES = frozenset(
        {
            ProcessTaskStatus.COMPLETED,
            ProcessTaskStatus.COMPENSATED,
            ProcessTaskStatus.FAILED,
            ProcessTaskStatus.SKIPPED,
            ProcessTaskStatus.CANCELLED,
        }
    )

    VALID_TRANSITIONS: dict[ProcessTaskStatus, set[ProcessTaskStatus]] = {
        ProcessTaskStatus.PENDING: {
            ProcessTaskStatus.READY,
            ProcessTaskStatus.SKIPPED,
            ProcessTaskStatus.CANCELLED,
        },
        ProcessTaskStatus.READY: {
            ProcessTaskStatus.RUNNING,
            ProcessTaskStatus.WAITING_APPROVAL,
            ProcessTaskStatus.CANCELLED,
        },
        ProcessTaskStatus.WAITING_APPROVAL: {
            ProcessTaskStatus.RUNNING,
            ProcessTaskStatus.FAILED,
            ProcessTaskStatus.CANCELLED,
        },
        ProcessTaskStatus.RUNNING: {
            ProcessTaskStatus.COMPLETED,
            ProcessTaskStatus.FAILED,
            ProcessTaskStatus.SUSPENDED,
            ProcessTaskStatus.CANCELLED,
        },
        ProcessTaskStatus.SUSPENDED: {
            ProcessTaskStatus.READY,
            ProcessTaskStatus.RUNNING,
            ProcessTaskStatus.FAILED,
            ProcessTaskStatus.CANCELLED,
        },
        ProcessTaskStatus.FAILED: {
            ProcessTaskStatus.COMPENSATING,
        },
        ProcessTaskStatus.COMPLETED: {
            ProcessTaskStatus.COMPENSATING,
        },
        ProcessTaskStatus.COMPENSATING: {
            ProcessTaskStatus.COMPENSATED,
            ProcessTaskStatus.FAILED,
        },
        ProcessTaskStatus.COMPENSATED: set(),
        ProcessTaskStatus.SKIPPED: set(),
        ProcessTaskStatus.CANCELLED: set(),
    }

    @classmethod
    def validate_transition(cls, current: ProcessTaskStatus, target: ProcessTaskStatus) -> None:
        """Validate whether a task transition is allowed."""
        if current in cls.TERMINAL_STATES and target not in {ProcessTaskStatus.COMPENSATING}:
            raise InvalidTaskTransitionError(
                f"Cannot transition from terminal task state '{current}' to '{target}'."
            )
        allowed = cls.VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidTaskTransitionError(
                f"Invalid task state transition from '{current}' to '{target}'."
            )
