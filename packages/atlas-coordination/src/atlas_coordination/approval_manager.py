"""ApprovalManager for human-in-the-loop task action authorizations."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from atlas_core.contracts.action import ComputerAction
from pydantic import BaseModel, ConfigDict, Field

from atlas_coordination.checkpoint_manager import redact_secrets


class ApprovalStatus(StrEnum):
    """Lifecycle status of a human approval request."""

    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class ApprovalSecurityError(Exception):
    """Raised when an approval validation fails due to parameter tampering, replay, expiration, or mismatch."""


class ApprovalRequest(BaseModel):
    """Formal human authorization request record for elevated/high-risk actions.

    Structurally and cryptographically bound to exact action parameters, policy version,
    and task identity to prevent replay, parameter tampering, and cross-task reuse.
    """

    model_config = ConfigDict(validate_assignment=True)

    request_id: str
    task_id: str
    action_id: str
    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    parameter_hash: str = ""
    action_signature: str = ""
    reason: str
    risk_level: str
    policy_rule: str | None = None
    policy_version: str = "1.0"
    status: ApprovalStatus = ApprovalStatus.PENDING
    operator_id: str | None = None
    decision_reason: str | None = None
    created_at: datetime
    decided_at: datetime | None = None
    expires_at: datetime
    consumed: bool = False
    consumed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def compute_parameter_hash(parameters: dict[str, Any] | None) -> str:
    """Compute deterministic SHA-256 hash of canonical action parameters."""
    clean_params = redact_secrets(parameters or {})
    canonical = json.dumps(clean_params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_action_signature(
    task_id: str,
    action_id: str,
    action_type: str,
    parameter_hash: str,
    risk_level: str,
    policy_version: str = "1.0",
) -> str:
    """Compute cryptographic SHA-256 seal binding action identity, parameters, and policy."""
    raw = f"{task_id}:{action_id}:{action_type.lower()}:{parameter_hash}:{risk_level.upper()}:{policy_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ApprovalManager:
    """Manages creation, resolution, verification, and consumption of human approval requests.

    In accordance with Constitution Rule 2 (Action Firewall):
    High-risk actions require operator authorization before driver execution.
    Approvals are bound to exact parameters and policy version, preventing:
    - Parameter tampering after approval
    - Approval reuse or replay
    - Approval after expiration
    - Cross-task approval hijacking
    - Approval under drifted policy rules
    """

    def __init__(self, default_ttl_seconds: int = 300) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._requests: dict[str, ApprovalRequest] = {}

    def create_request(
        self,
        task_id: str,
        action_id: str,
        action_type: str,
        parameters: dict[str, Any] | None = None,
        reason: str = "High risk action requires human authorization",
        risk_level: str = "HIGH",
        policy_rule: str | None = None,
        policy_version: str = "1.0",
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Create and store a pending approval request with cryptographic parameter binding."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        now = datetime.now(UTC)
        req_id = f"appr_{uuid.uuid4().hex[:10]}"

        param_hash = compute_parameter_hash(parameters)
        sig = compute_action_signature(
            task_id=task_id,
            action_id=action_id,
            action_type=action_type,
            parameter_hash=param_hash,
            risk_level=risk_level,
            policy_version=policy_version,
        )

        request = ApprovalRequest(
            request_id=req_id,
            task_id=task_id,
            action_id=action_id,
            action_type=action_type,
            parameters=parameters or {},
            parameter_hash=param_hash,
            action_signature=sig,
            reason=reason,
            risk_level=risk_level,
            policy_rule=policy_rule,
            policy_version=policy_version,
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
            consumed=False,
            metadata=metadata or {},
        )
        self._requests[req_id] = request
        return request

    def restore_request(self, raw_request: ApprovalRequest | dict[str, Any]) -> ApprovalRequest:
        """Restore a persisted approval only if its cryptographic bindings still match."""
        request = (
            raw_request
            if isinstance(raw_request, ApprovalRequest)
            else ApprovalRequest.model_validate(raw_request)
        )
        parameter_hash = compute_parameter_hash(request.parameters)
        if parameter_hash != request.parameter_hash:
            raise ApprovalSecurityError(
                f"Persisted approval '{request.request_id}' has an invalid parameter hash."
            )
        signature = compute_action_signature(
            task_id=request.task_id,
            action_id=request.action_id,
            action_type=request.action_type,
            parameter_hash=request.parameter_hash,
            risk_level=request.risk_level,
            policy_version=request.policy_version,
        )
        if signature != request.action_signature:
            raise ApprovalSecurityError(
                f"Persisted approval '{request.request_id}' has an invalid action signature."
            )
        existing = self._requests.get(request.request_id)
        if existing and existing != request:
            raise ApprovalSecurityError(
                f"Approval request ID collision for '{request.request_id}'."
            )
        self._requests[request.request_id] = request
        return request

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Fetch request by ID, evaluating expiration if still pending."""
        req = self._requests.get(request_id)
        if not req:
            return None
        if req.status == ApprovalStatus.PENDING and datetime.now(UTC) > req.expires_at:
            req.status = ApprovalStatus.EXPIRED
        return req

    def list_requests(
        self,
        task_id: str | None = None,
        status: ApprovalStatus | None = None,
    ) -> list[ApprovalRequest]:
        """List approval requests optionally filtered by task_id and status."""
        self.check_expirations()
        results: list[ApprovalRequest] = []
        for req in self._requests.values():
            if task_id and req.task_id != task_id:
                continue
            if status and req.status != status:
                continue
            results.append(req)
        # Order by created_at desc
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results

    def grant(
        self,
        request_id: str,
        operator_id: str,
        reason: str | None = None,
    ) -> ApprovalRequest:
        """Grant authorization for a pending approval request."""
        req = self._requests.get(request_id)
        if not req:
            raise KeyError(f"Approval request '{request_id}' not found.")

        now = datetime.now(UTC)
        if req.status == ApprovalStatus.EXPIRED or (
            req.status == ApprovalStatus.PENDING and now > req.expires_at
        ):
            req.status = ApprovalStatus.EXPIRED
            raise ValueError(f"Approval request '{request_id}' has already expired.")

        if req.status != ApprovalStatus.PENDING:
            raise ValueError(
                f"Cannot grant request '{request_id}' in terminal state '{req.status.value}'."
            )

        req.status = ApprovalStatus.GRANTED
        req.operator_id = operator_id
        req.decision_reason = reason or "Operator granted approval"
        req.decided_at = now
        return req

    def deny(
        self,
        request_id: str,
        operator_id: str,
        reason: str | None = None,
    ) -> ApprovalRequest:
        """Deny authorization for a pending approval request."""
        req = self._requests.get(request_id)
        if not req:
            raise KeyError(f"Approval request '{request_id}' not found.")

        now = datetime.now(UTC)
        if req.status == ApprovalStatus.EXPIRED or (
            req.status == ApprovalStatus.PENDING and now > req.expires_at
        ):
            req.status = ApprovalStatus.EXPIRED
            raise ValueError(f"Approval request '{request_id}' has already expired.")

        if req.status != ApprovalStatus.PENDING:
            raise ValueError(
                f"Cannot deny request '{request_id}' in terminal state '{req.status.value}'."
            )

        req.status = ApprovalStatus.DENIED
        req.operator_id = operator_id
        req.decision_reason = reason or "Operator denied approval"
        req.decided_at = now
        return req

    def validate_action(
        self,
        request_id: str,
        action: ComputerAction,
        policy_version: str = "1.0",
    ) -> bool:
        """Deterministically verify that an action matches its granted approval without tampering."""
        req = self.get_request(request_id)
        if not req:
            raise ApprovalSecurityError(f"Approval request '{request_id}' not found.")

        if req.status != ApprovalStatus.GRANTED:
            raise ApprovalSecurityError(
                f"Action '{action.action_id}' requires GRANTED approval, but request '{request_id}' is '{req.status.value}'."
            )

        if req.consumed:
            raise ApprovalSecurityError(
                f"Approval request '{request_id}' has already been consumed and cannot be replayed."
            )

        if datetime.now(UTC) > req.expires_at:
            req.status = ApprovalStatus.EXPIRED
            raise ApprovalSecurityError(
                f"Approval request '{request_id}' expired at {req.expires_at.isoformat()}."
            )

        if action.task_id != req.task_id:
            raise ApprovalSecurityError(
                f"Task ID mismatch: action '{action.task_id}' does not match approval '{req.task_id}'."
            )

        if action.action_id != req.action_id:
            raise ApprovalSecurityError(
                f"Action ID mismatch: action '{action.action_id}' does not match approval '{req.action_id}'."
            )

        if action.action_type.lower() != req.action_type.lower():
            raise ApprovalSecurityError(
                f"Action type mismatch: action '{action.action_type}' does not match approved '{req.action_type}'."
            )

        # Verify exact parameters
        current_param_hash = compute_parameter_hash(action.parameters)
        if current_param_hash != req.parameter_hash:
            raise ApprovalSecurityError(
                f"Parameter tampering detected for action '{action.action_id}': parameters have changed since approval was granted."
            )

        if req.policy_version != policy_version:
            raise ApprovalSecurityError(
                f"Policy version mismatch: approved under version '{req.policy_version}', current version is '{policy_version}'."
            )

        return True

    def mark_consumed(self, request_id: str) -> None:
        """Mark an approval request as consumed to prevent replay attacks."""
        req = self._requests.get(request_id)
        if not req:
            raise KeyError(f"Approval request '{request_id}' not found.")
        req.consumed = True
        req.consumed_at = datetime.now(UTC)

    def check_expirations(self) -> list[ApprovalRequest]:
        """Check and transition all overdue pending requests to EXPIRED."""
        now = datetime.now(UTC)
        newly_expired: list[ApprovalRequest] = []
        for req in self._requests.values():
            if req.status == ApprovalStatus.PENDING and now > req.expires_at:
                req.status = ApprovalStatus.EXPIRED
                newly_expired.append(req)
        return newly_expired
