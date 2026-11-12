"""ExecutionEvent and EventType domain contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(StrEnum):
    """Enumeration of all event types captured in the event log."""

    TASK_CREATED = "TASK_CREATED"
    TASK_QUEUED = "TASK_QUEUED"
    PLAN_GENERATED = "PLAN_GENERATED"
    MODEL_REQUESTED = "MODEL_REQUESTED"
    MODEL_RESPONDED = "MODEL_RESPONDED"
    ENVIRONMENT_ALLOCATED = "ENVIRONMENT_ALLOCATED"
    OBSERVATION_CAPTURED = "OBSERVATION_CAPTURED"
    ACTION_PROPOSED = "ACTION_PROPOSED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_DENIED = "APPROVAL_DENIED"
    ACTION_STARTED = "ACTION_STARTED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_FAILED = "ACTION_FAILED"
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    CHECKPOINT_CREATED = "CHECKPOINT_CREATED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_PAUSED = "TASK_PAUSED"
    TASK_CANCELLED = "TASK_CANCELLED"


class ExecutionEvent(BaseModel):
    """Immutable event representing a state transition or lifecycle occurrence."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    task_id: str
    session_id: str | None = None
    sequence: int
    event_type: EventType
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str
    schema_version: str = "1.0"
