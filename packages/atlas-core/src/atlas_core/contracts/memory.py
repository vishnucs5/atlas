"""Shared memory schemas, scoping levels, and provenance contracts."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MemoryScope(StrEnum):
    """Access boundary scoping for shared knowledge entries."""

    TASK_SCOPED = "TASK_SCOPED"  # Accessible to agents working on the same task
    AGENT_SCOPED = "AGENT_SCOPED"  # Private scratchpad for an individual agent
    PROJECT_SCOPED = "PROJECT_SCOPED"  # Read-only curated reference knowledge across tasks


class MemoryEntry(BaseModel):
    """Versioned knowledge unit with origin provenance and trust classification."""

    model_config = ConfigDict(validate_assignment=True)

    key: str
    value: Any
    scope: MemoryScope
    task_id: str | None = None
    agent_id: str | None = None
    contributor_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    is_untrusted: bool = False  # Flagged true for external web extracts or raw model hallucinations
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"
