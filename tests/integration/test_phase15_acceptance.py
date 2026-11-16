"""Comprehensive Phase 15 Acceptance Suite: Federated Autonomous Intelligence Network.

Verifies acceptance scenarios FED-01 through FED-30:
- Cryptographic Identity, Rotation, and Revocation (FED-01 - FED-05)
- Capability Registry, Visibility Scopes, and Discovery (FED-06 - FED-09)
- Versioned Messaging Protocol, Replay Guard, and Deduplication (FED-10 - FED-13)
- Cross-Instance Task Delegation, Firewall Gate, and Evidence Verification (FED-14 - FED-19)
- Multi-Tenant Isolation, Artifact Security, and Participant Isolation (FED-20 - FED-22)
- Federated Workflow & Skill Package Provenance (FED-23)
- Network Resilience, Outbox Buffering, and Outcome Reconciliation (FED-24 - FED-26)
- Federation Revocation and External Interoperability (FED-27 - FED-28)
- End-to-End Multi-Agent Distributed Collaboration (FED-29)
- Monorepo Core Zero-Dependency Architecture Invariant (FED-30)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from atlas_federation import (
    ActionFirewallTamperError,
    ArtifactAccessDeniedError,
    CapabilityAdvertisement,
    CrossInstanceDelegationEngine,
    ExpiredMessageError,
    FederatedCapabilityRegistry,
    FederatedTraceContext,
    FederatedWorkflowExchange,
    FederationGateway,
    FederationIdentityManager,
    FederationProtocolEngine,
    FederationReputationTracker,
    FederationSecurityError,
    FederationSecurityGovernor,
    InvalidMessageSignatureError,
    InvalidResultEvidenceError,
    MCPAdapter,
    MCPToolDefinition,
    MessageType,
    OutboxMessageStatus,
    PackageTamperedError,
    PackageWithdrawnError,
    ParticipantIdentity,
    PeerRateLimitExceededError,
    PeerSecurityPolicy,
    ReplayAttackDetectedError,
    ResilientOutbox,
    TaskExecutionResult,
    TaskProposal,
    TaskProposalStatus,
    TenantIsolationError,
    TrustRelationship,
    UnauthorizedDelegationError,
    VisibilityScope,
    WebhookAdapter,
)


@pytest.fixture
def identity_mgr() -> FederationIdentityManager:
    return FederationIdentityManager()


@pytest.fixture
def protocol_eng() -> FederationProtocolEngine:
    return FederationProtocolEngine()


@pytest.fixture
def gateway_alpha() -> FederationGateway:
    return FederationGateway(organization_id="org_alpha", installation_id="inst_alpha_01")


@pytest.fixture
def gateway_beta() -> FederationGateway:
    return FederationGateway(organization_id="org_beta", installation_id="inst_beta_01")


# ---------------------------------------------------------------------------
# FED-01: Federation Enrollment & Installation Registration
# ---------------------------------------------------------------------------
def test_fed01_federation_enrollment(identity_mgr: FederationIdentityManager) -> None:
    identity = ParticipantIdentity(
        organization_id="org_acme",
        installation_id="inst_us_east_1",
        agent_id="agent_planner",
    )
    assert identity.urn == "urn:atlas:org:org_acme:inst:inst_us_east_1:agent:agent_planner"

    creds = identity_mgr.issue_credentials(
        organization_id=identity.organization_id,
        installation_id=identity.installation_id,
        duration_seconds=3600.0,
    )
    assert creds.credential_id.startswith("cred_fed_")
    assert creds.organization_id == "org_acme"
    assert creds.signature.startswith("sig_ed25519_")
    assert creds.is_valid()


# ---------------------------------------------------------------------------
# FED-02: Invalid Participant Identity Rejection
# ---------------------------------------------------------------------------
def test_fed02_invalid_participant_identity(identity_mgr: FederationIdentityManager) -> None:
    valid_creds = identity_mgr.issue_credentials(
        organization_id="org_valid",
        installation_id="inst_01",
    )

    # Tampered signature
    tampered_creds = valid_creds.model_copy(
        update={"signature": "sig_ed25519_forged_signature_value"}
    )
    assert not identity_mgr.authenticate_peer(tampered_creds)

    # Tampered organization
    tampered_org = valid_creds.model_copy(update={"organization_id": "org_spoofed"})
    assert not identity_mgr.authenticate_peer(tampered_org)


# ---------------------------------------------------------------------------
# FED-03: Federation Credential Rotation
# ---------------------------------------------------------------------------
def test_fed03_credential_rotation(identity_mgr: FederationIdentityManager) -> None:
    old_creds = identity_mgr.issue_credentials(
        organization_id="org_enterprise",
        installation_id="inst_prod_01",
    )
    assert identity_mgr.authenticate_peer(old_creds)

    new_creds = identity_mgr.rotate_credentials(old_creds.credential_id)

    # Old credential is automatically revoked
    assert identity_mgr.is_revoked(old_creds.credential_id)
    assert not identity_mgr.authenticate_peer(old_creds)

    # New credential is valid and active
    assert identity_mgr.authenticate_peer(new_creds)
    assert new_creds.credential_id != old_creds.credential_id


# ---------------------------------------------------------------------------
# FED-04: Federation Credential Revocation Enforcement
# ---------------------------------------------------------------------------
def test_fed04_credential_revocation(identity_mgr: FederationIdentityManager) -> None:
    creds = identity_mgr.issue_credentials(
        organization_id="org_compromised",
        installation_id="inst_leak_01",
    )
    assert identity_mgr.authenticate_peer(creds)

    # Revoke
    identity_mgr.revoke_credential(creds.credential_id, reason="Suspected key compromise")
    assert identity_mgr.is_revoked(creds.credential_id)
    assert not identity_mgr.authenticate_peer(creds)


# ---------------------------------------------------------------------------
# FED-05: Mutual Cryptographic Authentication between Peer Gateways
# ---------------------------------------------------------------------------
def test_fed05_mutual_authentication(
    gateway_alpha: FederationGateway, gateway_beta: FederationGateway
) -> None:
    # Alpha enrolls Beta
    beta_creds_from_alpha = gateway_alpha.enroll_peer("org_beta", TrustRelationship.TRUSTED)
    # Beta enrolls Alpha
    alpha_creds_from_beta = gateway_beta.enroll_peer("org_alpha", TrustRelationship.TRUSTED)

    # Mutual validation
    assert gateway_alpha.identity_manager.authenticate_peer(beta_creds_from_alpha)
    assert gateway_beta.identity_manager.authenticate_peer(alpha_creds_from_beta)


# ---------------------------------------------------------------------------
# FED-06: Federated Agent Capability Advertisement & Discovery
# ---------------------------------------------------------------------------
def test_fed06_agent_discovery(gateway_alpha: FederationGateway) -> None:
    gateway_alpha.advertise_agent(
        agent_id="research_agent_v1",
        task_categories=["web_research", "financial_analysis"],
        modalities=["text", "vision"],
        skills=["pdf_extractor", "sec_filings_analyzer"],
        visibility=VisibilityScope.FEDERATION,
    )

    discovered = gateway_alpha.discover(category="financial_analysis")
    assert len(discovered) == 1
    assert discovered[0].agent_id == "research_agent_v1"
    assert "pdf_extractor" in discovered[0].available_skills


# ---------------------------------------------------------------------------
# FED-07: Private Capability Visibility Scoping & Access Control
# ---------------------------------------------------------------------------
def test_fed07_private_capability_visibility() -> None:
    registry = FederatedCapabilityRegistry()

    # Private ad for Org A
    ad_private = CapabilityAdvertisement(
        organization_id="org_alpha",
        installation_id="inst_01",
        agent_id="internal_security_scanner",
        supported_task_categories=["internal_audit"],
        visibility=VisibilityScope.PRIVATE,
    )
    # Org-level ad for Org A
    ad_org = CapabilityAdvertisement(
        organization_id="org_alpha",
        installation_id="inst_01",
        agent_id="hr_assistant",
        supported_task_categories=["hr"],
        visibility=VisibilityScope.ORGANIZATION,
    )
    # Public ad for Org A
    ad_public = CapabilityAdvertisement(
        organization_id="org_alpha",
        installation_id="inst_01",
        agent_id="public_translator",
        supported_task_categories=["translation"],
        visibility=VisibilityScope.PUBLIC,
    )

    registry.register_advertisement(ad_private)
    registry.register_advertisement(ad_org)
    registry.register_advertisement(ad_public)

    # Query from same org (org_alpha) -> Sees all 3
    results_alpha = registry.query_capabilities(requesting_org_id="org_alpha")
    assert len(results_alpha) == 3

    # Query from foreign org (org_beta) -> Sees only PUBLIC (not PRIVATE or ORGANIZATION)
    results_beta = registry.query_capabilities(requesting_org_id="org_beta")
    assert len(results_beta) == 1
    assert results_beta[0].agent_id == "public_translator"


# ---------------------------------------------------------------------------
# FED-08: Public Discovery Authorization & Secret Sanitization
# ---------------------------------------------------------------------------
def test_fed08_public_discovery_authorization() -> None:
    registry = FederatedCapabilityRegistry()

    ad_with_secrets = CapabilityAdvertisement(
        organization_id="org_careless",
        installation_id="inst_01",
        agent_id="agent_leaky",
        supported_task_categories=["general", "internal_secret_processing"],
        available_skills=["normal_skill", "super_api_token_fetcher", "system_prompt_injector"],
        visibility=VisibilityScope.PUBLIC,
    )

    registered = registry.register_advertisement(ad_with_secrets)

    # Sensitive metadata must be stripped
    assert "internal_secret_processing" not in registered.supported_task_categories
    assert "super_api_token_fetcher" not in registered.available_skills
    assert "system_prompt_injector" not in registered.available_skills
    assert "normal_skill" in registered.available_skills


# ---------------------------------------------------------------------------
# FED-09: Capability Negotiation across Modalities & Resource Constraints
# ---------------------------------------------------------------------------
def test_fed09_capability_negotiation() -> None:
    registry = FederatedCapabilityRegistry()

    registry.register_advertisement(
        CapabilityAdvertisement(
            organization_id="org_provider",
            installation_id="inst_gpu_pool",
            agent_id="video_agent",
            supported_task_categories=["video_rendering"],
            supported_modalities=["video", "audio"],
        )
    )
    registry.register_advertisement(
        CapabilityAdvertisement(
            organization_id="org_provider",
            installation_id="inst_cpu_pool",
            agent_id="text_agent",
            supported_task_categories=["text_summary"],
            supported_modalities=["text"],
        )
    )

    # Query for video modality
    video_matches = registry.query_capabilities(requesting_org_id="org_client", modality="video")
    assert len(video_matches) == 1
    assert video_matches[0].agent_id == "video_agent"

    # Query for text modality
    text_matches = registry.query_capabilities(requesting_org_id="org_client", modality="text")
    assert len(text_matches) == 1
    assert text_matches[0].agent_id == "text_agent"


# ---------------------------------------------------------------------------
# FED-10: Cryptographically Signed Message Envelope Validation
# ---------------------------------------------------------------------------
def test_fed10_signed_message_validation(protocol_eng: FederationProtocolEngine) -> None:
    sender = ParticipantIdentity(organization_id="org_sender", installation_id="inst_01")
    recipient = ParticipantIdentity(organization_id="org_recipient", installation_id="inst_02")

    msg = protocol_eng.build_message(
        correlation_id="corr_100",
        message_type=MessageType.TASK_PROPOSAL,
        sender=sender,
        recipient=recipient,
        payload={"param": "value1"},
    )
    assert msg.signature.startswith("ed25519:")

    # Verify unpack succeeds
    unpacked = protocol_eng.verify_and_unpack(msg)
    assert unpacked == {"param": "value1"}

    # Tamper with payload
    tampered_msg = msg.model_copy(update={"payload": {"param": "tampered_value"}})
    with pytest.raises(InvalidMessageSignatureError):
        protocol_eng.verify_and_unpack(tampered_msg)


# ---------------------------------------------------------------------------
# FED-11: Nonce-Based Replay Attack Detection & Rejection
# ---------------------------------------------------------------------------
def test_fed11_replay_attack_rejection(protocol_eng: FederationProtocolEngine) -> None:
    sender = ParticipantIdentity(organization_id="org_s", installation_id="inst_s")
    recipient = ParticipantIdentity(organization_id="org_r", installation_id="inst_r")

    msg = protocol_eng.build_message(
        correlation_id="corr_101",
        message_type=MessageType.PROGRESS,
        sender=sender,
        recipient=recipient,
        payload={"step": 1},
    )

    # First delivery succeeds
    protocol_eng.verify_and_unpack(msg)

    # Replay with identical nonce in a modified envelope
    replay_msg = msg.model_copy(update={"message_id": "msg_replay_different_id"})
    replay_msg.signature = protocol_eng.compute_signature(replay_msg)

    with pytest.raises(ReplayAttackDetectedError):
        protocol_eng.verify_and_unpack(replay_msg)


# ---------------------------------------------------------------------------
# FED-12: Expired Federation Message Rejection (TTL Guard)
# ---------------------------------------------------------------------------
def test_fed12_expired_message_rejection(protocol_eng: FederationProtocolEngine) -> None:
    sender = ParticipantIdentity(organization_id="org_s", installation_id="inst_s")
    recipient = ParticipantIdentity(organization_id="org_r", installation_id="inst_r")

    # Message expired 10 seconds ago
    msg = protocol_eng.build_message(
        correlation_id="corr_102",
        message_type=MessageType.TASK_PROPOSAL,
        sender=sender,
        recipient=recipient,
        payload={"data": 123},
        ttl_seconds=5.0,
    )

    # Verify in future past expiry
    with pytest.raises(ExpiredMessageError):
        protocol_eng.verify_and_unpack(msg, now=msg.expires_at + 1.0)


# ---------------------------------------------------------------------------
# FED-13: Idempotent Duplicate Message Handling
# ---------------------------------------------------------------------------
def test_fed13_duplicate_message_handling(protocol_eng: FederationProtocolEngine) -> None:
    sender = ParticipantIdentity(organization_id="org_s", installation_id="inst_s")
    recipient = ParticipantIdentity(organization_id="org_r", installation_id="inst_r")

    msg = protocol_eng.build_message(
        correlation_id="corr_103",
        message_type=MessageType.PROGRESS,
        sender=sender,
        recipient=recipient,
        payload={"status": "working"},
    )

    # Process first time
    result1 = protocol_eng.verify_and_unpack(msg)
    # Process identical message second time -> returns cached result idempotently without error
    result2 = protocol_eng.verify_and_unpack(msg)

    assert result1 == result2 == {"status": "working"}


# ---------------------------------------------------------------------------
# FED-14: Cross-Instance Task Proposal Contract Negotiation
# ---------------------------------------------------------------------------
def test_fed14_task_proposal(
    identity_mgr: FederationIdentityManager,
    protocol_eng: FederationProtocolEngine,
) -> None:
    engine = CrossInstanceDelegationEngine(identity_mgr, protocol_eng)
    identity_mgr.set_pairwise_trust("org_partner", TrustRelationship.TRUSTED)

    sender = ParticipantIdentity(organization_id="org_local", installation_id="inst_01")
    recipient = ParticipantIdentity(organization_id="org_partner", installation_id="inst_02")

    proposal = TaskProposal(
        origin_task_id="task_445",
        origin_tenant_id="tenant_finance",
        sender=sender,
        recipient=recipient,
        objective="Analyze Q3 ledger",
        inputs={"ledger_id": "L-998"},
        required_permissions=["read:ledger"],
        verification_requirements=["ledger_summary_hash"],
    )

    envelope = engine.propose_task(proposal)
    assert envelope.message_type == MessageType.TASK_PROPOSAL
    assert envelope.correlation_id == proposal.proposal_id


# ---------------------------------------------------------------------------
# FED-15: Remote Task Acceptance & Lease Issuance
# ---------------------------------------------------------------------------
def test_fed15_remote_task_acceptance(
    identity_mgr: FederationIdentityManager,
    protocol_eng: FederationProtocolEngine,
) -> None:
    engine = CrossInstanceDelegationEngine(identity_mgr, protocol_eng)
    identity_mgr.set_pairwise_trust("org_sender", TrustRelationship.TRUSTED)

    sender = ParticipantIdentity(organization_id="org_sender", installation_id="inst_01")
    recipient = ParticipantIdentity(organization_id="org_receiver", installation_id="inst_02")

    proposal = TaskProposal(
        origin_task_id="task_123",
        origin_tenant_id="tenant_default",
        sender=sender,
        recipient=recipient,
        objective="Compute hash",
        inputs={"text": "hello"},
    )

    accepted, lease_id = engine.receive_and_authorize(proposal)
    assert accepted is True
    assert lease_id.startswith("lease_")
    assert proposal.status == TaskProposalStatus.ACCEPTED


# ---------------------------------------------------------------------------
# FED-16: Remote Action Firewall Authorization Failure Handling
# ---------------------------------------------------------------------------
def test_fed16_remote_authorization_failure(
    identity_mgr: FederationIdentityManager,
    protocol_eng: FederationProtocolEngine,
) -> None:
    engine = CrossInstanceDelegationEngine(identity_mgr, protocol_eng)
    identity_mgr.set_pairwise_trust("org_sender", TrustRelationship.TRUSTED)

    sender = ParticipantIdentity(organization_id="org_sender", installation_id="inst_01")
    recipient = ParticipantIdentity(organization_id="org_receiver", installation_id="inst_02")

    proposal = TaskProposal(
        origin_task_id="task_evil",
        origin_tenant_id="tenant_default",
        sender=sender,
        recipient=recipient,
        objective="Escalate privilege",
        inputs={},
        required_permissions=["admin:root", "firewall:modify"],
    )

    # Pass dummy firewall object
    accepted, reason = engine.receive_and_authorize(proposal, local_firewall=object())
    assert accepted is False
    assert "rejected dangerous permission" in reason


# ---------------------------------------------------------------------------
# FED-17: End-to-End Cross-Instance Task Delegation & Execution
# ---------------------------------------------------------------------------
def test_fed17_cross_instance_execution(
    gateway_alpha: FederationGateway, gateway_beta: FederationGateway
) -> None:
    # Mutual trust
    gateway_alpha.enroll_peer("org_beta", TrustRelationship.TRUSTED)
    gateway_beta.enroll_peer("org_alpha", TrustRelationship.TRUSTED)

    # Alpha proposes task to Beta
    proposal, envelope = gateway_alpha.delegate_task(
        recipient=gateway_beta.identity,
        objective="Summarize technical document",
        inputs={"doc_url": "https://example.com/doc.txt"},
        verification_requirements=["summary_hash", "token_count"],
    )

    # Beta authorizes
    authorized, lease_token = gateway_beta.receive_and_authorize_task(proposal)
    assert authorized is True

    # Beta simulates execution and returns result
    result = TaskExecutionResult(
        proposal_id=proposal.proposal_id,
        status="COMPLETED",
        outputs={"summary": "Document summarizes distributed consensus."},
        evidence_refs=["summary_hash:sha256_abcdef123", "token_count:42"],
        execution_duration_sec=1.2,
        worker_signature="sig_worker_beta_valid",
    )

    # Alpha independently verifies returned result
    verified = gateway_alpha.verify_remote_result(proposal, result)
    assert verified is True
    assert proposal.status == TaskProposalStatus.COMPLETED


# ---------------------------------------------------------------------------
# FED-18: Invalid or Forged Task Result Rejection
# ---------------------------------------------------------------------------
def test_fed18_invalid_result_rejection(gateway_alpha: FederationGateway) -> None:
    proposal = TaskProposal(
        origin_task_id="task_99",
        origin_tenant_id="tenant_01",
        sender=gateway_alpha.identity,
        recipient=ParticipantIdentity(organization_id="org_untrusted", installation_id="inst_01"),
        objective="Sensitive query",
        verification_requirements=["signed_proof"],
    )

    # Result missing worker signature
    invalid_result = TaskExecutionResult(
        proposal_id=proposal.proposal_id,
        status="COMPLETED",
        outputs={"data": 123},
        evidence_refs=["signed_proof"],
        worker_signature="",  # Missing signature
    )

    with pytest.raises(InvalidResultEvidenceError, match="missing worker signature"):
        gateway_alpha.verify_remote_result(proposal, invalid_result)


# ---------------------------------------------------------------------------
# FED-19: Independent Evidence Verification by Delegating Installation
# ---------------------------------------------------------------------------
def test_fed19_evidence_verification(gateway_alpha: FederationGateway) -> None:
    proposal = TaskProposal(
        origin_task_id="task_audit",
        origin_tenant_id="tenant_01",
        sender=gateway_alpha.identity,
        recipient=ParticipantIdentity(organization_id="org_peer", installation_id="inst_01"),
        objective="Run benchmark",
        verification_requirements=["latency_p99_proof", "stdout_log"],
    )

    # Evidence missing required criteria
    partial_result = TaskExecutionResult(
        proposal_id=proposal.proposal_id,
        status="COMPLETED",
        outputs={"p99": 15},
        evidence_refs=["stdout_log"],  # Missing latency_p99_proof
        worker_signature="sig_worker_ok",
    )

    with pytest.raises(InvalidResultEvidenceError, match="failed verification requirement"):
        gateway_alpha.verify_remote_result(proposal, partial_result)


# ---------------------------------------------------------------------------
# FED-20: Strict Multi-Tenant Isolation across Federation Boundaries
# ---------------------------------------------------------------------------
def test_fed20_cross_tenant_isolation() -> None:
    gov = FederationSecurityGovernor()

    # Attempt cross-tenant access between unauthorized tenants
    with pytest.raises(TenantIsolationError, match="Cross-tenant isolation violation"):
        gov.check_incoming_request(
            sender_org_id="org_external",
            target_tenant_id="tenant_finance_internal",
            origin_tenant_id="tenant_marketing_external",
        )


# ---------------------------------------------------------------------------
# FED-21: Cross-Boundary Media & Artifact Authorization Check
# ---------------------------------------------------------------------------
def test_fed21_artifact_authorization() -> None:
    gov = FederationSecurityGovernor()

    # Register restricted artifact
    gov.register_artifact(
        artifact_id="art_secret_keys",
        owner_org_id="org_owner",
        tenant_id="tenant_secure",
        classification="RESTRICTED",
        shareable_federated=False,  # Not shareable
    )

    with pytest.raises(ArtifactAccessDeniedError, match="non-shareable"):
        gov.check_incoming_request(
            sender_org_id="org_partner",
            target_tenant_id="tenant_secure",
            origin_tenant_id="tenant_secure",
            referenced_artifact_ids=["art_secret_keys"],
        )


# ---------------------------------------------------------------------------
# FED-22: Malicious Federation Participant Isolation & Rate Limiting
# ---------------------------------------------------------------------------
def test_fed22_malicious_participant_isolation() -> None:
    reputation = FederationReputationTracker()
    gov = FederationSecurityGovernor(
        reputation_tracker=reputation,
        default_policy=PeerSecurityPolicy(max_requests_per_minute=3),
    )

    # 1. Rate Limiting Test
    for _ in range(3):
        gov.check_incoming_request(
            sender_org_id="org_spammer",
            target_tenant_id="tenant_common",
            origin_tenant_id="tenant_common",
        )

    # 4th request exceeds rate limit
    with pytest.raises(PeerRateLimitExceededError):
        gov.check_incoming_request(
            sender_org_id="org_spammer",
            target_tenant_id="tenant_common",
            origin_tenant_id="tenant_common",
        )

    # 2. Action Firewall Tamper & Immediate Isolation Test
    with pytest.raises(ActionFirewallTamperError):
        gov.check_incoming_request(
            sender_org_id="org_attacker",
            target_tenant_id="tenant_common",
            origin_tenant_id="tenant_common",
            requested_actions=["firewall:disable", "sudo"],
        )

    # Verify that org_attacker is now completely isolated
    assert reputation.is_isolated("org_attacker")
    with pytest.raises(FederationSecurityError, match="isolated due to security violations"):
        gov.check_incoming_request(
            sender_org_id="org_attacker",
            target_tenant_id="tenant_common",
            origin_tenant_id="tenant_common",
        )


# ---------------------------------------------------------------------------
# FED-23: Federated Skill Package Signature & Provenance Verification
# ---------------------------------------------------------------------------
def test_fed23_package_signature_validation() -> None:
    exchange = FederatedWorkflowExchange()

    skill_code = b"print('Hello from federated skill')"
    pkg = exchange.publish_package(
        package_id="pkg_data_cleaner",
        name="DataCleanerSkill",
        version="1.0.0",
        publisher_org_id="org_skills_inc",
        content=skill_code,
        declared_permissions=["filesystem:read"],
    )

    # Valid package verification
    assert exchange.verify_package(pkg, content=skill_code)

    # Content tampering detection
    tampered_code = b"print('Tampered code!')"
    with pytest.raises(PackageTamperedError):
        exchange.verify_package(pkg, content=tampered_code)

    # Import package: Zero-permission inheritance check
    imported = exchange.import_package(
        requesting_org_id="org_consumer", package_id="pkg_data_cleaner"
    )
    assert imported["granted_permissions"] == []  # Zero permissions inherited
    assert imported["sandbox_isolated"] is True

    # Withdrawal
    exchange.withdraw_package(
        "org_skills_inc", "pkg_data_cleaner", reason="CVE-2026-9999 discovered"
    )
    with pytest.raises(PackageWithdrawnError):
        exchange.import_package("org_consumer", "pkg_data_cleaner")


# ---------------------------------------------------------------------------
# FED-24: Network Partition Detection & Outbox Buffering
# ---------------------------------------------------------------------------
def test_fed24_network_partition(protocol_eng: FederationProtocolEngine) -> None:
    outbox = ResilientOutbox()
    msg = protocol_eng.build_message(
        correlation_id="corr_part_1",
        message_type=MessageType.TASK_PROPOSAL,
        sender=ParticipantIdentity(organization_id="org_a", installation_id="inst_a"),
        recipient=ParticipantIdentity(organization_id="org_b", installation_id="inst_b"),
        payload={"task": 1},
    )

    outbox.enqueue(msg)
    assert len(outbox.get_pending_entries()) == 1

    # Simulate network partition
    outbox.set_partitioned(True)
    delivered = outbox.flush()
    # 0 delivered, messages safely retained in buffer
    assert delivered == 0
    assert len(outbox.get_pending_entries()) == 1
    assert outbox.get_pending_entries()[0].status == OutboxMessageStatus.BUFFERED


# ---------------------------------------------------------------------------
# FED-25: Network Reconnection & Resilient Message Replay
# ---------------------------------------------------------------------------
def test_fed25_reconnection_and_resynchronization(protocol_eng: FederationProtocolEngine) -> None:
    outbox = ResilientOutbox()
    msg = protocol_eng.build_message(
        correlation_id="corr_part_2",
        message_type=MessageType.PROGRESS,
        sender=ParticipantIdentity(organization_id="org_a", installation_id="inst_a"),
        recipient=ParticipantIdentity(organization_id="org_b", installation_id="inst_b"),
        payload={"step": "upload"},
    )
    outbox.enqueue(msg)
    outbox.set_partitioned(True)
    outbox.flush()

    # Reconnect network
    outbox.set_partitioned(False)
    delivered = outbox.flush(delivery_fn=lambda m: True)
    assert delivered == 1
    assert len(outbox.get_pending_entries()) == 0


# ---------------------------------------------------------------------------
# FED-26: Unknown Remote Outcome Safe Reconciliation Protocol
# ---------------------------------------------------------------------------
def test_fed26_unknown_remote_outcome_reconciliation(
    protocol_eng: FederationProtocolEngine,
) -> None:
    outbox = ResilientOutbox()
    msg = protocol_eng.build_message(
        correlation_id="proposal_unconfirmed_99",
        message_type=MessageType.TASK_PROPOSAL,
        sender=ParticipantIdentity(organization_id="org_a", installation_id="inst_a"),
        recipient=ParticipantIdentity(organization_id="org_b", installation_id="inst_b"),
        payload={"charge_amount": 500},
    )
    entry = outbox.enqueue(msg)

    # Connection dropped before receiving ACK. Query remote status endpoint:
    def mock_remote_query(proposal_id: str) -> dict[str, str]:
        assert proposal_id == "proposal_unconfirmed_99"
        return {"status": "COMPLETED"}

    resolved_status = outbox.reconcile_remote_outcome("proposal_unconfirmed_99", mock_remote_query)
    assert resolved_status == "COMPLETED"
    assert entry.status == OutboxMessageStatus.ACKNOWLEDGED


# ---------------------------------------------------------------------------
# FED-27: Federation Disconnection & Pairwise Trust Revocation
# ---------------------------------------------------------------------------
def test_fed27_federation_revocation(gateway_alpha: FederationGateway) -> None:
    gateway_alpha.enroll_peer("org_untrustworthy", TrustRelationship.TRUSTED)
    assert (
        gateway_alpha.identity_manager.get_pairwise_trust("org_untrustworthy")
        == TrustRelationship.TRUSTED
    )

    # Disconnect & Revoke trust
    gateway_alpha.revoke_peer_trust("org_untrustworthy")
    assert (
        gateway_alpha.identity_manager.get_pairwise_trust("org_untrustworthy")
        == TrustRelationship.BLOCKED
    )

    # Delegations are blocked
    proposal = TaskProposal(
        origin_task_id="t1",
        origin_tenant_id="ten1",
        sender=gateway_alpha.identity,
        recipient=ParticipantIdentity(
            organization_id="org_untrustworthy", installation_id="inst_x"
        ),
        objective="Test",
    )
    with pytest.raises(UnauthorizedDelegationError, match="is BLOCKED"):
        gateway_alpha.delegation_engine.propose_task(proposal)


# ---------------------------------------------------------------------------
# FED-28: External Agent Protocol Interoperability (MCP & Webhooks)
# ---------------------------------------------------------------------------
def test_fed28_external_protocol_interoperability() -> None:
    # 1. MCP Adapter Test with Action Firewall Evaluation
    mcp = MCPAdapter(
        organization_id="org_local", installation_id="inst_mcp", local_firewall=object()
    )
    mcp.register_tool(
        MCPToolDefinition(
            name="query_database",
            description="Executes readonly SQL query",
            inputSchema={"type": "object", "properties": {"sql": {"type": "string"}}},
        )
    )

    # Valid tool call
    res_valid = mcp.call_tool("query_database", {"sql": "SELECT count(*) FROM users"})
    assert res_valid["isError"] is False

    # Blocked dangerous tool call (Action Firewall gate)
    res_blocked = mcp.call_tool("query_database", {"sql": "DROP TABLE users; rm -rf /"})
    assert res_blocked["isError"] is True
    assert "Action Firewall blocked" in res_blocked["content"][0]["text"]

    # 2. Webhook Adapter Test with HMAC-SHA256 signature
    webhook = WebhookAdapter(
        secret_key="my_secret_token", organization_id="org_local", installation_id="inst_wh"
    )
    body = json.dumps({"source_org": "github_org", "objective": "Run CI verification"}).encode()
    valid_sig = webhook.compute_signature(body)

    # Valid webhook ingestion
    proposal = webhook.ingest_webhook(body, {"X-Atlas-Signature": valid_sig})
    assert proposal.objective == "Run CI verification"

    # Invalid webhook signature rejection
    with pytest.raises(UnauthorizedDelegationError, match="invalid or missing"):
        webhook.ingest_webhook(body, {"X-Atlas-Signature": "forged_signature"})


# ---------------------------------------------------------------------------
# FED-29: Full Distributed Multi-Agent Collaborative Task Workflow
# ---------------------------------------------------------------------------
def test_fed29_full_distributed_task_workflow(
    gateway_alpha: FederationGateway,
    gateway_beta: FederationGateway,
) -> None:
    # Setup mutual trust & enrollment
    gateway_alpha.enroll_peer("org_beta", TrustRelationship.TRUSTED)
    gateway_beta.enroll_peer("org_alpha", TrustRelationship.TRUSTED)

    # Beta advertises specialized machine learning agent
    gateway_beta.advertise_agent(
        agent_id="ml_classifier_agent",
        task_categories=["machine_learning", "classification"],
        modalities=["text", "tabular"],
        skills=["xgboost_predictor"],
        visibility=VisibilityScope.FEDERATION,
    )

    # Synchronize capabilities across federated gateways
    gateway_alpha.sync_capabilities(gateway_beta.capability_registry)

    # Alpha discovers Beta's agent
    discovered = gateway_alpha.discover(target_org_id="org_beta", category="classification")
    assert len(discovered) == 1
    target_agent = discovered[0]
    assert target_agent.agent_id == "ml_classifier_agent"

    # Alpha traces execution with W3C Distributed Context
    trace = FederatedTraceContext(
        correlation_id="corr_workflow_29",
        originating_org_id="org_alpha",
    )
    gateway_alpha.telemetry.record_event(
        "task_delegation_started",
        trace_context=trace,
        attributes={"objective": "Classify user churn dataset", "token": "sensitive_leaked_token"},
    )
    # Ensure telemetry is sanitized
    events = gateway_alpha.telemetry.get_events()
    assert events[0]["attributes"]["token"] == "[REDACTED]"

    # Alpha proposes task to Beta
    proposal, envelope = gateway_alpha.delegate_task(
        recipient=ParticipantIdentity(
            organization_id=target_agent.organization_id,
            installation_id=target_agent.installation_id,
            agent_id=target_agent.agent_id,
        ),
        objective="Classify churn risk dataset",
        inputs={"dataset_url": "s3://clean_churn.csv"},
        required_permissions=["read:dataset"],
        verification_requirements=["roc_auc_score", "confusion_matrix"],
    )

    # Beta receives, validates firewall, and issues lease
    authorized, lease_token = gateway_beta.receive_and_authorize_task(proposal)
    assert authorized is True

    # Beta completes task and returns execution result
    result = TaskExecutionResult(
        proposal_id=proposal.proposal_id,
        status="COMPLETED",
        outputs={"accuracy": 0.94, "churn_count": 128},
        evidence_refs=[
            "roc_auc_score:0.96",
            "confusion_matrix:sha256_e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        ],
        execution_duration_sec=3.4,
        worker_signature="sig_worker_beta_ml_cluster",
    )

    # Alpha independently verifies returned evidence
    verified = gateway_alpha.verify_remote_result(proposal, result)
    assert verified is True
    assert proposal.status == TaskProposalStatus.COMPLETED

    # Check that Alpha updated Beta's reputation
    assert gateway_alpha.reputation_tracker.get_score("org_beta") > 1.0 - 0.001
    assert not gateway_alpha.reputation_tracker.is_isolated("org_beta")


# ---------------------------------------------------------------------------
# FED-30: Monorepo Full Regression & Core Zero-Dependency Preservation
# ---------------------------------------------------------------------------
def test_fed30_full_monorepo_regression_and_zero_dependency_core() -> None:
    # Read packages/atlas-core/pyproject.toml directly
    core_toml_path = (
        Path(__file__).resolve().parents[2] / "packages" / "atlas-core" / "pyproject.toml"
    )
    assert core_toml_path.exists(), f"Path {core_toml_path} not found"

    content = core_toml_path.read_text(encoding="utf-8")
    for forbidden in [
        "kubernetes",
        "playwright",
        "psycopg",
        "asyncpg",
        "fastapi",
        "docker",
        "torch",
        "sklearn",
    ]:
        assert forbidden not in content.lower(), (
            f"Constitutional Invariant 3 Violated: Forbidden driver '{forbidden}' detected in atlas-core!"
        )

    # Verify that atlas-federation is registered in root pyproject.toml
    root_toml = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    assert "packages/atlas-federation" in root_toml
