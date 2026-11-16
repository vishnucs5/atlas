"""ATLAS Federation Gateway.

Unified node gateway orchestrating identity, capability discovery, secure messaging,
task delegation, external adapters, network resilience, and telemetry for an ATLAS installation.
"""

from __future__ import annotations

import time
from typing import Any

from atlas_federation.delegation import (
    CrossInstanceDelegationEngine,
    TaskExecutionResult,
    TaskProposal,
)
from atlas_federation.discovery import (
    CapabilityAdvertisement,
    FederatedCapabilityRegistry,
    VisibilityScope,
)
from atlas_federation.external_adapters import MCPAdapter, WebhookAdapter
from atlas_federation.identity import (
    FederationCredentials,
    FederationIdentityManager,
    ParticipantIdentity,
    TrustRelationship,
)
from atlas_federation.observability import (
    FederationTelemetryCollector,
)
from atlas_federation.protocol import (
    FederationMessage,
    FederationProtocolEngine,
    MessageType,
)
from atlas_federation.reputation import FederationReputationTracker
from atlas_federation.resilience import ResilientOutbox
from atlas_federation.security import (
    FederationSecurityGovernor,
    PeerSecurityPolicy,
)
from atlas_federation.workflow_exchange import FederatedWorkflowExchange


class FederationGateway:
    """Sovereign gateway representing an ATLAS installation within the global federation network."""

    def __init__(
        self,
        organization_id: str,
        installation_id: str,
        webhook_secret: str = "wh_secret_federation_gateway_default",
        capability_registry: FederatedCapabilityRegistry | None = None,
    ) -> None:
        self.identity = ParticipantIdentity(
            organization_id=organization_id, installation_id=installation_id
        )
        self.identity_manager = FederationIdentityManager()
        self.capability_registry = capability_registry or FederatedCapabilityRegistry()
        self.protocol_engine = FederationProtocolEngine()
        self.reputation_tracker = FederationReputationTracker()
        self.security_governor = FederationSecurityGovernor(
            reputation_tracker=self.reputation_tracker
        )
        self.delegation_engine = CrossInstanceDelegationEngine(
            identity_manager=self.identity_manager,
            protocol_engine=self.protocol_engine,
        )
        self.resilient_outbox = ResilientOutbox()
        self.telemetry = FederationTelemetryCollector()
        self.workflow_exchange = FederatedWorkflowExchange()
        self.mcp_adapter = MCPAdapter(
            organization_id=organization_id, installation_id=installation_id
        )
        self.webhook_adapter = WebhookAdapter(
            secret_key=webhook_secret,
            organization_id=organization_id,
            installation_id=installation_id,
        )

        # Issue self credentials
        self.credentials = self.identity_manager.issue_credentials(
            organization_id=organization_id,
            installation_id=installation_id,
        )

    def enroll_peer(
        self,
        organization_id: str,
        trust_level: TrustRelationship = TrustRelationship.TRUSTED,
        peer_policy: PeerSecurityPolicy | None = None,
    ) -> FederationCredentials:
        """Enroll a partner organization into this gateway's trust domain."""
        self.identity_manager.set_pairwise_trust(organization_id, trust_level)
        if peer_policy:
            self.security_governor.set_peer_policy(organization_id, peer_policy)

        # Generate credentials for the peer
        return self.identity_manager.issue_credentials(
            organization_id=organization_id,
            installation_id=f"inst_{organization_id[:8]}",
        )

    def revoke_peer_trust(self, organization_id: str) -> None:
        """Sever trust relationship with a peer organization, immediately blocking incoming interactions."""
        self.identity_manager.set_pairwise_trust(organization_id, TrustRelationship.BLOCKED)

    def advertise_agent(
        self,
        agent_id: str,
        task_categories: list[str],
        modalities: list[str] | None = None,
        skills: list[str] | None = None,
        visibility: VisibilityScope = VisibilityScope.FEDERATION,
    ) -> CapabilityAdvertisement:
        """Register and advertise local agent capabilities into the capability registry."""
        ad = CapabilityAdvertisement(
            organization_id=self.identity.organization_id,
            installation_id=self.identity.installation_id,
            agent_id=agent_id,
            supported_task_categories=task_categories,
            supported_modalities=modalities or ["text"],
            available_skills=skills or [],
            visibility=visibility,
        )
        return self.capability_registry.register_advertisement(ad)

    def sync_capabilities(self, source_registry: FederatedCapabilityRegistry) -> None:
        """Synchronize discoverable capabilities from a peer or federation registry."""
        for ad in source_registry._advertisements.values():
            self.capability_registry.register_advertisement(ad)

    def discover(
        self,
        target_org_id: str | None = None,
        category: str | None = None,
        modality: str | None = None,
    ) -> list[CapabilityAdvertisement]:
        """Query discoverable capabilities respecting visibility scoping."""
        return self.capability_registry.query_capabilities(
            requesting_org_id=self.identity.organization_id,
            target_org_id=target_org_id,
            category=category,
            modality=modality,
        )

    def send_message(
        self,
        recipient: ParticipantIdentity,
        message_type: MessageType,
        payload: dict[str, Any],
        correlation_id: str | None = None,
        ttl_seconds: float = 60.0,
    ) -> FederationMessage:
        """Build and queue a signed message for transmission."""
        corr = correlation_id or f"corr_{int(time.time() * 1000)}"
        msg = self.protocol_engine.build_message(
            correlation_id=corr,
            message_type=message_type,
            sender=self.identity,
            recipient=recipient,
            payload=payload,
            ttl_seconds=ttl_seconds,
        )
        self.resilient_outbox.enqueue(msg)
        return msg

    def handle_incoming_message(
        self,
        msg: FederationMessage,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Verify, authenticate, unpack, and process an incoming message envelope."""
        # 1. Unpack & Verify envelope
        payload = self.protocol_engine.verify_and_unpack(msg, now=now)

        # 2. Check pairwise trust
        trust = self.identity_manager.get_pairwise_trust(msg.sender.organization_id)
        if trust == TrustRelationship.BLOCKED:
            raise PermissionError(
                f"Rejected: Peer organization '{msg.sender.organization_id}' is BLOCKED."
            )

        return payload

    def delegate_task(
        self,
        recipient: ParticipantIdentity,
        objective: str,
        inputs: dict[str, Any],
        required_permissions: list[str] | None = None,
        verification_requirements: list[str] | None = None,
        origin_tenant_id: str = "tenant_local_default",
    ) -> tuple[TaskProposal, FederationMessage]:
        """Create and propose a delegated task to a remote peer."""
        proposal = TaskProposal(
            origin_task_id=f"task_{int(time.time() * 1000)}",
            origin_tenant_id=origin_tenant_id,
            sender=self.identity,
            recipient=recipient,
            objective=objective,
            inputs=inputs,
            required_permissions=required_permissions or [],
            verification_requirements=verification_requirements
            or ["deterministic_postcondition", "execution_trace"],
        )
        envelope = self.delegation_engine.propose_task(proposal)
        self.resilient_outbox.enqueue(envelope)
        return proposal, envelope

    def receive_and_authorize_task(
        self,
        proposal: TaskProposal,
        target_tenant_id: str = "tenant_local_default",
        local_firewall: Any | None = None,
    ) -> tuple[bool, str]:
        """Authorize an incoming task proposal against security policies and the local Action Firewall."""
        # 1. Security Governor validation
        self.security_governor.check_incoming_request(
            sender_org_id=proposal.sender.organization_id,
            target_tenant_id=target_tenant_id,
            origin_tenant_id=proposal.origin_tenant_id,
            requested_actions=proposal.required_permissions,
        )

        # 2. Delegation Engine authorization & lease generation
        return self.delegation_engine.receive_and_authorize(
            proposal=proposal,
            local_firewall=local_firewall,
            tenant_id=target_tenant_id,
        )

    def verify_remote_result(
        self,
        proposal: TaskProposal,
        result: TaskExecutionResult,
    ) -> bool:
        """Verify returned task result and update advisory reputation tracker."""
        try:
            valid = self.delegation_engine.verify_returned_result(proposal, result)
            if valid:
                self.reputation_tracker.record_success(proposal.recipient.organization_id)
            return valid
        except Exception:
            self.reputation_tracker.record_verification_failure(proposal.recipient.organization_id)
            raise
