"""Causal Decision Lineage & Explainability Tracer."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from atlas_collaboration.models import (
    AgentDecisionLineage,
    CASArtifactRef,
    DecisionFactor,
)


class CausalDecisionTracer:
    """Records and verifies causal reasoning chains and Merkle-hashed decision lineage."""

    def __init__(self) -> None:
        self._decisions: dict[str, AgentDecisionLineage] = {}
        self._cas_storage: dict[str, bytes] = {}

    def record_decision(
        self,
        tenant_id: str,
        agent_id: str,
        task_instance_id: str,
        selected_action: str,
        rationale: str,
        factors: list[DecisionFactor],
        policy_checks_passed: list[str] | None = None,
        context_payload: dict[str, Any] | None = None,
    ) -> AgentDecisionLineage:
        decision_id = f"dec_{uuid.uuid4().hex[:12]}"

        # Create lineage object
        lineage = AgentDecisionLineage(
            decision_id=decision_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            task_instance_id=task_instance_id,
            selected_action=selected_action,
            rationale=rationale,
            factors=factors,
            policy_checks_passed=policy_checks_passed or [],
        )
        lineage.merkle_root_hash = lineage.calculate_merkle_root()

        # Tier 2: Content-Addressable Storage (CAS) for rich context
        if context_payload:
            raw_bytes = json.dumps(context_payload, sort_keys=True).encode("utf-8")
            sha256 = hashlib.sha256(raw_bytes).hexdigest()
            uri = f"atlas-cas://{sha256}"
            self._cas_storage[uri] = raw_bytes
            lineage.cas_ref = CASArtifactRef(
                uri=uri,
                sha256_hash=sha256,
                size_bytes=len(raw_bytes),
            )

        self._decisions[decision_id] = lineage
        return lineage

    def get_decision(self, decision_id: str) -> AgentDecisionLineage | None:
        return self._decisions.get(decision_id)

    def verify_integrity(self, decision_id: str) -> bool:
        """Deterministically verify that recorded Merkle root matches computed factor hashes."""
        lineage = self._decisions.get(decision_id)
        if not lineage:
            return False

        computed = lineage.calculate_merkle_root()
        matches_merkle = computed == lineage.merkle_root_hash

        # Verify CAS payload if attached
        if lineage.cas_ref:
            stored_bytes = self._cas_storage.get(lineage.cas_ref.uri)
            if not stored_bytes:
                return False
            actual_hash = hashlib.sha256(stored_bytes).hexdigest()
            if actual_hash != lineage.cas_ref.sha256_hash:
                return False

        return matches_merkle

    def get_task_causal_chain(self, task_instance_id: str) -> list[AgentDecisionLineage]:
        """Return the complete causal lineage of decisions for a specific task instance."""
        chain = [d for d in self._decisions.values() if d.task_instance_id == task_instance_id]
        chain.sort(key=lambda d: d.timestamp)
        return chain
