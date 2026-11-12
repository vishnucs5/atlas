"""Worker, lease, and fencing token domain contracts."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkerStatus(StrEnum):
    """Lifecycle status of a computer-use worker process or daemon."""

    IDLE = "IDLE"
    BUSY = "BUSY"
    DRAINING = "DRAINING"
    DISCONNECTED = "DISCONNECTED"
    TERMINATED = "TERMINATED"


class LeaseStatus(StrEnum):
    """Lifecycle status of a task execution lease."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"
    REVOKED = "REVOKED"


class WorkerRecord(BaseModel):
    """Metadata, capability, and health tracking record for an execution worker."""

    model_config = ConfigDict(validate_assignment=True)

    worker_id: str
    hostname: str
    status: WorkerStatus = WorkerStatus.IDLE
    capabilities: list[str] = Field(default_factory=list)
    current_task_id: str | None = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_heartbeat_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"


class WorkerLease(BaseModel):
    """Exclusive task execution lease with monotonic fencing token generation."""

    model_config = ConfigDict(validate_assignment=True)

    lease_id: str
    task_id: str
    worker_id: str
    generation: int = 1
    status: LeaseStatus = LeaseStatus.ACTIVE
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    schema_version: str = "1.0"

    def is_expired(self, at_time: datetime | None = None) -> bool:
        """Check if lease has passed its expiration deadline."""
        now = at_time or datetime.now(UTC)
        return now >= self.expires_at or self.status != LeaseStatus.ACTIVE
