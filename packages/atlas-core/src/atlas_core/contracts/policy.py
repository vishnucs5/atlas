"""Policy decision, risk classification, and approval contracts."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PolicyDecisionType(StrEnum):
    """Authorization decision outcome for an action proposal."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class RiskLevel(StrEnum):
    """Risk severity classification for computer actions."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ApprovalStatus(StrEnum):
    """Lifecycle status of a human approval request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PolicyDecision(BaseModel):
    """Outcome of Action Firewall policy evaluation."""

    model_config = ConfigDict(validate_assignment=True)

    decision: PolicyDecisionType
    risk_level: RiskLevel
    reason: str
    rules_evaluated: list[str] = Field(default_factory=list)
    schema_version: str = "1.0"


class ApprovalRequest(BaseModel):
    """Request for interactive human approval of a sensitive/critical action."""

    model_config = ConfigDict(validate_assignment=True)

    approval_id: str
    task_id: str
    action_id: str
    action_hash: str
    risk_level: RiskLevel
    reason: str
    status: str = ApprovalStatus.PENDING.value
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    schema_version: str = "1.0"
