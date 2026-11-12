"""Durable Action Execution Ledger for tracking action lifecycle, deduplication, and safe retry policies."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from atlas_core.contracts.ledger import ActionExecutionRecord, ActionExecutionStatus
from atlas_storage.interfaces import ActionLedgerStoreProtocol

from atlas_coordination.checkpoint_manager import redact_secrets
from atlas_coordination.lease_manager import WorkerLeaseManager

# Actions that are inherently safe to repeat without side effects
IDEMPOTENT_ACTION_TYPES = {
    "navigate",
    "goto",
    "scroll",
    "get_state",
    "observe",
    "wait",
    "screenshot",
    "snapshot",
    "verify",
    "hover",
    "inspect",
}


class NonIdempotentActionUncertaintyError(Exception):
    """Raised when attempting to blindly re-execute a non-idempotent action in UNKNOWN status without physical reconciliation."""


def is_action_idempotent(action_type: str) -> bool:
    """Determine whether an action type is safe for automatic retry."""
    return action_type.lower() in IDEMPOTENT_ACTION_TYPES


def compute_idempotency_key(
    task_id: str,
    action_type: str,
    parameters: dict[str, Any],
    step_id: str | None = None,
) -> str:
    """Compute deterministic SHA-256 idempotency key for an action."""
    clean_params = redact_secrets(parameters)
    canonical_repr = json.dumps(clean_params, sort_keys=True, separators=(",", ":"))
    raw = f"{task_id}:{step_id or 'none'}:{action_type.lower()}:{canonical_repr}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class ActionLedger:
    """Orchestrates durable action execution logging, commit-time fencing, and idempotency deduplication."""

    def __init__(
        self,
        store: ActionLedgerStoreProtocol,
        lease_manager: WorkerLeaseManager | None = None,
    ) -> None:
        self.store = store
        self.lease_manager = lease_manager

    def start_action(
        self,
        action_id: str,
        task_id: str,
        action_type: str,
        parameters: dict[str, Any],
        worker_id: str,
        lease_generation: int,
        idempotency_key: str | None = None,
        step_id: str | None = None,
        force_retry: bool = False,
    ) -> ActionExecutionRecord:
        """Start and record an action attempt, verifying fencing and idempotency."""
        # 1. Validate commit-time fencing token
        if self.lease_manager is not None:
            self.lease_manager.assert_fencing(task_id, lease_generation, worker_id=worker_id)

        key = idempotency_key or compute_idempotency_key(task_id, action_type, parameters, step_id)

        # 2. Check for existing attempts
        latest = self.store.get_latest_action(task_id, key)
        next_attempt = 1

        if latest is not None:
            # Deduplication: already completed/verified
            if latest.status in (ActionExecutionStatus.SUCCEEDED, ActionExecutionStatus.VERIFIED):
                return latest

            # If previous attempt is in UNKNOWN state and action is non-idempotent, reject retry without reconciliation
            if latest.status == ActionExecutionStatus.UNKNOWN and not force_retry:
                if not is_action_idempotent(action_type):
                    raise NonIdempotentActionUncertaintyError(
                        f"Action '{action_id}' (key: {key}, type: '{action_type}') is in UNKNOWN state. "
                        f"Non-idempotent action cannot be re-executed without physical environment reconciliation."
                    )

            next_attempt = latest.attempt + 1

        # 3. Clean parameters
        clean_params = redact_secrets(parameters)

        record = ActionExecutionRecord(
            action_id=action_id,
            task_id=task_id,
            idempotency_key=key,
            attempt=next_attempt,
            status=ActionExecutionStatus.STARTED,
            worker_id=worker_id,
            lease_generation=lease_generation,
            started_at=datetime.now(UTC),
            action_type=action_type,
            parameters=clean_params,
        )

        self.store.record_action_attempt(record)
        return record

    def mark_succeeded(
        self,
        task_id: str,
        idempotency_key: str,
        attempt: int,
        output: dict[str, Any] | None = None,
        lease_generation: int = 1,
        worker_id: str | None = None,
    ) -> ActionExecutionRecord:
        """Mark action attempt as SUCCEEDED after execution."""
        if self.lease_manager is not None:
            self.lease_manager.assert_fencing(task_id, lease_generation, worker_id=worker_id)

        clean_output = redact_secrets(output) if output else None
        return self.store.update_action_status(
            task_id=task_id,
            idempotency_key=idempotency_key,
            attempt=attempt,
            status=ActionExecutionStatus.SUCCEEDED,
            output=clean_output,
            completed_at=datetime.now(UTC),
        )

    def mark_verified(
        self,
        task_id: str,
        idempotency_key: str,
        attempt: int,
        verification_result: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        lease_generation: int = 1,
        worker_id: str | None = None,
    ) -> ActionExecutionRecord:
        """Mark action attempt as VERIFIED after post-condition verification."""
        if self.lease_manager is not None:
            self.lease_manager.assert_fencing(task_id, lease_generation, worker_id=worker_id)

        clean_v = redact_secrets(verification_result) if verification_result else None
        clean_out = redact_secrets(output) if output else None
        return self.store.update_action_status(
            task_id=task_id,
            idempotency_key=idempotency_key,
            attempt=attempt,
            status=ActionExecutionStatus.VERIFIED,
            output=clean_out,
            verification_result=clean_v,
            completed_at=datetime.now(UTC),
        )

    def mark_failed(
        self,
        task_id: str,
        idempotency_key: str,
        attempt: int,
        error: str,
        lease_generation: int = 1,
        worker_id: str | None = None,
    ) -> ActionExecutionRecord:
        """Mark action attempt as FAILED."""
        if self.lease_manager is not None:
            self.lease_manager.assert_fencing(task_id, lease_generation, worker_id=worker_id)

        return self.store.update_action_status(
            task_id=task_id,
            idempotency_key=idempotency_key,
            attempt=attempt,
            status=ActionExecutionStatus.FAILED,
            error=error,
            completed_at=datetime.now(UTC),
        )

    def mark_unknown(
        self,
        task_id: str,
        idempotency_key: str,
        attempt: int,
        reason: str,
    ) -> ActionExecutionRecord:
        """Transition an action to UNKNOWN state during recovery or upon worker loss.

        Does not require worker fencing check because this is called by the recovery coordinator.
        """
        return self.store.update_action_status(
            task_id=task_id,
            idempotency_key=idempotency_key,
            attempt=attempt,
            status=ActionExecutionStatus.UNKNOWN,
            error=f"Outcome uncertain: {reason}",
            completed_at=datetime.now(UTC),
        )

    def get_action(
        self, task_id: str, idempotency_key: str, attempt: int = 1
    ) -> ActionExecutionRecord | None:
        """Retrieve a specific action attempt."""
        return self.store.get_action_record(task_id, idempotency_key, attempt=attempt)

    def get_latest_action(self, task_id: str, idempotency_key: str) -> ActionExecutionRecord | None:
        """Retrieve the latest attempt for an action."""
        return self.store.get_latest_action(task_id, idempotency_key)

    def get_task_actions(self, task_id: str) -> list[ActionExecutionRecord]:
        """List all action execution records for a task."""
        return self.store.get_task_actions(task_id)
