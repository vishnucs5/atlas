"""Checkpoint domain contracts for durable state recovery."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atlas_core.contracts.task import TaskStatus


class Checkpoint(BaseModel):
    """Point-in-time durable state snapshot of a task for rollback, reconciliation, and recovery."""

    model_config = ConfigDict(validate_assignment=True)

    checkpoint_id: str
    task_id: str
    sequence: int
    state: TaskStatus
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str | None = None
    worker_id: str | None = None
    lease_generation: int = 1
    plan_id: str | None = None
    plan_version: int = 1
    current_step_id: str | None = None
    completed_action_ids: list[str] = Field(default_factory=list)
    pending_action_ids: list[str] = Field(default_factory=list)
    uncertain_action_ids: list[str] = Field(default_factory=list)
    last_event_sequence: int = 0
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    environment_metadata: dict[str, Any] = Field(default_factory=dict)
    verification_evidence_refs: list[str] = Field(default_factory=list)
    recovery_metadata: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    checkpoint_hash: str | None = None
    schema_version: str = "1.0"

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 integrity hash over canonical JSON representation."""
        data = {
            "checkpoint_id": self.checkpoint_id,
            "task_id": self.task_id,
            "sequence": self.sequence,
            "state": self.state.value if isinstance(self.state, TaskStatus) else str(self.state),
            "session_id": self.session_id,
            "worker_id": self.worker_id,
            "lease_generation": self.lease_generation,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "current_step_id": self.current_step_id,
            "completed_action_ids": sorted(self.completed_action_ids),
            "pending_action_ids": sorted(self.pending_action_ids),
            "uncertain_action_ids": sorted(self.uncertain_action_ids),
            "last_event_sequence": self.last_event_sequence,
            "state_snapshot": self.state_snapshot,
            "environment_metadata": self.environment_metadata,
            "verification_evidence_refs": sorted(self.verification_evidence_refs),
            "recovery_metadata": self.recovery_metadata,
            "schema_version": self.schema_version,
        }
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def seal(self) -> "Checkpoint":
        """Compute and seal checkpoint_hash into this instance."""
        self.checkpoint_hash = self.compute_hash()
        return self

    def verify_hash(self) -> bool:
        """Verify whether the checkpoint has not been tampered with or corrupted."""
        if not self.checkpoint_hash:
            return False
        return self.checkpoint_hash == self.compute_hash()
