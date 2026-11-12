"""Action execution ledger contracts and status definitions."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionExecutionStatus(StrEnum):
    """Detailed lifecycle states for discrete action execution attempts."""

    NOT_STARTED = "NOT_STARTED"
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ActionExecutionRecord(BaseModel):
    """Durable ledger record tracking an individual action attempt."""

    model_config = ConfigDict(validate_assignment=True)

    action_id: str
    task_id: str
    idempotency_key: str
    attempt: int = 1
    status: ActionExecutionStatus = ActionExecutionStatus.NOT_STARTED
    worker_id: str
    lease_generation: int = 1
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    verification_result: dict[str, Any] | None = None
    error: str | None = None
    schema_version: str = "1.0"
