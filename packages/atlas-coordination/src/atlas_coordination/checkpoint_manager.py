"""CheckpointManager for atomic, sealed, and verified state snapshots in ATLAS."""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.task import TaskStatus
from atlas_storage.interfaces import (
    CheckpointNotFoundError,
    CheckpointStoreProtocol,
    CorruptedCheckpointError,
    EventStoreProtocol,
)

# Common sensitive parameter / key patterns for redaction
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(password|secret|token|api_key|apikey|bearer|credential|auth|private_key|session_token)"
)
REDACTED_SENTINEL = "***REDACTED***"

# Match database / service URIs containing credentials: scheme://user:pass@host
_URI_CREDENTIAL_PATTERN = re.compile(r"(://[^:\s@]+):([^@\s]+)@")

# Raw token patterns to scrub from unstructured strings
_RAW_TOKEN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[a-zA-Z0-9_\-]{20,}"),
    re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}"),
    re.compile(r"gh[pousr]_[a-zA-Z0-9]{36,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"eyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]+"),
]


def redact_secrets(data: Any) -> Any:
    """Recursively redact sensitive key-values and authorization tokens from dicts, lists, and strings."""
    if isinstance(data, dict):
        sanitized: dict[str, Any] = {}
        for key, value in data.items():
            if _SENSITIVE_KEY_PATTERN.search(key):
                sanitized[key] = REDACTED_SENTINEL
            else:
                sanitized[key] = redact_secrets(value)
        return sanitized
    elif isinstance(data, list):
        return [redact_secrets(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(redact_secrets(item) for item in data)
    elif isinstance(data, str):
        result = data
        if "Bearer " in result or "bearer " in result:
            result = re.sub(
                r"(?i)bearer\s+[a-zA-Z0-9_\-\.]+",
                "Bearer " + REDACTED_SENTINEL,
                result,
            )
        result = _URI_CREDENTIAL_PATTERN.sub(r"\1:" + REDACTED_SENTINEL + "@", result)
        for pattern in _RAW_TOKEN_PATTERNS:
            result = pattern.sub(REDACTED_SENTINEL, result)
        return result
    return data


class CheckpointManager:
    """Manager for creating, sealing, verifying, and rolling back task execution checkpoints."""

    def __init__(
        self,
        checkpoint_store: CheckpointStoreProtocol,
        event_store: EventStoreProtocol | None = None,
    ) -> None:
        self.checkpoint_store = checkpoint_store
        self.event_store = event_store

    def create_checkpoint(
        self,
        task_id: str,
        state: TaskStatus | str,
        sequence: int,
        worker_id: str | None = None,
        lease_generation: int = 1,
        session_id: str | None = None,
        plan_id: str | None = None,
        plan_version: int = 1,
        current_step_id: str | None = None,
        completed_action_ids: list[str] | None = None,
        pending_action_ids: list[str] | None = None,
        uncertain_action_ids: list[str] | None = None,
        last_event_sequence: int = 0,
        state_snapshot: dict[str, Any] | None = None,
        environment_metadata: dict[str, Any] | None = None,
        verification_evidence_refs: list[str] | None = None,
        recovery_metadata: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Checkpoint:
        """Create, sanitize, seal with SHA-256 integrity hash, and persist a checkpoint."""
        checkpoint_id = f"chk_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)

        # Redact sensitive credentials/tokens in state snapshot and metadata before computing hash
        clean_snapshot = redact_secrets(state_snapshot or {})
        clean_env_meta = redact_secrets(environment_metadata or {})
        clean_rec_meta = redact_secrets(recovery_metadata or {})
        clean_meta = redact_secrets(metadata or {})

        task_state = TaskStatus(state) if isinstance(state, str) else state

        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            task_id=task_id,
            session_id=session_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            state=task_state,
            sequence=sequence,
            plan_id=plan_id,
            plan_version=plan_version,
            current_step_id=current_step_id,
            completed_action_ids=completed_action_ids or [],
            pending_action_ids=pending_action_ids or [],
            uncertain_action_ids=uncertain_action_ids or [],
            last_event_sequence=last_event_sequence,
            state_snapshot=clean_snapshot,
            environment_metadata=clean_env_meta,
            verification_evidence_refs=verification_evidence_refs or [],
            recovery_metadata=clean_rec_meta,
            metadata=clean_meta,
            timestamp=now,
        )

        # Seal computes SHA-256 hash
        checkpoint.seal()

        # Persist checkpoint
        self.checkpoint_store.save_checkpoint(checkpoint)

        # Record event in event store if configured
        if self.event_store is not None:
            latest_seq = self.event_store.get_latest_sequence(task_id)
            event = ExecutionEvent(
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                session_id=session_id,
                sequence=latest_seq + 1,
                event_type=EventType.CHECKPOINT_CREATED,
                timestamp=now,
                payload={
                    "checkpoint_id": checkpoint_id,
                    "sequence": sequence,
                    "state": str(state),
                    "lease_generation": lease_generation,
                    "checkpoint_hash": checkpoint.checkpoint_hash,
                },
                correlation_id=checkpoint_id,
            )
            self.event_store.append_event(event)

        return checkpoint

    def get_checkpoint(self, checkpoint_id: str, verify: bool = True) -> Checkpoint | None:
        """Retrieve a checkpoint, optionally verifying its cryptographic SHA-256 seal."""
        chk = self.checkpoint_store.get_checkpoint(checkpoint_id)
        if chk is None:
            return None

        if verify and not chk.verify_hash():
            raise CorruptedCheckpointError(
                f"Checkpoint '{checkpoint_id}' failed cryptographic integrity check. "
                f"Stored hash: {chk.checkpoint_hash}, computed hash: {chk.compute_hash()}"
            )

        return chk

    def get_latest_valid_checkpoint(self, task_id: str) -> Checkpoint | None:
        """Retrieve the latest checkpoint that passes SHA-256 verification."""
        checkpoints = self.checkpoint_store.list_checkpoints(task_id, limit=50)
        for chk in checkpoints:
            if chk.verify_hash():
                return chk
        return None

    def rollback_to_last_valid(self, task_id: str) -> Checkpoint:
        """Roll back to the most recent uncorrupted checkpoint in the execution chain."""
        valid_chk = self.get_latest_valid_checkpoint(task_id)
        if valid_chk is None:
            raise CheckpointNotFoundError(
                f"No valid, uncorrupted checkpoints found for task '{task_id}' to roll back to."
            )
        return valid_chk

    def list_checkpoints(self, task_id: str, limit: int = 50) -> list[Checkpoint]:
        """List checkpoints for a task ordered by creation time descending."""
        return self.checkpoint_store.list_checkpoints(task_id, limit=limit)
