"""Durable Task Idempotency and Irreversible Operation Safety System.

Provides database-backed idempotency tracking, operation fingerprinting, ambiguous outcome
detection, and reconciliation requirements for financial and critical business workflows.
"""

from __future__ import annotations

import hashlib
import json
import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class OperationStatus(StrEnum):
    """Lifecycle state machine for durable task operations."""

    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    CANCELLED = "CANCELLED"


class IdempotencyError(Exception):
    """Base exception for durable task idempotency violations."""


class SagaError(Exception):
    """Base exception for saga transaction errors."""


class ConcurrentOperationInProgressError(IdempotencyError):
    """Raised when an operation with the same idempotency key is already in progress."""


class IdempotencyKeyReuseError(IdempotencyError):
    """Raised when an idempotency key is reused with differing request payloads/parameters."""


class OperationPreviouslyFailedError(IdempotencyError):
    """Raised when an operation previously failed with a final non-retryable error."""


class ReconciliationRequiredError(IdempotencyError, SagaError):
    """Raised when an operation outcome is unknown and requires reconciliation before retry."""


class TaskOperationRecord(BaseModel):
    """Durable record of a task operation execution attempt."""

    tenant_id: str
    idempotency_key: str
    process_instance_id: str
    task_def_id: str
    operation_name: str
    request_fingerprint: str
    status: OperationStatus = OperationStatus.CREATED
    provider_idempotency_key: str | None = None
    provider_name: str | None = None
    request_payload: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    completed_at: float | None = None
    expires_at: float | None = None


def compute_request_fingerprint(payload: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 fingerprint for operation parameters."""
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class DurableOperationIdempotencyManager:
    """Manages durable operation idempotency across distributed workers and engine restarts."""

    def __init__(self, storage: Any) -> None:
        self.storage = storage

    def start_operation(
        self,
        tenant_id: str,
        idempotency_key: str,
        process_instance_id: str,
        task_def_id: str,
        operation_name: str,
        request_payload: dict[str, Any],
        provider_idempotency_key: str | None = None,
        provider_name: str | None = None,
        expires_at: float | None = None,
    ) -> tuple[OperationStatus, dict[str, Any] | None]:
        """Atomically initiate an operation, returning existing cached result if already completed."""
        fingerprint = compute_request_fingerprint(request_payload)
        return self.storage.start_operation(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            process_instance_id=process_instance_id,
            task_def_id=task_def_id,
            operation_name=operation_name,
            request_fingerprint=fingerprint,
            request_payload=request_payload,
            provider_idempotency_key=provider_idempotency_key,
            provider_name=provider_name,
            expires_at=expires_at,
        )

    def complete_operation(
        self,
        tenant_id: str,
        idempotency_key: str,
        response_payload: dict[str, Any],
    ) -> None:
        """Mark an operation successfully completed with response payload."""
        self.storage.complete_operation(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            response_payload=response_payload,
        )

    def fail_operation(
        self,
        tenant_id: str,
        idempotency_key: str,
        error_message: str,
        retryable: bool = False,
    ) -> None:
        """Mark an operation failed, specifying whether retry is permitted."""
        self.storage.fail_operation(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            error_message=error_message,
            retryable=retryable,
        )

    def mark_unknown_outcome(
        self,
        tenant_id: str,
        idempotency_key: str,
        reason: str,
    ) -> None:
        """Mark an operation as UNKNOWN_OUTCOME requiring reconciliation before retry."""
        self.storage.mark_operation_unknown_outcome(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            reason=reason,
        )

    def reconcile_operation(
        self,
        tenant_id: str,
        idempotency_key: str,
        resolution_status: OperationStatus,
        resolved_by: str,
        notes: str = "",
        response_payload: dict[str, Any] | None = None,
    ) -> None:
        """Reconcile an ambiguous operation outcome."""
        self.storage.reconcile_operation(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            resolution_status=resolution_status,
            resolved_by=resolved_by,
            notes=notes,
            response_payload=response_payload,
        )
