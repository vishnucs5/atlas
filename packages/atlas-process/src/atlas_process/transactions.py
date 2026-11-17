"""ATLAS Multi-System Transaction Coordination & Compensation Engine.

Implements the Saga distributed transaction pattern with explicit compensation handlers,
verification invariants, idempotency keys, unknown-outcome reconciliation, and honest audit states.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from atlas_process.idempotency import (
    OperationStatus,
    ReconciliationRequiredError,
    SagaError,
    compute_request_fingerprint,
)


class SagaStepStatus(StrEnum):
    """Lifecycle states of an individual saga transaction step."""

    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    COMPENSATION_UNAVAILABLE = "COMPENSATION_UNAVAILABLE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"


class SagaStatus(StrEnum):
    """Overall status of a saga transaction."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"


class NonIdempotentBlindRetryError(SagaError):
    """Raised when a non-idempotent operation is subjected to an unsafe blind retry."""


class CompensationUnavailableError(SagaError):
    """Raised when compensation is triggered but no rollback handler exists for a completed step."""


class CompensationFailedError(SagaError):
    """Raised when a compensation handler executes but fails or fails post-condition verification."""


class SagaStep(BaseModel):
    """Specification of a forward operation and its corresponding compensation."""

    step_id: str = Field(default_factory=lambda: f"step_{uuid.uuid4().hex[:10]}")
    name: str
    is_idempotent: bool = False
    idempotency_key: str = Field(default_factory=lambda: f"idem_{uuid.uuid4().hex[:12]}")
    status: SagaStepStatus = SagaStepStatus.PENDING
    forward_payload: dict[str, Any] = Field(default_factory=dict)
    forward_result: dict[str, Any] = Field(default_factory=dict)
    compensation_payload: dict[str, Any] = Field(default_factory=dict)
    compensation_attempts: int = 0
    compensation_history: list[dict[str, Any]] = Field(default_factory=list)
    compensation_verification: dict[str, Any] | None = None
    error_message: str | None = None
    executed_at: float | None = None
    compensated_at: float | None = None


class SagaTransaction(BaseModel):
    """Managed saga transaction containing an ordered sequence of transactional steps."""

    saga_id: str = Field(default_factory=lambda: f"saga_{uuid.uuid4().hex[:12]}")
    process_instance_id: str
    status: SagaStatus = SagaStatus.ACTIVE
    steps: list[SagaStep] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    completed_at: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SagaCoordinator:
    """Coordinates forward execution, reverse compensation, and unknown-outcome reconciliation."""

    def __init__(self, storage: Any | None = None) -> None:
        self.storage = storage
        self._sagas: dict[str, SagaTransaction] = {}
        self._registered_handlers: dict[str, Callable[[dict[str, Any]], bool]] = {}
        self._registered_verifiers: dict[str, Callable[[dict[str, Any]], bool]] = {}
        self._reconciliation_queue: list[dict[str, Any]] = []

    def register_compensation_handler(
        self,
        step_name: str,
        handler: Callable[[dict[str, Any]], bool],
        verification_fn: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        """Register a reusable compensation handler and optional verification function for a step type."""
        self._registered_handlers[step_name] = handler
        if verification_fn:
            self._registered_verifiers[step_name] = verification_fn

    def create_saga(
        self, process_instance_id: str, metadata: dict[str, Any] | None = None
    ) -> SagaTransaction:
        """Create and register a new saga transaction."""
        saga = SagaTransaction(process_instance_id=process_instance_id, metadata=metadata or {})
        self._sagas[saga.saga_id] = saga
        if self.storage and hasattr(self.storage, "save_saga"):
            self.storage.save_saga(saga)
        return saga

    def get_saga(self, saga_id: str) -> SagaTransaction | None:
        """Retrieve a saga transaction by ID, loading from durable storage if absent from RAM."""
        saga = self._sagas.get(saga_id)
        if not saga and self.storage and hasattr(self.storage, "get_saga"):
            saga = self.storage.get_saga(saga_id)
            if saga:
                self._sagas[saga_id] = saga
        return saga

    def execute_step(
        self,
        saga_id: str,
        step: SagaStep,
        action_fn: Callable[[dict[str, Any]], dict[str, Any]],
        compensation_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a forward step in the saga."""
        saga = self.get_saga(saga_id)
        if not saga:
            raise KeyError(f"Saga '{saga_id}' not found.")

        saga.steps.append(step)
        step.status = SagaStepStatus.EXECUTING
        step.compensation_payload = compensation_payload or {}
        if self.storage and hasattr(self.storage, "save_saga"):
            self.storage.save_saga(saga)

        # Check durable operation idempotency if key is present
        tenant_id = saga.metadata.get("tenant_id", "tenant_default")
        if step.idempotency_key and self.storage and hasattr(self.storage, "start_operation"):
            op_status, cached_resp = self.storage.start_operation(
                tenant_id=tenant_id,
                idempotency_key=step.idempotency_key,
                process_instance_id=saga.process_instance_id or "unknown_inst",
                task_def_id=step.name,
                operation_name=step.name,
                request_fingerprint=compute_request_fingerprint(step.forward_payload),
                request_payload=step.forward_payload,
            )
            if op_status == OperationStatus.SUCCEEDED and cached_resp is not None:
                step.status = SagaStepStatus.COMPLETED
                step.forward_result = cached_resp
                step.executed_at = time.time()
                if hasattr(self.storage, "save_saga"):
                    self.storage.save_saga(saga)
                return cached_resp

        try:
            result = action_fn(step.forward_payload)
            step.status = SagaStepStatus.COMPLETED
            step.forward_result = result
            step.executed_at = time.time()
            if (
                step.idempotency_key
                and self.storage
                and hasattr(self.storage, "complete_operation")
            ):
                self.storage.complete_operation(
                    tenant_id=tenant_id,
                    idempotency_key=step.idempotency_key,
                    response_payload=result,
                )
            if self.storage and hasattr(self.storage, "save_saga"):
                self.storage.save_saga(saga)
            return result
        except TimeoutError as exc:
            if (
                step.idempotency_key
                and self.storage
                and hasattr(self.storage, "mark_operation_unknown_outcome")
            ):
                self.storage.mark_operation_unknown_outcome(
                    tenant_id=tenant_id,
                    idempotency_key=step.idempotency_key,
                    reason=f"TimeoutError: {exc}",
                )
            # Unknown outcome! If non-idempotent, DO NOT blind retry!
            step.status = SagaStepStatus.RECONCILIATION_REQUIRED
            step.error_message = f"Timeout encountered: {exc}"
            saga.status = SagaStatus.RECONCILIATION_REQUIRED
            rec_item = {
                "saga_id": saga_id,
                "step_id": step.step_id,
                "idempotency_key": step.idempotency_key,
                "reason": "Timeout on external call",
                "queued_at": time.time(),
            }
            self._reconciliation_queue.append(rec_item)
            if self.storage and hasattr(self.storage, "save_saga"):
                self.storage.save_saga(saga)
            if self.storage and hasattr(self.storage, "record_reconciliation"):
                self.storage.record_reconciliation(
                    saga_id=saga_id,
                    step_id=step.step_id,
                    reason=rec_item["reason"],
                    notes=f"TimeoutError: {exc}",
                )
            raise ReconciliationRequiredError(
                f"Step '{step.name}' entered RECONCILIATION_REQUIRED: outcome unknown after timeout."
            ) from exc
        except Exception as exc:
            if step.idempotency_key and self.storage and hasattr(self.storage, "fail_operation"):
                self.storage.fail_operation(
                    tenant_id=tenant_id,
                    idempotency_key=step.idempotency_key,
                    error_message=str(exc),
                    retryable=False,
                )
            step.status = SagaStepStatus.FAILED
            step.error_message = str(exc)
            saga.status = SagaStatus.COMPENSATING
            if self.storage and hasattr(self.storage, "save_saga"):
                self.storage.save_saga(saga)
            # Trigger automatic compensation of preceding steps
            self.compensate_saga(saga_id)
            raise

    def compensate_saga(
        self,
        saga_id: str,
        compensation_handlers: (dict[str, Callable[[dict[str, Any]], bool]] | None) = None,
    ) -> bool:
        """Execute compensation steps in reverse order for all completed steps.

        Mandatory Invariant: Never mark an operation compensated unless compensation was
        actually executed successfully and verified.
        """
        saga = self.get_saga(saga_id)
        if not saga:
            raise KeyError(f"Saga '{saga_id}' not found.")

        saga.status = SagaStatus.COMPENSATING
        if self.storage and hasattr(self.storage, "save_saga"):
            self.storage.save_saga(saga)

        handlers = dict(self._registered_handlers)
        if compensation_handlers:
            handlers.update(compensation_handlers)

        all_compensated = True
        has_unavailable = False

        # Compensate completed or uncompensated steps in reverse order
        for step in reversed(saga.steps):
            if step.status in (
                SagaStepStatus.COMPLETED,
                SagaStepStatus.COMPENSATION_FAILED,
                SagaStepStatus.COMPENSATION_UNAVAILABLE,
            ):
                step.status = SagaStepStatus.COMPENSATING
                step.compensation_attempts += 1
                if self.storage and hasattr(self.storage, "save_saga"):
                    self.storage.save_saga(saga)

                handler = handlers.get(step.name)

                attempt_record: dict[str, Any] = {
                    "attempt": step.compensation_attempts,
                    "timestamp": time.time(),
                }

                if handler is None:
                    # Missing handler must NEVER report success
                    step.status = SagaStepStatus.COMPENSATION_UNAVAILABLE
                    step.error_message = (
                        f"Missing compensation handler for step '{step.name}'. "
                        "Manual intervention is required to reconcile this state."
                    )
                    attempt_record["success"] = False
                    attempt_record["error"] = step.error_message
                    step.compensation_history.append(attempt_record)
                    all_compensated = False
                    has_unavailable = True
                    if self.storage and hasattr(self.storage, "save_saga"):
                        self.storage.save_saga(saga)
                    if self.storage and hasattr(self.storage, "record_reconciliation"):
                        self.storage.record_reconciliation(
                            saga_id=saga_id,
                            step_id=step.step_id,
                            reason=f"Missing compensation handler for step '{step.name}'",
                            notes=step.error_message,
                        )
                    continue

                success = False
                error_msg = None
                try:
                    success = handler(step.compensation_payload)
                except Exception as exc:
                    success = False
                    error_msg = str(exc)

                # Post-condition verification if handler reported success
                if success:
                    verifier = self._registered_verifiers.get(step.name)
                    if verifier:
                        try:
                            verified = verifier(step.compensation_payload)
                            if not verified:
                                success = False
                                error_msg = "Compensation post-condition verification failed."
                        except Exception as exc:
                            success = False
                            error_msg = f"Verifier exception: {exc}"

                attempt_record["success"] = success
                if error_msg:
                    attempt_record["error"] = error_msg
                step.compensation_history.append(attempt_record)

                if success:
                    step.status = SagaStepStatus.COMPENSATED
                    step.compensated_at = time.time()
                    step.error_message = None
                else:
                    step.status = SagaStepStatus.COMPENSATION_FAILED
                    step.error_message = error_msg or "Compensation execution returned failure."
                    all_compensated = False
                    if self.storage and hasattr(self.storage, "record_reconciliation"):
                        self.storage.record_reconciliation(
                            saga_id=saga_id,
                            step_id=step.step_id,
                            reason=f"Compensation failure for step '{step.name}'",
                            notes=step.error_message,
                        )

                if self.storage and hasattr(self.storage, "save_saga"):
                    self.storage.save_saga(saga)

        if all_compensated:
            saga.status = SagaStatus.COMPENSATED
        elif has_unavailable:
            saga.status = SagaStatus.MANUAL_INTERVENTION_REQUIRED
        else:
            saga.status = SagaStatus.PARTIAL_FAILURE

        saga.completed_at = time.time()
        if self.storage and hasattr(self.storage, "save_saga"):
            self.storage.save_saga(saga)

        return all_compensated

    def safe_retry(
        self,
        step: SagaStep,
        action_fn: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Attempt retry with non-idempotent protection.

        Rejects blind retry if the step is not explicitly marked as idempotent.
        """
        if not step.is_idempotent:
            raise NonIdempotentBlindRetryError(
                f"Blind retry forbidden: Step '{step.name}' is non-idempotent. Must be reconciled first."
            )
        return action_fn(step.forward_payload)

    def reconcile_step(
        self,
        saga_id: str,
        step_id: str,
        resolved_status: SagaStepStatus,
        notes: str = "",
    ) -> None:
        """Manually or automatically reconcile an unknown outcome step."""
        saga = self.get_saga(saga_id)
        if not saga:
            raise KeyError(f"Saga '{saga_id}' not found.")

        for step in saga.steps:
            if step.step_id == step_id:
                step.status = resolved_status
                if notes:
                    step.error_message = (
                        f"{step.error_message} [Reconciliation Note: {notes}]"
                        if step.error_message
                        else notes
                    )
                # Remove from reconciliation queue
                self._reconciliation_queue = [
                    item for item in self._reconciliation_queue if item.get("step_id") != step_id
                ]
                break

        # Check if all steps resolved
        if not any(
            s.status
            in (
                SagaStepStatus.RECONCILIATION_REQUIRED,
                SagaStepStatus.MANUAL_INTERVENTION_REQUIRED,
                SagaStepStatus.COMPENSATION_UNAVAILABLE,
                SagaStepStatus.COMPENSATION_FAILED,
            )
            for s in saga.steps
        ):
            saga.status = SagaStatus.COMPLETED

        if self.storage and hasattr(self.storage, "save_saga"):
            self.storage.save_saga(saga)

    def manual_resolve(
        self,
        saga_id: str,
        resolved_by: str,
        notes: str = "",
        mark_as: SagaStatus = SagaStatus.COMPENSATED,
    ) -> SagaTransaction:
        """Manually resolve a saga that is blocked in MANUAL_INTERVENTION_REQUIRED."""
        saga = self.get_saga(saga_id)
        if not saga:
            raise KeyError(f"Saga '{saga_id}' not found.")

        saga.status = mark_as
        saga.metadata["manually_resolved_by"] = resolved_by
        saga.metadata["manual_resolution_notes"] = notes
        saga.metadata["manually_resolved_at"] = time.time()
        saga.completed_at = time.time()

        if self.storage and hasattr(self.storage, "save_saga"):
            self.storage.save_saga(saga)

        if (
            self.storage
            and hasattr(self.storage, "list_reconciliations")
            and hasattr(self.storage, "resolve_reconciliation")
        ):
            pending_records = self.storage.list_reconciliations(status="PENDING")
            for rec in pending_records:
                if rec.get("saga_id") == saga_id:
                    rec_id = rec.get("record_id") or rec.get("id")
                    if rec_id is not None:
                        self.storage.resolve_reconciliation(
                            record_id=rec_id,
                            resolved_by=resolved_by,
                            notes=notes,
                        )

        return saga

    def recover_saga(self, saga_id: str) -> SagaTransaction | None:
        """Reload a saga from persistent storage into active memory upon restart."""
        if self.storage and hasattr(self.storage, "get_saga"):
            saga = self.storage.get_saga(saga_id)
            if saga:
                self._sagas[saga_id] = saga
                return saga
        return self._sagas.get(saga_id)
