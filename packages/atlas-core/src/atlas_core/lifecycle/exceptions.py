"""Lifecycle and state machine exceptions for ATLAS."""

from atlas_core.contracts.task import TaskStatus


class LifecycleError(Exception):
    """Base exception for all lifecycle and state machine errors."""


class InvalidStateTransitionError(LifecycleError):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        from_status: TaskStatus | str | None = None,
        to_status: TaskStatus | str | None = None,
        message: str | None = None,
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        if message:
            self.message = message
        elif from_status is not None and to_status is not None:
            self.message = f"Invalid state transition from {from_status} to {to_status}"
        else:
            self.message = "Invalid state transition"
        super().__init__(self.message)
