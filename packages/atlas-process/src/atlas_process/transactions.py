"""ATLAS Multi-System Transaction Coordination & Compensation Engine.

Implements the Saga distributed transaction pattern with explicit compensation handlers,
idempotency keys, no-blind-retries for non-idempotent operations, and unknown outcome reconciliation.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SagaStepStatus(StrEnum):
    """Lifecycle states of an individual saga transaction step."""

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class SagaStatus(StrEnum):
    """Overall status of a saga transaction."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class SagaError(Exception):
    """Base exception for saga transaction errors."""


class NonIdempotentBlindRetryError(SagaError):
    """Raised when a non-idempotent operation is subjected to an unsafe blind retry."""


class ReconciliationRequiredError(SagaError):
    """Raised when an operation's outcome is unknown (e.g. timeout) and requires reconciliation."""


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


class SagaCoordinator:
    """Coordinates forward execution, reverse compensation, and unknown-outcome reconciliation."""

    def __init__(self) -> None:
        self._sagas: dict[str, SagaTransaction] = {}
        self._reconciliation_queue: list[dict[str, Any]] = []

    def create_saga(self, process_instance_id: str) -> SagaTransaction:
        """Create and register a new saga transaction."""
        saga = SagaTransaction(process_instance_id=process_instance_id)
        self._sagas[saga.saga_id] = saga
        return saga

    def execute_step(
        self,
        saga_id: str,
        step: SagaStep,
        action_fn: Callable[[dict[str, Any]], dict[str, Any]],
        compensation_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a forward step in the saga."""
        saga = self._sagas.get(saga_id)
        if not saga:
            raise KeyError(f"Saga '{saga_id}' not found.")

        saga.steps.append(step)
        step.compensation_payload = compensation_payload or {}

        try:
            result = action_fn(step.forward_payload)
            step.status = SagaStepStatus.COMPLETED
            step.forward_result = result
            step.executed_at = time.time()
            return result
        except TimeoutError as exc:
            # Unknown outcome! If non-idempotent, DO NOT blind retry!
            step.status = SagaStepStatus.RECONCILIATION_REQUIRED
            step.error_message = f"Timeout encountered: {exc}"
            saga.status = SagaStatus.RECONCILIATION_REQUIRED
            self._reconciliation_queue.append(
                {
                    "saga_id": saga_id,
                    "step_id": step.step_id,
                    "idempotency_key": step.idempotency_key,
                    "reason": "Timeout on external call",
                }
            )
            raise ReconciliationRequiredError(
                f"Step '{step.name}' entered RECONCILIATION_REQUIRED: outcome unknown after timeout."
            ) from exc
        except Exception as exc:
            step.status = SagaStepStatus.FAILED
            step.error_message = str(exc)
            saga.status = SagaStatus.COMPENSATING
            # Trigger automatic compensation of preceding steps
            self.compensate_saga(saga_id)
            raise

    def compensate_saga(
        self,
        saga_id: str,
        compensation_handlers: (dict[str, Callable[[dict[str, Any]], bool]] | None) = None,
    ) -> bool:
        """Execute compensation steps in reverse order for all completed steps."""
        saga = self._sagas.get(saga_id)
        if not saga:
            raise KeyError(f"Saga '{saga_id}' not found.")

        saga.status = SagaStatus.COMPENSATING
        handlers = compensation_handlers or {}
        all_compensated = True

        # Compensate completed steps in reverse order
        for step in reversed(saga.steps):
            if step.status == SagaStepStatus.COMPLETED:
                step.status = SagaStepStatus.COMPENSATING
                handler = handlers.get(step.name)
                success = True
                if handler:
                    try:
                        success = handler(step.compensation_payload)
                    except Exception:
                        success = False

                if success:
                    step.status = SagaStepStatus.COMPENSATED
                    step.compensated_at = time.time()
                else:
                    step.status = SagaStepStatus.COMPENSATION_FAILED
                    all_compensated = False

        if all_compensated:
            saga.status = SagaStatus.COMPENSATED
        else:
            saga.status = SagaStatus.PARTIAL_FAILURE

        saga.completed_at = time.time()
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
    ) -> None:
        """Manually or automatically reconcile an unknown outcome step."""
        saga = self._sagas.get(saga_id)
        if not saga:
            raise KeyError(f"Saga '{saga_id}' not found.")

        for step in saga.steps:
            if step.step_id == step_id:
                step.status = resolved_status
                # Remove from reconciliation queue
                self._reconciliation_queue = [
                    item for item in self._reconciliation_queue if item.get("step_id") != step_id
                ]
                break

        # Check if all steps resolved
        if not any(s.status == SagaStepStatus.RECONCILIATION_REQUIRED for s in saga.steps):
            saga.status = SagaStatus.COMPLETED
