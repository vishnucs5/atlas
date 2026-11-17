"""ATLAS Human Workforce and Approval Engine.

Implements cryptographically bound human approval requests, strict separation-of-duties,
parameter tamper resistance, multi-person quorums, and approval lifecycle management.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ApprovalDecision(StrEnum):
    """Decision outcome of a human approval request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ApprovalError(Exception):
    """Base exception for human approval failures."""


class ParameterTamperedError(ApprovalError):
    """Raised when an operation's parameters differ from the approved parameters hash."""


class SeparationOfDutiesViolationError(ApprovalError):
    """Raised when a requesting entity attempts to approve its own sensitive action."""


class UnauthorizedApproverError(ApprovalError):
    """Raised when an entity not listed in authorized approvers attempts a decision."""


class ApprovalExpiredError(ApprovalError):
    """Raised when a decision is attempted on an expired approval request."""


class ApprovalRecord(BaseModel):
    """Single decision record within an approval request (for multi-person approvals)."""

    approver_id: str
    decision: ApprovalDecision
    decided_at: float = Field(default_factory=time.time)
    comments: str = ""


class ApprovalRequest(BaseModel):
    """Cryptographically bound, immutable human approval specification."""

    approval_id: str = Field(default_factory=lambda: f"appr_{uuid.uuid4().hex[:12]}")
    process_instance_id: str
    task_def_id: str
    action_name: str
    target_resource: str
    parameters: dict[str, Any]
    parameter_hash: str = ""
    requesting_identity: str
    tenant_id: str = "tenant_default"
    allowed_approver_roles: list[str] = Field(default_factory=list)
    allowed_approver_ids: list[str] = Field(default_factory=list)
    required_approvals: int = 1
    policy_version: str = "1.0.0"
    risk_classification: str = "HIGH"
    expires_at: float
    status: ApprovalDecision = ApprovalDecision.PENDING
    decisions: list[ApprovalRecord] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    resolved_at: float | None = None

    def compute_parameter_hash(self) -> str:
        """Compute deterministic SHA-256 hash of material parameters."""
        serialized = json.dumps(self.parameters, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class HumanApprovalEngine:
    """Manages human approval requests, enforces separation of duties, and validates parameter integrity."""

    def __init__(self, storage: Any | None = None) -> None:
        self.storage = storage
        self._approvals: dict[str, ApprovalRequest] = {}
        self._lock = threading.RLock()

    def create_approval_request(
        self,
        process_instance_id: str,
        task_def_id: str,
        action_name: str,
        target_resource: str,
        parameters: dict[str, Any],
        requesting_identity: str,
        allowed_approver_ids: list[str],
        allowed_approver_roles: list[str] | None = None,
        duration_seconds: float = 3600.0,
        required_approvals: int = 1,
        risk_classification: str = "HIGH",
        tenant_id: str = "tenant_default",
    ) -> ApprovalRequest:
        """Create and register an immutable approval request with hashed parameters."""
        now = time.time()
        req = ApprovalRequest(
            process_instance_id=process_instance_id,
            task_def_id=task_def_id,
            action_name=action_name,
            target_resource=target_resource,
            parameters=parameters,
            requesting_identity=requesting_identity,
            allowed_approver_ids=allowed_approver_ids,
            allowed_approver_roles=allowed_approver_roles or [],
            required_approvals=required_approvals,
            risk_classification=risk_classification,
            expires_at=now + duration_seconds,
            tenant_id=tenant_id,
        )
        req.parameter_hash = req.compute_parameter_hash()
        with self._lock:
            self._approvals[req.approval_id] = req
            if self.storage and hasattr(self.storage, "save_approval"):
                self.storage.save_approval(req)
        return req

    def decide(
        self,
        approval_id: str,
        approver_id: str,
        decision: ApprovalDecision,
        comments: str = "",
        current_parameters: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Record an approval or rejection decision with thread-safe quorum updates and storage durability."""
        with self._lock:
            # If durable storage provides transactional decision recording, delegate to authoritative database
            if self.storage and hasattr(self.storage, "decide_approval"):
                req = self.storage.decide_approval(
                    approval_id=approval_id,
                    approver_id=approver_id,
                    decision=decision,
                    comments=comments,
                    current_parameters=current_parameters,
                )
                self._approvals[approval_id] = req
                return req

            req = self.get_approval(approval_id)
            if not req:
                raise KeyError(f"Approval request '{approval_id}' not found.")

            now = time.time()

            # 0. Terminal State Lock Invariant
            if req.status != ApprovalDecision.PENDING:
                raise ApprovalError(
                    f"Approval request '{approval_id}' has already been resolved with status '{req.status}' "
                    "and cannot accept further decisions."
                )

            # 1. Check Expiry
            if now > req.expires_at:
                req.status = ApprovalDecision.EXPIRED
                req.resolved_at = now
                if self.storage and hasattr(self.storage, "save_approval"):
                    self.storage.save_approval(req)
                raise ApprovalExpiredError(f"Approval request '{approval_id}' has expired.")

            # 2. Separation of Duties Invariant: Requestor cannot approve own action
            if approver_id == req.requesting_identity:
                raise SeparationOfDutiesViolationError(
                    f"Separation of duties violation: Requestor '{approver_id}' cannot approve its own action."
                )

            # 3. Authorized Approver Check
            if approver_id not in req.allowed_approver_ids:
                raise UnauthorizedApproverError(
                    f"Approver '{approver_id}' is not authorized to decide approval '{approval_id}'."
                )

            # 4. Parameter Tamper Resistance: Ensure parameters haven't mutated
            if current_parameters is not None:
                current_hash = hashlib.sha256(
                    json.dumps(current_parameters, sort_keys=True).encode("utf-8")
                ).hexdigest()
                if current_hash != req.parameter_hash:
                    raise ParameterTamperedError(
                        "Approval rejected: Material parameters have been altered since approval request creation."
                    )

            # 5. Check duplicate approval by same person
            if any(d.approver_id == approver_id for d in req.decisions):
                raise ApprovalError(f"Approver '{approver_id}' has already submitted a decision.")

            # Record decision
            req.decisions.append(
                ApprovalRecord(
                    approver_id=approver_id,
                    decision=decision,
                    decided_at=now,
                    comments=comments,
                )
            )

            if decision == ApprovalDecision.REJECTED:
                # Permanent veto: Single rejection terminates immediately
                req.status = ApprovalDecision.REJECTED
                req.resolved_at = now
            elif decision == ApprovalDecision.APPROVED:
                approved_count = sum(
                    1 for d in req.decisions if d.decision == ApprovalDecision.APPROVED
                )
                if approved_count >= req.required_approvals:
                    req.status = ApprovalDecision.APPROVED
                    req.resolved_at = now

            if self.storage and hasattr(self.storage, "save_approval"):
                self.storage.save_approval(req)

            return req

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        """Retrieve approval request by ID, checking authoritative durable storage first and falling back to local cache."""
        with self._lock:
            if self.storage and hasattr(self.storage, "get_approval"):
                appr = self.storage.get_approval(approval_id)
                if appr:
                    self._approvals[approval_id] = appr
                    return appr
            return self._approvals.get(approval_id)
