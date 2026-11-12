"""Observation domain contracts."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Observation(BaseModel):
    """Multimodal or structured snapshot of environment state."""

    model_config = ConfigDict(validate_assignment=True)

    observation_id: str
    task_id: str
    session_id: str
    timestamp: datetime
    screenshot_ref: str | None = None
    dom_snapshot: str | None = None
    accessibility_tree: dict[str, Any] | None = None
    focused_element: str | None = None
    window_title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"
