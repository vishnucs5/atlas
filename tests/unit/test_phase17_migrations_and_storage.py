"""Unit tests for Phase 17 Migrations 019 & 020 and CollaborationStorage."""

from __future__ import annotations

import time
from pathlib import Path

from atlas_collaboration.models import (
    AgentDecisionLineage,
    ComplianceBundle,
    DecisionFactor,
    SteeringEvent,
    TurnLease,
    WorkspaceRole,
)
from atlas_collaboration.storage import CollaborationStorage


def test_migrations_and_storage_initialization(tmp_path: Path):
    """Verify CollaborationStorage initializes tables without syntax errors."""
    db_file = tmp_path / "collab_test.db"
    storage = CollaborationStorage(db_path=db_file)
    assert storage is not None
    assert db_file.exists()


def test_workspace_crud_and_collaborators(tmp_path: Path):
    """Verify workspace creation, listing, inspection, and member registration."""
    storage = CollaborationStorage(db_path=tmp_path / "ws.db")

    ws = storage.save_workspace(
        workspace_id="ws_fin_01",
        name="Q4 Financial Audit",
        tenant_id="tenant_finance",
        metadata={"priority": "HIGH"},
    )
    assert ws["workspace_id"] == "ws_fin_01"
    assert ws["name"] == "Q4 Financial Audit"
    assert ws["status"] == "ACTIVE"

    # Add collaborators
    storage.add_collaborator("ws_fin_01", "auditor@corp.internal", WorkspaceRole.OWNER)
    storage.add_collaborator("ws_fin_01", "agent_reconcile", WorkspaceRole.AUTONOMOUS_WORKER)

    fetched = storage.get_workspace("ws_fin_01")
    assert fetched is not None
    assert fetched["name"] == "Q4 Financial Audit"
    assert len(fetched["collaborators"]) == 2
    identities = {c["identity"] for c in fetched["collaborators"]}
    assert "auditor@corp.internal" in identities
    assert "agent_reconcile" in identities

    # List workspaces
    workspaces = storage.list_workspaces(tenant_id="tenant_finance")
    assert len(workspaces) == 1
    assert workspaces[0]["workspace_id"] == "ws_fin_01"


def test_turn_lease_lifecycle_and_fencing(tmp_path: Path):
    """Verify persisting and querying turn leases with monotonic fencing tokens."""
    storage = CollaborationStorage(db_path=tmp_path / "lease.db")
    storage.save_workspace("ws_lease_01", "Turn Lease Test")

    lease_1 = TurnLease(
        lease_id="lease_001",
        workspace_id="ws_lease_01",
        holder_identity="agent_coder",
        holder_role=WorkspaceRole.AUTONOMOUS_WORKER,
        fencing_token=1,
        acquired_at=time.time(),
        expires_at=time.time() + 300,
        is_active=True,
    )
    storage.save_lease(lease_1)

    active = storage.get_active_lease("ws_lease_01")
    assert active is not None
    assert active.holder_identity == "agent_coder"
    assert active.fencing_token == 1

    # Human preempts with higher fencing token
    lease_2 = TurnLease(
        lease_id="lease_002",
        workspace_id="ws_lease_01",
        holder_identity="sarah_engineer",
        holder_role=WorkspaceRole.OWNER,
        fencing_token=2,
        acquired_at=time.time(),
        expires_at=time.time() + 300,
        is_active=True,
    )
    storage.save_lease(lease_2)

    active_preempted = storage.get_active_lease("ws_lease_01")
    assert active_preempted is not None
    assert active_preempted.holder_identity == "sarah_engineer"
    assert active_preempted.fencing_token == 2


def test_decision_lineage_persistence(tmp_path: Path):
    """Verify storing and retrieving causal decision lineage records."""
    storage = CollaborationStorage(db_path=tmp_path / "lineage.db")

    factor = DecisionFactor(
        factor_id="f_01",
        factor_type="POLICY_RULE",
        source_reference="policy_dual_signoff.rego",
        confidence_weight=1.0,
        description="Dual sign-off mandated for transfers exceeding $10,000",
    )
    lineage = AgentDecisionLineage(
        decision_id="dec_9901",
        tenant_id="tenant_finance",
        agent_id="agent_payouts",
        task_instance_id="task_wire_123",
        selected_action="transfer.hold_for_secondary_approval",
        rationale="Amount exceeds single-authority threshold",
        factors=[factor],
        policy_checks_passed=["SEC-01", "FIN-04"],
        merkle_root_hash="hash_merkle_abcdef123456",
        cas_artifact_uri="atlas-cas://abcdef1234567890",
        timestamp=time.time(),
    )
    storage.save_decision_lineage(lineage)

    decisions = storage.list_decision_lineages("task_wire_123")
    assert len(decisions) == 1
    d = decisions[0]
    assert d.decision_id == "dec_9901"
    assert d.selected_action == "transfer.hold_for_secondary_approval"
    assert len(d.factors) == 1
    assert d.factors[0].factor_id == "f_01"


def test_steering_and_compliance_persistence(tmp_path: Path):
    """Verify storing steering intervention events and compliance bundles."""
    storage = CollaborationStorage(db_path=tmp_path / "steer_comp.db")

    event = SteeringEvent(
        steering_id="steer_001",
        workspace_id="ws_steer_01",
        operator_id="operator_dan",
        parent_operation_key="op_parent_99",
        child_operation_key="op_child_100",
        original_parameters={"amount": 50000},
        modified_parameters={"amount": 25000, "memo": "Adjusted per audit"},
        reason="Exceeded preliminary budget",
        timestamp=time.time(),
    )
    storage.save_steering_event(event)

    events = storage.list_steering_events("ws_steer_01")
    assert len(events) == 1
    assert events[0].operator_id == "operator_dan"
    assert events[0].child_operation_key == "op_child_100"

    bundle = ComplianceBundle(
        bundle_id="bundle_compliance_77",
        tenant_id="tenant_health",
        workspace_id="ws_steer_01",
        framework="HIPAA",
        frameworks=["HIPAA", "EU_AI_ACT"],
        root_merkle_hash="merkle_root_998877",
        decision_merkle_root="merkle_root_998877",
        signature="sig_hmac_112233",
        hmac_signature="sig_hmac_112233",
        record_count=5,
        total_decisions=5,
        generated_at=time.time(),
    )
    storage.save_compliance_bundle(bundle)

    fetched_bundle = storage.get_latest_compliance_bundle("ws_steer_01")
    assert fetched_bundle is not None
    assert fetched_bundle.bundle_id == "bundle_compliance_77"
    assert "HIPAA" in fetched_bundle.frameworks
