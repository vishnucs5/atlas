"""ATLAS Federated Process Delegation Engine.

Bridges enterprise business processes with the Phase 15 Federation Gateway,
enabling sovereign, cryptographically verified cross-organization task delegation.
"""

from __future__ import annotations

from typing import Any

from atlas_federation.gateway import FederationGateway
from atlas_federation.identity import ParticipantIdentity, TrustRelationship


class FederatedProcessDelegator:
    """Delegates business process steps across sovereign ATLAS federation boundaries."""

    def __init__(self, local_gateway: FederationGateway) -> None:
        self.gateway = local_gateway

    def delegate_business_step(
        self,
        target_org_id: str,
        target_installation_id: str,
        objective: str,
        parameters: dict[str, Any],
        verification_requirements: list[str] | None = None,
        origin_tenant_id: str = "tenant_enterprise_default",
    ) -> str:
        """Propose and delegate a business process step to a federated partner."""
        # 1. Verify pairwise trust
        trust = self.gateway.identity_manager.get_pairwise_trust(target_org_id)
        if trust == TrustRelationship.BLOCKED:
            raise PermissionError(
                f"Delegation rejected: Target organization '{target_org_id}' is BLOCKED."
            )

        recipient = ParticipantIdentity(
            organization_id=target_org_id,
            installation_id=target_installation_id,
        )

        proposal, envelope = self.gateway.delegate_task(
            recipient=recipient,
            objective=objective,
            inputs=parameters,
            verification_requirements=verification_requirements
            or ["deterministic_evidence", "audit_trace"],
            origin_tenant_id=origin_tenant_id,
        )

        return proposal.proposal_id
