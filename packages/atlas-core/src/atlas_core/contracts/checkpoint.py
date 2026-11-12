"""Checkpoint domain contracts for state recovery."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atlas_core.contracts.task import TaskStatus


class Checkpoint(BaseModel):
    """Point-in-time state snapshot of a task for rollback and recovery."""

    model_config = ConfigDict(validate_assignment=True)

    checkpoint_id: str
    task_id: str
    sequence: int
    state: TaskStatus
    timestamp: datetime
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"
