"""ATLAS Safety Governor.

Enforces immutable boundaries around core security, authorization, Action Firewall,
tenant isolation, and source code, blocking unauthorized autonomous self-modification.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class SafetyGovernorError(Exception):
    """Base exception for safety governance violations."""


class ProtectedComponentModificationError(SafetyGovernorError):
    """Raised when an optimization candidate attempts to modify an immutable system component."""


class UnauthorizedPromotionError(SafetyGovernorError):
    """Raised when an unapproved or invalid candidate is submitted for production promotion."""


class SelfApprovalProhibitedError(SafetyGovernorError):
    """Raised when an autonomous proposer attempts to approve its own change."""


class RiskLevel(StrEnum):
    """Risk severity classification for proposed changes."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ChangeCategory(StrEnum):
    """Operational domain of a proposed improvement candidate."""

    PARAMETER_TUNING = "PARAMETER_TUNING"
    ROUTING_WEIGHTS = "ROUTING_WEIGHTS"
    PROMPT_TEMPLATE = "PROMPT_TEMPLATE"
    SECURITY_POLICY = "SECURITY_POLICY"
    CODE_MODIFICATION = "CODE_MODIFICATION"
    AUTH_CONTROL = "AUTH_CONTROL"


class ProposedChange(BaseModel):
    """Specification of an optimization or configuration change submitted for review."""

    change_id: str = Field(default_factory=lambda: f"chg_{uuid.uuid4().hex[:10]}")
    proposer_id: str
    category: ChangeCategory
    target_path: str
    description: str
    diff_content: str = ""


class SafetyGovernor:
    """Evaluates proposed changes and enforces non-negotiable security invariants."""

    PROTECTED_PATHS = [
        "packages/atlas-core",
        "packages/atlas-policy",
        "packages/atlas-storage",
        "packages/atlas-enterprise",
        "packages/atlas-browser",
        "deploy/",
        "AGENTS.md",
    ]

    PROTECTED_CATEGORIES = [
        ChangeCategory.SECURITY_POLICY,
        ChangeCategory.CODE_MODIFICATION,
        ChangeCategory.AUTH_CONTROL,
    ]

    @classmethod
    def evaluate_change(cls, change: ProposedChange) -> RiskLevel:
        """Validate proposed change against immutable boundaries and compute its risk score."""
        target_norm = change.target_path.strip().lower()

        # 1. Strictly Forbidden Categories
        if change.category in cls.PROTECTED_CATEGORIES:
            raise ProtectedComponentModificationError(
                f"Proposed change '{change.change_id}' rejected: Category '{change.category.value}' "
                "targets protected security/code boundaries. Autonomous modification is strictly prohibited. "
                "Core code changes require standard engineering process."
            )

        # 2. Protected Path Containment Check
        for p in cls.PROTECTED_PATHS:
            if p.lower() in target_norm:
                raise ProtectedComponentModificationError(
                    f"Proposed change '{change.change_id}' rejected: Target path '{change.target_path}' "
                    f"overlaps with protected component '{p}'. Core code changes require standard engineering process."
                )

        # 3. Assess allowable risk
        if change.category == ChangeCategory.PROMPT_TEMPLATE:
            return RiskLevel.MEDIUM
        if change.category == ChangeCategory.ROUTING_WEIGHTS:
            return RiskLevel.LOW
        if change.category == ChangeCategory.PARAMETER_TUNING:
            return RiskLevel.LOW

        return RiskLevel.HIGH

    @classmethod
    def authorize_promotion(
        cls,
        change: ProposedChange,
        approver_id: str,
    ) -> bool:
        """Authorize promotion of an evaluated change, enforcing separate approval authority."""
        # 1. Evaluate change against immutable boundaries
        risk = cls.evaluate_change(change)

        # 2. Prohibit Self-Approval: Autonomous systems cannot approve their own proposals
        if change.proposer_id.strip().lower() == approver_id.strip().lower():
            raise SelfApprovalProhibitedError(
                f"Self-approval rejected for change '{change.change_id}'! Proposer '{change.proposer_id}' "
                "cannot act as approver. Independent human or system authorization is required."
            )

        return risk in (RiskLevel.LOW, RiskLevel.MEDIUM)
