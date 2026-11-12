"""Session domain contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SessionStatus(StrEnum):
    """Lifecycle status of an execution session."""

    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"
    FAILED = "failed"


class Session(BaseModel):
    """Active execution environment context tied to a task."""

    model_config = ConfigDict(validate_assignment=True)

    session_id: str
    task_id: str
    session_type: str = "browser"
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"
