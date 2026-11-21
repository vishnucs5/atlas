"""Data contracts for Human-AI Collaboration, Governance & Explainability."""

from __future__ import annotations

import hashlib
import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceRole(StrEnum):
    """Roles for participants in a collaborative workspace."""

    OWNER = "OWNER"
    EDITOR = "EDITOR"
    REVIEWER = "REVIEWER"
    AUTONOMOUS_WORKER = "AUTONOMOUS_WORKER"


class Collaborator(BaseModel):
    """Participant in a collaborative session."""

    identity: str
    role: WorkspaceRole
    joined_at: float = Field(default_factory=time.time)
    is_human: bool = True


class TurnLease(BaseModel):
    """Server-authoritative semantic turn-locking lease."""

    lease_id: str
    workspace_id: str = ""
    holder_identity: str
    holder_role: WorkspaceRole = WorkspaceRole.EDITOR
    acquired_at: float = Field(default_factory=time.time)
    expires_at: float
    fencing_token: int
    is_human: bool = False
    preempted: bool = False

    @property
    def is_active(self) -> bool:
        return not self.preempted and time.time() <= self.expires_at

    def is_expired(self, at_time: float | None = None) -> bool:
        t = at_time or time.time()
        return self.preempted or t > self.expires_at


class CASArtifactRef(BaseModel):
    """Content-addressable reference to a bulk lineage artifact."""

    uri: str  # Format: "atlas-cas://<sha256>"
    sha256_hash: str
    size_bytes: int
    content_type: str = "application/json"
    encryption_algorithm: str = "AES-256-GCM"


class DecisionFactor(BaseModel):
    """Atomic evidence or policy item used by an agent to justify an action."""

    factor_id: str
    factor_type: str  # DOCUMENT, POLICY_RULE, USER_DIRECTIVE, HISTORICAL_OUTCOME
    source_reference: str
    confidence_weight: float = Field(ge=0.0, le=1.0)
    description: str

    def compute_hash(self) -> str:
        data = f"{self.factor_id}:{self.factor_type}:{self.source_reference}:{self.confidence_weight:.4f}:{self.description}"
        return hashlib.sha256(data.encode("utf-8")).hexdigest()


class AgentDecisionLineage(BaseModel):
    """Causal, auditable record explaining why an autonomous action was selected."""

    decision_id: str
    tenant_id: str
    agent_id: str
    task_instance_id: str
    selected_action: str
    rationale: str
    factors: list[DecisionFactor] = Field(default_factory=list)
    policy_checks_passed: list[str] = Field(default_factory=list)
    merkle_root_hash: str = ""
    cas_ref: CASArtifactRef | None = None
    cas_artifact_uri: str | None = None
    timestamp: float = Field(default_factory=time.time)

    def calculate_merkle_root(self) -> str:
        if not self.factors:
            base = f"{self.decision_id}:{self.selected_action}:{self.rationale}"
            return hashlib.sha256(base.encode("utf-8")).hexdigest()

        leaf_hashes = [f.compute_hash() for f in self.factors]
        current_level = leaf_hashes
        while len(current_level) > 1:
            next_level = []
            for i in range(0, len(current_level), 2):
                if i + 1 < len(current_level):
                    combined = current_level[i] + current_level[i + 1]
                else:
                    combined = current_level[i] + current_level[i]
                next_level.append(hashlib.sha256(combined.encode("utf-8")).hexdigest())
            current_level = next_level
        return current_level[0]


class DelegationEnvelope(BaseModel):
    """Time-bounded, capability-restricted authority delegation."""

    delegation_id: str
    tenant_id: str
    grantor_id: str
    delegatee_id: str
    scope: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    valid_from: float
    valid_until: float
    signature: str = ""
    revoked: bool = False

    def is_active(self, at_time: float | None = None) -> bool:
        t = at_time or time.time()
        return not self.revoked and (self.valid_from <= t <= self.valid_until)

    def compute_signature(self, secret: str = "atlas-secret") -> str:
        canonical = f"{self.delegation_id}:{self.tenant_id}:{self.grantor_id}:{self.delegatee_id}:{self.scope}:{self.valid_from}:{self.valid_until}"
        return hashlib.sha256((canonical + secret).encode("utf-8")).hexdigest()


class SteeringEvent(BaseModel):
    """Immutable audit record of a human intervention on a paused workflow."""

    steering_id: str
    workspace_id: str = ""
    process_instance_id: str = ""
    task_instance_id: str = ""
    operator_id: str
    parent_operation_key: str
    child_operation_key: str
    original_parameters: dict[str, Any]
    modified_parameters: dict[str, Any]
    reason: str
    timestamp: float = Field(default_factory=time.time)


class CollaborativeSession(BaseModel):
    """Collaborative workspace state synchronized across humans and agents."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    tenant_id: str
    workspace_name: str
    status: str = "ACTIVE"
    collaborators: dict[str, Collaborator] = Field(default_factory=dict)
    active_turn_lease: TurnLease | None = None
    sequence_id: int = 0
    artifacts: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class ComplianceBundle(BaseModel):
    """Verifiable compliance evidence package."""

    bundle_id: str
    tenant_id: str
    workspace_id: str = ""
    framework: str = "SOC2"  # SOC2, HIPAA, ISO27001, EU_AI_ACT
    frameworks: list[str] = Field(default_factory=list)
    root_merkle_hash: str = ""
    decision_merkle_root: str = ""
    generated_at: float = Field(default_factory=time.time)
    record_count: int = 0
    total_decisions: int = 0
    signature: str = ""
    hmac_signature: str = ""
    records: list[dict[str, Any]] = Field(default_factory=list)
