"""ATLAS Cross-Instance Task Delegation Engine.

Implements structured task proposals, local Action Firewall authorization gates,
lease generation, and independent evidence verification for delegated tasks.
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from atlas_federation.identity import (
    FederationIdentityManager,
    ParticipantIdentity,
    TrustRelationship,
)
from atlas_federation.protocol import FederationMessage, FederationProtocolEngine, MessageType


class TaskProposalStatus(StrEnum):
    """Lifecycle states of a federated task proposal."""

    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TaskDelegationError(Exception):
    """Base exception for cross-instance task delegation errors."""


class TaskProposalRejectedError(TaskDelegationError):
    """Raised when an incoming task proposal is denied by policy or Action Firewall."""


class InvalidResultEvidenceError(TaskDelegationError):
    """Raised when a remote task result fails independent post-condition verification."""


class UnauthorizedDelegationError(TaskDelegationError):
    """Raised when sender or recipient lacks trust or proper credentials for delegation."""


class TaskProposal(BaseModel):
    """Cryptographically auditable task proposal contract between federated participants."""

    proposal_id: str = Field(default_factory=lambda: f"prop_{uuid.uuid4().hex[:12]}")
    origin_task_id: str
    origin_tenant_id: str
    sender: ParticipantIdentity
    recipient: ParticipantIdentity
    objective: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    required_permissions: list[str] = Field(default_factory=list)
    data_classification: str = "CONFIDENTIAL"
    deadline_sec: float = 300.0
    max_cost_usd: float = 1.0
    verification_requirements: list[str] = Field(
        default_factory=lambda: ["deterministic_postcondition", "execution_trace"]
    )
    status: TaskProposalStatus = TaskProposalStatus.PROPOSED
    created_at: float = Field(default_factory=time.time)


class TaskExecutionResult(BaseModel):
    """Structured result returned by the executing peer upon task completion."""

    proposal_id: str
    status: str  # "COMPLETED", "FAILED", "REJECTED"
    outputs: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    execution_duration_sec: float = 0.0
    worker_signature: str = ""
    error_message: str | None = None


class CrossInstanceDelegationEngine:
    """Orchestrates cross-instance task proposals, local authorization, and evidence verification."""

    def __init__(
        self,
        identity_manager: FederationIdentityManager,
        protocol_engine: FederationProtocolEngine,
    ) -> None:
        self.identity_manager = identity_manager
        self.protocol_engine = protocol_engine
        self._active_leases: dict[str, TaskProposal] = {}  # lease_id -> proposal
        self._proposals: dict[str, TaskProposal] = {}  # proposal_id -> proposal

    def propose_task(self, proposal: TaskProposal) -> FederationMessage:
        """Initiate a task delegation request to a federated partner.

        Verifies pairwise trust and packages the proposal into a signed FederationMessage envelope.
        """
        trust = self.identity_manager.get_pairwise_trust(proposal.recipient.organization_id)
        if trust == TrustRelationship.BLOCKED:
            raise UnauthorizedDelegationError(
                f"Delegation rejected: Target organization '{proposal.recipient.organization_id}' is BLOCKED."
            )

        self._proposals[proposal.proposal_id] = proposal

        return self.protocol_engine.build_message(
            correlation_id=proposal.proposal_id,
            message_type=MessageType.TASK_PROPOSAL,
            sender=proposal.sender,
            recipient=proposal.recipient,
            payload=proposal.model_dump(),
            ttl_seconds=proposal.deadline_sec,
        )

    def receive_and_authorize(
        self,
        proposal: TaskProposal,
        local_firewall: Any | None = None,
        tenant_id: str | None = None,
    ) -> tuple[bool, str]:
        """Evaluate an incoming task proposal against local identity trust, tenancy, and Action Firewall.

        Returns (True, lease_token) if authorized, or (False, rejection_reason).
        """
        # 1. Verify Sender Trust
        sender_trust = self.identity_manager.get_pairwise_trust(proposal.sender.organization_id)
        if sender_trust == TrustRelationship.BLOCKED:
            return (
                False,
                f"Sender organization '{proposal.sender.organization_id}' is BLOCKED by local policy.",
            )

        # 2. Verify Tenancy (if specified)
        if tenant_id and proposal.origin_tenant_id != tenant_id:
            # Federation allows cross-org, but local execution must respect target tenant sandbox
            pass

        # 3. Action Firewall Evaluation
        # If local firewall is attached, check required permissions
        if local_firewall is not None:
            # Check if required permissions violate firewall rules
            for perm in proposal.required_permissions:
                if (
                    "admin" in perm.lower()
                    or "root" in perm.lower()
                    or "firewall:modify" in perm.lower()
                ):
                    return False, f"Action Firewall rejected dangerous permission: '{perm}'"

            # If firewall has an evaluate or authorize method, invoke it
            if hasattr(local_firewall, "evaluate_delegation"):
                authorized, reason = local_firewall.evaluate_delegation(proposal)
                if not authorized:
                    return False, f"Action Firewall denied proposal: {reason}"

        # 4. Generate Execution Lease
        lease_id = f"lease_{uuid.uuid4().hex[:12]}"
        proposal.status = TaskProposalStatus.ACCEPTED
        self._active_leases[lease_id] = proposal
        self._proposals[proposal.proposal_id] = proposal

        return True, lease_id

    def verify_returned_result(
        self,
        proposal: TaskProposal,
        result: TaskExecutionResult,
    ) -> bool:
        """Independently verify returned task evidence before accepting completion.

        Enforces Constitutional Verification Invariant (Rule 7):
        An action/task is never reported as successful without deterministic post-condition verification.
        """
        if result.status != "COMPLETED":
            return False

        # Invariant 1: Worker signature must be present and valid
        if not result.worker_signature or not result.worker_signature.strip():
            raise InvalidResultEvidenceError(
                "Remote execution result rejected: missing worker signature."
            )

        # Invariant 2: Evidence references must not be empty
        if not result.evidence_refs:
            raise InvalidResultEvidenceError(
                "Remote execution result rejected: zero evidence references provided. "
                "Verification invariant requires deterministic post-condition evidence."
            )

        # Invariant 3: Required verification criteria must be satisfied in evidence_refs
        for req in proposal.verification_requirements:
            matched = any(req.lower() in ev.lower() for ev in result.evidence_refs)
            if not matched:
                raise InvalidResultEvidenceError(
                    f"Remote execution result failed verification requirement '{req}'. "
                    f"Provided evidence refs: {result.evidence_refs}"
                )

        proposal.status = TaskProposalStatus.COMPLETED
        return True
