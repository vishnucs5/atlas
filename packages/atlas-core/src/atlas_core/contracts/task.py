"""Task and TaskRequest domain contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(StrEnum):
    """Finite states of an ATLAS task lifecycle."""

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_FOR_ENVIRONMENT = "WAITING_FOR_ENVIRONMENT"
    RECOVERING = "RECOVERING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TaskPriority(StrEnum):
    """Execution priority levels for tasks."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TaskRequest(BaseModel):
    """Client request to initialize an ATLAS task."""

    model_config = ConfigDict(validate_assignment=True)

    objective: str
    priority: TaskPriority = TaskPriority.NORMAL
    metadata: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 3600
    schema_version: str = "1.0"


class Task(BaseModel):
    """Primary materialized record representing an orchestrated task."""

    model_config = ConfigDict(validate_assignment=True)

    task_id: str
    objective: str
    status: TaskStatus = TaskStatus.CREATED
    priority: TaskPriority = TaskPriority.NORMAL
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    current_checkpoint_id: str | None = None
    schema_version: str = "1.0"
