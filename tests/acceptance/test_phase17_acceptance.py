"""ATLAS Phase 17 Acceptance Test Suite: Human-AI Collaboration & Governance Ecosystem.

Comprehensive end-to-end acceptance test suite verifying scenarios COL-01 through COL-20:
- COL-01: Multi-Tenant Collaborative Workspace Initialization
- COL-02: Server-Authoritative Semantic Turn-Locking with Monotonic Fencing
- COL-03: Human Preemptive Override with Immediate Fencing Invalidation
- COL-04: Turn Lease Expiration and Automatic Lock Release
- COL-05: Content-Addressable Storage (CAS) Reference Verification
- COL-06: Causal Decision Lineage and Explainability Tracing
- COL-07: Merkle Decision Factor Tree Cryptographic Verification
- COL-08: In-Flight Workflow Steering & Safe Pause
- COL-09: Deterministic Child Idempotency Key Derivation
- COL-10: In-Flight Parameter Modification and Execution Resumption
- COL-11: Dynamic Capability-Restricted Policy Delegation
- COL-12: Delegation Time Expiration Enforcement
- COL-13: Continuous Compliance Evidence Bundle Generation
- COL-14: HMAC-SHA256 Cryptographic Tamper Detection for Compliance Bundles
- COL-15: Hermetic Monte Carlo Policy Simulation Sandbox
- COL-16: Simulation Sandbox Firewall Guard
- COL-17: FastAPI REST Control Plane Endpoints
- COL-18: CLI Collaboration Subcommands E2E
- COL-19: Operator Control Plane Web Dashboard E2E
- COL-20: Enterprise Relational Database Migrations 019 & 020 Integration
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest
from atlas_cli.commands.collaboration import (
    run_steering_pause,
    run_steering_resume,
    run_workspace_create,
    run_workspace_list,
)
from atlas_collaboration.compliance import ComplianceEvidenceGenerator
from atlas_collaboration.explainability import CausalDecisionTracer
from atlas_collaboration.models import (
    DecisionFactor,
    DelegationEnvelope,
    WorkspaceRole,
)
from atlas_collaboration.simulation import (
    DryRunConnectorDriver,
    PolicySimulationEngine,
    SimulationSandboxViolationError,
)
from atlas_collaboration.steering import (
    SteeringController,
    WorkflowNotPausedError,
)
from atlas_collaboration.storage import CollaborationStorage
from atlas_collaboration.workspace import (
    CollaborativeWorkspaceHub,
    FencingTokenInvalidError,
    TurnLeaseConflictError,
)
from fastapi.testclient import TestClient


# ==============================================================================
# Scenario COL-01: Multi-Tenant Collaborative Workspace Initialization
# ==============================================================================
def test_col01_workspace_session_initialization() -> None:
    """Verify collaborative session initialization, tenant isolation, and snapshot state."""
    hub = CollaborativeWorkspaceHub()
    session = hub.create_session(
        tenant_id="tenant_fin_01",
        workspace_name="Q4 Financial Ledger Audit",
        owner_identity="chief_accountant",
    )

    assert session.session_id.startswith("ws_sess_")
    assert session.tenant_id == "tenant_fin_01"
    assert session.workspace_name == "Q4 Financial Ledger Audit"
    assert session.status == "ACTIVE"
    assert "chief_accountant" in session.collaborators
    assert session.collaborators["chief_accountant"].role == WorkspaceRole.OWNER

    # Register an autonomous worker
    hub.join_session(
        session_id=session.session_id,
        identity="agent_reconciler_01",
        role=WorkspaceRole.AUTONOMOUS_WORKER,
        is_human=False,
    )

    snapshot = hub.get_snapshot(session.session_id)
    assert snapshot["collaborator_count"] == 2
    assert snapshot["sequence_id"] == 0
    assert snapshot["status"] == "ACTIVE"


# ==============================================================================
# Scenario COL-02: Server-Authoritative Semantic Turn-Locking with Monotonic Fencing
# ==============================================================================
def test_col02_semantic_turn_locking_fencing() -> None:
    """Verify single-writer turn locking and monotonic fencing token incrementation."""
    hub = CollaborativeWorkspaceHub()
    session = hub.create_session(
        tenant_id="tenant_ops_01",
        workspace_name="Infrastructure Deployment",
        owner_identity="devops_lead",
    )
    sid = session.session_id

    hub.join_session(sid, "agent_terraform_01", WorkspaceRole.AUTONOMOUS_WORKER, is_human=False)
    hub.join_session(sid, "agent_ansible_01", WorkspaceRole.AUTONOMOUS_WORKER, is_human=False)

    # First agent acquires lease
    lease1 = hub.acquire_turn_lease(sid, identity="agent_terraform_01", duration_seconds=60.0)
    assert lease1.holder_identity == "agent_terraform_01"
    assert lease1.fencing_token == 1
    assert lease1.is_active is True

    # Concurrent acquisition by another agent fails closed
    with pytest.raises(TurnLeaseConflictError, match="Turn lease is actively held"):
        hub.acquire_turn_lease(sid, identity="agent_ansible_01")


# ==============================================================================
# Scenario COL-03: Human Preemptive Override with Immediate Fencing Invalidation
# ==============================================================================
def test_col03_human_preemptive_override() -> None:
    """Verify human operators immediately preempt active agent turn leases."""
    hub = CollaborativeWorkspaceHub()
    session = hub.create_session(
        tenant_id="tenant_sec_01",
        workspace_name="Incident Response Chamber",
        owner_identity="secops_commander",
    )
    sid = session.session_id

    hub.join_session(sid, "agent_triage_01", WorkspaceRole.AUTONOMOUS_WORKER, is_human=False)

    # Agent acquires turn lease
    agent_lease = hub.acquire_turn_lease(sid, identity="agent_triage_01", duration_seconds=120.0)
    assert agent_lease.fencing_token == 1

    # Human intervenes and preempts the agent
    human_lease = hub.acquire_turn_lease(sid, identity="secops_commander", duration_seconds=60.0)
    assert human_lease.holder_identity == "secops_commander"
    assert human_lease.fencing_token == 2
    assert human_lease.is_human is True
    assert agent_lease.preempted is True

    # Preempted agent attempting to write receives FencingTokenInvalidError
    with pytest.raises(FencingTokenInvalidError, match="superseded"):
        hub.mutate_artifact(
            sid,
            "agent_triage_01",
            agent_lease.fencing_token,
            "remediation_plan",
            {"block_ip": True},
        )

    # Human mutates artifact successfully
    seq = hub.mutate_artifact(
        sid,
        "secops_commander",
        human_lease.fencing_token,
        "remediation_plan",
        {"isolate_subnet": True},
    )
    assert seq == 1


# ==============================================================================
# Scenario COL-04: Turn Lease Expiration and Automatic Lock Release
# ==============================================================================
def test_col04_turn_lease_expiration_and_release() -> None:
    """Verify turn leases expire naturally and allow subsequent turn acquisition."""
    hub = CollaborativeWorkspaceHub()
    session = hub.create_session(
        tenant_id="tenant_test",
        workspace_name="Quick Review",
        owner_identity="user_alice",
    )
    sid = session.session_id

    hub.join_session(sid, "agent_worker_01", WorkspaceRole.AUTONOMOUS_WORKER, is_human=False)

    # Acquire an expired lease
    lease = hub.acquire_turn_lease(sid, identity="agent_worker_01", duration_seconds=0.01)
    time.sleep(0.02)
    assert lease.is_expired() is True
    assert lease.is_active is False

    # New acquisition succeeds without conflict
    lease2 = hub.acquire_turn_lease(sid, identity="user_alice", duration_seconds=60.0)
    assert lease2.fencing_token == 2
    assert lease2.holder_identity == "user_alice"


# ==============================================================================
# Scenario COL-05: Content-Addressable Storage (CAS) Reference Verification
# ==============================================================================
def test_col05_cas_artifact_integrity_verification() -> None:
    """Verify content-addressable storage (CAS) URI and SHA-256 hash calculation."""
    tracer = CausalDecisionTracer()

    payload = {"query": "SELECT * FROM users", "risk_score": 0.12}
    lineage = tracer.record_decision(
        tenant_id="tenant_data_01",
        agent_id="agent_sql_reviewer",
        task_instance_id="task_db_01",
        selected_action="approve_query",
        rationale="Read-only query with minimal cost impact",
        factors=[],
        policy_checks_passed=["rule_no_drop_table"],
        context_payload=payload,
    )

    assert lineage.cas_ref is not None
    assert lineage.cas_ref.uri.startswith("atlas-cas://")
    expected_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    assert lineage.cas_ref.sha256_hash == expected_hash
    assert lineage.cas_ref.uri == f"atlas-cas://{expected_hash}"


# ==============================================================================
# Scenario COL-06: Causal Decision Lineage and Explainability Tracing
# ==============================================================================
def test_col06_causal_decision_lineage_tracing() -> None:
    """Verify capturing factor trees, policy checks, and causal chains for decisions."""
    tracer = CausalDecisionTracer()
    factor = DecisionFactor(
        factor_id="df_01",
        factor_type="POLICY_RULE",
        source_reference="enterprise_iam_policy.v2",
        confidence_weight=1.0,
        description="Admin roles must have hardware key MFA enabled",
    )

    lineage = tracer.record_decision(
        tenant_id="tenant_corp",
        agent_id="agent_iam_enforcer",
        task_instance_id="task_role_grant_88",
        selected_action="deny_role_elevation",
        rationale="Candidate lacks FIDO2 hardware token",
        factors=[factor],
        policy_checks_passed=["rule_fido2_required"],
    )

    chain = tracer.get_task_causal_chain("task_role_grant_88")
    assert len(chain) == 1
    assert chain[0].decision_id == lineage.decision_id
    assert chain[0].selected_action == "deny_role_elevation"
    assert chain[0].factors[0].factor_id == "df_01"


# ==============================================================================
# Scenario COL-07: Merkle Decision Factor Tree Cryptographic Verification
# ==============================================================================
def test_col07_merkle_factor_tree_tamper_detection() -> None:
    """Verify Merkle root integrity and detection of modified factor trees."""
    tracer = CausalDecisionTracer()
    factor1 = DecisionFactor(
        factor_id="f1",
        factor_type="DOCUMENT",
        source_reference="handbook.pdf#p10",
        confidence_weight=0.9,
        description="Standard procurement limit is $10k",
    )
    factor2 = DecisionFactor(
        factor_id="f2",
        factor_type="HISTORICAL_OUTCOME",
        source_reference="po_9921",
        confidence_weight=0.85,
        description="Prior vendor approval history",
    )

    lineage = tracer.record_decision(
        tenant_id="tenant_proc",
        agent_id="agent_procurement",
        task_instance_id="task_po_01",
        selected_action="require_dual_approval",
        rationale="PO exceeds $10k standard threshold",
        factors=[factor1, factor2],
        policy_checks_passed=["procurement_limit_rule"],
    )

    # Verification of genuine lineage
    assert tracer.verify_integrity(lineage.decision_id) is True

    # Tampering: mutate the factor description in stored lineage
    tampered_factor = DecisionFactor(
        factor_id="f1",
        factor_type="DOCUMENT",
        source_reference="handbook.pdf#p10",
        confidence_weight=0.9,
        description="Procurement limit is $1,000,000",
    )
    tracer._decisions[lineage.decision_id].factors[0] = tampered_factor

    # Verification must detect the tampering
    assert tracer.verify_integrity(lineage.decision_id) is False


# ==============================================================================
# Scenario COL-08: In-Flight Workflow Steering & Safe Pause
# ==============================================================================
def test_col08_active_steering_pause_workflow() -> None:
    """Verify operator pause of an active process workflow instance."""
    controller = SteeringController()

    event = controller.pause_workflow(
        process_instance_id="pinst_payroll_01",
        task_instance_id="task_disburse_batch",
        operator_id="compliance_director",
        reason="Suspicious employee banking account change detected",
    )

    assert event["status"] == "PAUSED_FOR_STEERING"
    assert event["process_instance_id"] == "pinst_payroll_01"
    assert controller.is_paused("pinst_payroll_01") is True

    # Attempting to inject parameters into an unpaused workflow raises error
    with pytest.raises(WorkflowNotPausedError, match="not paused for steering"):
        controller.inject_and_resume(
            process_instance_id="pinst_unpaused_99",
            task_instance_id="task_dummy",
            operator_id="operator_dan",
            parent_operation_key="op_parent_key",
            original_parameters={},
            modified_parameters={},
            reason="Illegal injection",
        )


# ==============================================================================
# Scenario COL-09: Deterministic Child Idempotency Key Derivation
# ==============================================================================
def test_col09_child_idempotency_key_derivation() -> None:
    """Verify mathematical child idempotency key derivation prevents replay."""
    controller = SteeringController()
    controller.pause_workflow(
        process_instance_id="pinst_payment_44",
        task_instance_id="task_gateway_charge",
        operator_id="operator_dan",
        reason="Rate limit mitigation",
    )

    original_params = {"amount": 25000, "currency": "USD"}
    modified_params = {"amount": 15000, "currency": "USD"}

    child_key, event = controller.inject_and_resume(
        process_instance_id="pinst_payment_44",
        task_instance_id="task_gateway_charge",
        operator_id="operator_dan",
        parent_operation_key="op_parent_uuid_77",
        original_parameters=original_params,
        modified_parameters=modified_params,
        reason="Reduced charge limit per customer request",
    )

    # Mathematical specification verification:
    # key_child = SHA256(key_parent : steering_id : SHA256(canonical_json(modified_params)))
    param_hash = hashlib.sha256(
        json.dumps(modified_params, sort_keys=True).encode("utf-8")
    ).hexdigest()
    expected_compound = f"op_parent_uuid_77:{event.steering_id}:{param_hash}"
    expected_child_key = hashlib.sha256(expected_compound.encode("utf-8")).hexdigest()

    assert child_key == expected_child_key
    assert child_key != "op_parent_uuid_77"


# ==============================================================================
# Scenario COL-10: In-Flight Parameter Modification and Execution Resumption
# ==============================================================================
def test_col10_steering_parameter_injection_resumption() -> None:
    """Verify workflow parameters are updated and process resumes cleanly."""
    controller = SteeringController()
    controller.pause_workflow(
        process_instance_id="pinst_batch_job",
        task_instance_id="task_map_reduce",
        operator_id="lead_sre",
        reason="Throttling worker concurrency",
    )

    child_key, event = controller.inject_and_resume(
        process_instance_id="pinst_batch_job",
        task_instance_id="task_map_reduce",
        operator_id="lead_sre",
        parent_operation_key="op_batch_01",
        original_parameters={"concurrency": 50},
        modified_parameters={"concurrency": 10},
        reason="Reduced concurrency to prevent database saturation",
    )

    assert controller.is_paused("pinst_batch_job") is False
    assert event.modified_parameters["concurrency"] == 10
    assert event.original_parameters["concurrency"] == 50


# ==============================================================================
# Scenario COL-11: Dynamic Capability-Restricted Policy Delegation
# ==============================================================================
def test_col11_dynamic_policy_delegation_scope() -> None:
    """Verify time-bounded and capability-restricted authority delegation envelope."""
    now = time.time()
    delegation = DelegationEnvelope(
        delegation_id="del_exec_01",
        tenant_id="tenant_corp",
        grantor_id="vp_finance",
        delegatee_id="director_finance",
        scope="EXPENSE_APPROVAL",
        constraints={"max_amount_usd": 25000, "category": "SOFTWARE_LICENSES"},
        valid_from=now - 100.0,
        valid_until=now + 3600.0,
    )

    assert delegation.is_active() is True
    assert delegation.constraints["max_amount_usd"] == 25000
    sig = delegation.compute_signature(secret="enterprise-governance-key")
    assert sig != ""
    assert len(sig) == 64


# ==============================================================================
# Scenario COL-12: Delegation Time Expiration Enforcement
# ==============================================================================
def test_col12_delegation_time_expiration_enforcement() -> None:
    """Verify delegation envelopes automatically expire past their valid_until threshold."""
    now = time.time()
    expired_delegation = DelegationEnvelope(
        delegation_id="del_expired_01",
        tenant_id="tenant_corp",
        grantor_id="vp_finance",
        delegatee_id="assistant_finance",
        scope="PURCHASE_ORDER_SIGN",
        valid_from=now - 7200.0,
        valid_until=now - 3600.0,
    )

    assert expired_delegation.is_active() is False

    # Revoked delegation is also inactive
    revoked_delegation = DelegationEnvelope(
        delegation_id="del_revoked_01",
        tenant_id="tenant_corp",
        grantor_id="vp_finance",
        delegatee_id="director_finance",
        scope="EXPENSE_APPROVAL",
        valid_from=now - 100.0,
        valid_until=now + 3600.0,
        revoked=True,
    )
    assert revoked_delegation.is_active() is False


# ==============================================================================
# Scenario COL-13: Continuous Compliance Evidence Bundle Generation
# ==============================================================================
def test_col13_compliance_bundle_generation() -> None:
    """Verify compliance bundle generation for SOC 2, HIPAA, ISO 27001, EU AI Act."""
    generator = ComplianceEvidenceGenerator(signing_secret="secops-signing-secret")

    audit_records = [
        {"action": "USER_AUTH", "user": "alice", "method": "SAML_SSO", "result": "PERMIT"},
        {
            "action": "DATA_ACCESS",
            "table": "patient_records",
            "patient_id": "p_881",
            "result": "LOGGED",
        },
        {
            "action": "AGENT_STEP",
            "agent": "clinical_coder",
            "detail": "suggest_icd10",
            "result": "VERIFIED",
        },
    ]

    bundle = generator.generate_bundle(
        tenant_id="tenant_health_01",
        framework="HIPAA",
        records=audit_records,
    )

    assert bundle.bundle_id.startswith("cmp_")
    assert bundle.framework == "HIPAA"
    assert bundle.record_count == 3
    assert bundle.root_merkle_hash != ""
    assert bundle.signature != ""


# ==============================================================================
# Scenario COL-14: HMAC-SHA256 Cryptographic Tamper Detection for Compliance Bundles
# ==============================================================================
def test_col14_hmac_sha256_compliance_signature_verification() -> None:
    """Verify HMAC-SHA256 signature guarantees tamper detection for compliance bundles."""
    generator = ComplianceEvidenceGenerator(signing_secret="regulatory-key-999")

    records = [
        {"tx_id": "tx_100", "sender": "corp_a", "amount": 100000},
        {"tx_id": "tx_101", "sender": "corp_b", "amount": 45000},
    ]

    bundle = generator.generate_bundle(
        tenant_id="tenant_bank",
        framework="SOC2",
        records=records,
    )

    assert generator.verify_bundle(bundle) is True

    # Tampering with record payload
    tampered_records = [
        {"tx_id": "tx_100", "sender": "corp_a", "amount": 99999999},
        {"tx_id": "tx_101", "sender": "corp_b", "amount": 45000},
    ]
    tampered_bundle = bundle.model_copy(update={"records": tampered_records})
    assert generator.verify_bundle(tampered_bundle) is False


# ==============================================================================
# Scenario COL-15: Hermetic Monte Carlo Policy Simulation Sandbox
# ==============================================================================
def test_col15_hermetic_monte_carlo_policy_simulation() -> None:
    """Verify Monte Carlo simulation evaluates draft policies against historical runs."""
    mock_erp = DryRunConnectorDriver("sap_erp", {"create_invoice": {"invoice_id": "inv_sim"}})
    engine = PolicySimulationEngine(connectors={"sap_erp": mock_erp})

    historical_workload = [
        {"action": "create_invoice", "parameters": {"amount_usd": 5000}},
        {"action": "create_invoice", "parameters": {"amount_usd": 75000}},
        {"action": "wire_transfer", "parameters": {"amount_usd": 25000}},
        {"action": "update_ledger", "parameters": {"account": "acc_01"}},
    ]

    draft_policy = {
        "max_amount_usd": 50000,
        "restricted_actions": ["wire_transfer"],
    }

    eval_result = engine.evaluate_draft_policy(draft_policy, historical_workload)
    assert eval_result["total_evaluated"] == 4
    assert eval_result["allowed"] == 2
    assert eval_result["approvals_required"] == 1
    assert eval_result["denied"] == 1
    assert eval_result["safe_for_deployment"] is False


# ==============================================================================
# Scenario COL-16: Simulation Sandbox Firewall Guard
# ==============================================================================
def test_col16_simulation_sandbox_violation_guard() -> None:
    """Verify attempting to inject live external drivers into simulation is blocked."""

    class LiveProductionDatabaseConnector:
        def execute(self, sql: str) -> None:
            pass

    with pytest.raises(
        SimulationSandboxViolationError, match="must be an instance of DryRunConnectorDriver"
    ):
        PolicySimulationEngine(connectors={"prod_db": LiveProductionDatabaseConnector()})  # type: ignore


# ==============================================================================
# Scenario COL-17: FastAPI REST Control Plane Endpoints
# ==============================================================================
def test_col17_rest_api_collaboration_endpoints() -> None:
    """Verify FastAPI routes for workspaces, turn leasing, steering, and compliance."""
    from atlas_api.main import app

    client = TestClient(app)

    # 1. Create workspace session
    res_create = client.post(
        "/api/v1/workspaces/sessions",
        json={
            "tenant_id": "tenant_api_test",
            "workspace_name": "API Acceptance Workspace",
            "owner_identity": "api_admin",
        },
    )
    assert res_create.status_code == 201
    sid = res_create.json()["session_id"]

    # 2. Acquire lease
    res_lease = client.post(
        f"/api/v1/workspaces/sessions/{sid}/lease",
        json={"identity": "api_admin", "duration_seconds": 60.0},
    )
    assert res_lease.status_code == 200
    assert res_lease.json()["holder_identity"] == "api_admin"
    assert res_lease.json()["fencing_token"] == 1

    # 3. Steering pause
    res_pause = client.post(
        "/api/v1/instances/pinst_api_01/steering/pause",
        json={
            "task_instance_id": "task_api_01",
            "operator_id": "api_admin",
            "reason": "Test pause",
        },
    )
    assert res_pause.status_code == 200
    assert res_pause.json()["status"] == "PAUSED_FOR_STEERING"

    # 4. Steering resume
    res_resume = client.post(
        "/api/v1/instances/pinst_api_01/steering/resume",
        json={
            "task_instance_id": "task_api_01",
            "operator_id": "api_admin",
            "parent_operation_key": "op_parent_api_99",
            "original_parameters": {"x": 1},
            "modified_parameters": {"x": 2},
            "reason": "Parameter updated",
        },
    )
    assert res_resume.status_code == 200
    assert res_resume.json()["status"] == "RESUMED"

    # 5. Generate compliance bundle
    res_comp = client.post(
        "/api/v1/governance/compliance/bundles",
        json={
            "tenant_id": "tenant_api_test",
            "framework": "SOC2",
            "records": [{"audit": "verified"}],
        },
    )
    assert res_comp.status_code == 200
    assert res_comp.json()["framework"] == "SOC2"


# ==============================================================================
# Scenario COL-18: CLI Collaboration Subcommands E2E
# ==============================================================================
def test_col18_cli_collaboration_commands_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify executing CLI collaboration commands (workspace, steering, compliance)."""
    storage = CollaborationStorage(db_path=tmp_path / "cli_acc_test.db")
    monkeypatch.setattr("atlas_cli.commands.collaboration._get_local_storage", lambda: storage)

    # 1. atlas workspace create
    assert run_workspace_create("Acceptance Project", tenant_id="tenant_e2e") == 0
    out = capsys.readouterr().out
    assert "Workspace created successfully" in out

    # 2. atlas workspace list
    assert run_workspace_list() == 0
    list_out = capsys.readouterr().out
    assert "Acceptance Project" in list_out

    workspaces = storage.list_workspaces()
    assert len(workspaces) >= 1
    ws_id = workspaces[0]["workspace_id"]

    # 3. atlas steering pause
    assert run_steering_pause(ws_id, reason="Testing pause") == 0
    pause_out = capsys.readouterr().out
    assert "PAUSED" in pause_out

    # 4. atlas steering resume
    assert run_steering_resume(ws_id, params_json='{"key": "val"}') == 0
    resume_out = capsys.readouterr().out
    assert "resumed" in resume_out.lower()
    assert "Child Idempotency Key" in resume_out


# ==============================================================================
# Scenario COL-19: Operator Control Plane Web Dashboard E2E
# ==============================================================================
def test_col19_web_operator_dashboard_collaboration_hub() -> None:
    """Verify Phase 17 Collaboration & Compliance Hub is rendered in operator dashboard."""
    from atlas_api.main import app

    client = TestClient(app)
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.text

    # Verify Collaboration & Compliance Hub elements
    assert "Collaboration &amp; Compliance" in html or "Collaboration & Compliance" in html
    assert "Active Turn-Lock Lease" in html
    assert "Human Turn Preemption" in html
    assert "In-Flight Workflow Steering" in html
    assert "Continuous Compliance Bundles" in html
    assert "Download Bundle (.JSON)" in html


# ==============================================================================
# Scenario COL-20: Enterprise Relational Database Migrations 019 & 020 Integration
# ==============================================================================
def test_col20_database_migrations_019_and_020_integration(tmp_path: Path) -> None:
    """Verify database migrations 019 and 020 tables and constraints in CollaborationStorage."""
    from atlas_collaboration.models import AgentDecisionLineage, DecisionFactor, TurnLease

    storage = CollaborationStorage(db_path=tmp_path / "collab_acc.db")

    # 1. Workspace and Collaborator
    storage.save_workspace("ws_acc_20", "Schema Integrity Test", "tenant_db")
    storage.add_collaborator("ws_acc_20", "lead_dev", WorkspaceRole.OWNER)
    storage.add_collaborator("ws_acc_20", "agent_db", WorkspaceRole.AUTONOMOUS_WORKER)

    fetched = storage.get_workspace("ws_acc_20")
    assert fetched is not None
    assert len(fetched["collaborators"]) == 2

    # 2. Turn Lease persistence
    lease = TurnLease(
        lease_id="lease_acc_20",
        workspace_id="ws_acc_20",
        holder_identity="lead_dev",
        holder_role=WorkspaceRole.OWNER,
        expires_at=time.time() + 60.0,
        fencing_token=1,
        is_human=True,
    )
    storage.save_lease(lease)
    active = storage.get_active_lease("ws_acc_20")
    assert active is not None
    assert active.holder_identity == "lead_dev"
    assert active.fencing_token == 1

    # 3. Decision Lineage
    factor = DecisionFactor(
        factor_id="f_acc",
        factor_type="POLICY",
        source_reference="db_policy",
        confidence_weight=1.0,
        description="Integrity test factor",
    )
    lineage = AgentDecisionLineage(
        decision_id="dec_acc_20",
        tenant_id="tenant_db",
        agent_id="agent_db",
        task_instance_id="task_acc_20",
        selected_action="verify_schema",
        rationale="Schema verification successful",
        factors=[factor],
    )
    storage.save_decision_lineage(lineage)
    lineages = storage.list_decision_lineages("task_acc_20")
    assert len(lineages) == 1
    assert lineages[0].decision_id == "dec_acc_20"
