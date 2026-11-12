"""Recovery classification, strategy, and environment reconciliation contracts."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FailureClassification(StrEnum):
    """Categorized failure types triggering the recovery engine."""

    WORKER_CRASH = "WORKER_CRASH"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    NETWORK_DISCONNECTION = "NETWORK_DISCONNECTION"
    BROWSER_DISCONNECTION = "BROWSER_DISCONNECTION"
    UNKNOWN_ACTION_OUTCOME = "UNKNOWN_ACTION_OUTCOME"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    CORRUPTED_CHECKPOINT = "CORRUPTED_CHECKPOINT"
    API_RESTART = "API_RESTART"


class RecoveryStrategy(StrEnum):
    """Selected strategy for recovering an interrupted or degraded task."""

    RETRY_ACTION = "RETRY_ACTION"
    RECONCILE_ENVIRONMENT = "RECONCILE_ENVIRONMENT"
    RESUME_FROM_CHECKPOINT = "RESUME_FROM_CHECKPOINT"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    FAIL_TASK = "FAIL_TASK"


class ReconciliationDecision(StrEnum):
    """Outcome decision resulting from live physical environment reconciliation."""

    RESUME = "RESUME"
    RESTART_STEP = "RESTART_STEP"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    ABORT = "ABORT"


class ReconciliationResult(BaseModel):
    """Result of comparing actual live physical environment state against checkpoint expectations."""

    model_config = ConfigDict(validate_assignment=True)

    matches_expected: bool
    observed_url: str | None = None
    observed_title: str | None = None
    pending_action_handled: bool = False
    decision: ReconciliationDecision = ReconciliationDecision.RESUME
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = "1.0"
