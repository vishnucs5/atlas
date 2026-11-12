"""ApprovalManager for human-in-the-loop task action authorizations."""

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApprovalStatus(StrEnum):
    """Lifecycle status of a human approval request."""

    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class ApprovalRequest(BaseModel):
    """Formal human authorization request record for elevated/high-risk actions."""

    model_config = ConfigDict(validate_assignment=True)

    request_id: str
    task_id: str
    action_id: str
    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str
    risk_level: str
    policy_rule: str | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    operator_id: str | None = None
    decision_reason: str | None = None
    created_at: datetime
    decided_at: datetime | None = None
    expires_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalManager:
    """Manages creation, resolution, and expiration of human approval requests.

    In accordance with Constitution Rule 2 (Action Firewall):
    High-risk actions require operator authorization before driver execution.
    Tasks pause in WAITING_APPROVAL until this manager records a GRANT or DENY decision.
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
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Create and store a pending approval request."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        now = datetime.now(UTC)
        req_id = f"appr_{uuid.uuid4().hex[:10]}"

        request = ApprovalRequest(
            request_id=req_id,
            task_id=task_id,
            action_id=action_id,
            action_type=action_type,
            parameters=parameters or {},
            reason=reason,
            risk_level=risk_level,
            policy_rule=policy_rule,
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
            metadata=metadata or {},
        )
        self._requests[req_id] = request
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

    def check_expirations(self) -> list[ApprovalRequest]:
        """Check and transition all overdue pending requests to EXPIRED."""
        now = datetime.now(UTC)
        newly_expired: list[ApprovalRequest] = []
        for req in self._requests.values():
            if req.status == ApprovalStatus.PENDING and now > req.expires_at:
                req.status = ApprovalStatus.EXPIRED
                newly_expired.append(req)
        return newly_expired
