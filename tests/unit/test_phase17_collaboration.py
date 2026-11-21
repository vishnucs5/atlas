"""Unit tests for Phase 17 Human-AI Collaboration, Explainability & Governance."""

import hashlib
import json

import pytest
from atlas_collaboration.compliance import ComplianceEvidenceGenerator
from atlas_collaboration.explainability import CausalDecisionTracer
from atlas_collaboration.models import DecisionFactor, WorkspaceRole
from atlas_collaboration.simulation import (
    DryRunConnectorDriver,
    PolicySimulationEngine,
    SimulationSandboxViolationError,
)
from atlas_collaboration.steering import (
    SteeringController,
    WorkflowNotPausedError,
)
from atlas_collaboration.workspace import (
    CollaborativeWorkspaceHub,
    FencingTokenInvalidError,
    TurnLeaseConflictError,
)


# ==============================================================================
# 1. Collaborative Workspace & Human Preemption Tests
# ==============================================================================
def test_workspace_session_creation_and_snapshot():
    """Verify collaborative session initialization and state snapshot."""
    hub = CollaborativeWorkspaceHub()
    session = hub.create_session(
        tenant_id="tenant_eng_01",
        workspace_name="Backend Architecture Review",
        owner_identity="lead_architect",
    )
    assert session.session_id.startswith("ws_sess_")
    assert "lead_architect" in session.collaborators
    assert session.collaborators["lead_architect"].role == WorkspaceRole.OWNER

    # Join an autonomous worker
    hub.join_session(
        session_id=session.session_id,
        identity="agent_coder_01",
        role=WorkspaceRole.AUTONOMOUS_WORKER,
        is_human=False,
    )
    snapshot = hub.get_snapshot(session.session_id)
    assert snapshot["collaborator_count"] == 2
    assert snapshot["sequence_id"] == 0


def test_workspace_semantic_turn_locking_and_human_preemption():
    """Verify semantic turn-locking and immediate human preemptive override of agents."""
    hub = CollaborativeWorkspaceHub()
    session = hub.create_session(
        tenant_id="tenant_fin_01",
        workspace_name="Budget Planning",
        owner_identity="finance_director",
    )
    sid = session.session_id

    hub.join_session(
        sid, identity="agent_math_01", role=WorkspaceRole.AUTONOMOUS_WORKER, is_human=False
    )
    hub.join_session(
        sid, identity="agent_math_02", role=WorkspaceRole.AUTONOMOUS_WORKER, is_human=False
    )

    # 1. Agent acquires turn lease
    lease_agent = hub.acquire_turn_lease(sid, identity="agent_math_01", duration_seconds=60.0)
    assert lease_agent.holder_identity == "agent_math_01"
    assert lease_agent.fencing_token == 1
    assert lease_agent.is_human is False

    # 2. Another agent attempts to acquire lease -> conflict
    with pytest.raises(TurnLeaseConflictError, match="Turn lease is actively held"):
        hub.acquire_turn_lease(sid, identity="agent_math_02")

    # 3. Agent mutates artifact successfully with valid token
    seq = hub.mutate_artifact(
        sid, "agent_math_01", lease_agent.fencing_token, "sheet_a", {"val": 100}
    )
    assert seq == 1

    # 4. Human operator requests edit -> Preempts the agent immediately!
    lease_human = hub.acquire_turn_lease(sid, identity="finance_director", duration_seconds=60.0)
    assert lease_human.holder_identity == "finance_director"
    assert lease_human.fencing_token == 2
    assert lease_human.is_human is True
    assert lease_agent.preempted is True

    # 5. Preempted agent attempt to mutate artifact fails with FencingTokenInvalidError
    with pytest.raises(FencingTokenInvalidError, match="superseded"):
        hub.mutate_artifact(
            sid, "agent_math_01", lease_agent.fencing_token, "sheet_a", {"val": 999}
        )

    # 6. Human mutates artifact successfully
    seq2 = hub.mutate_artifact(
        sid, "finance_director", lease_human.fencing_token, "sheet_a", {"val": 500}
    )
    assert seq2 == 2


# ==============================================================================
# 2. Causal Decision Lineage & Explainability Tests
# ==============================================================================
def test_causal_decision_tracing_and_merkle_integrity():
    """Verify Merkle root calculation and content-addressable storage (CAS) integrity."""
    tracer = CausalDecisionTracer()
    factor1 = DecisionFactor(
        factor_id="f1",
        factor_type="DOCUMENT",
        source_reference="docs/security_policy.pdf#p4",
        confidence_weight=0.95,
        description="Password must require 14+ characters",
    )
    factor2 = DecisionFactor(
        factor_id="f2",
        factor_type="POLICY_RULE",
        source_reference="rule_require_mfa",
        confidence_weight=0.99,
        description="MFA required for admin roles",
    )

    lineage = tracer.record_decision(
        tenant_id="tenant_sec_01",
        agent_id="agent_security_01",
        task_instance_id="task_audit_99",
        selected_action="enforce_mfa",
        rationale="Admin role detected in request without MFA token",
        factors=[factor1, factor2],
        policy_checks_passed=["rule_require_mfa"],
        context_payload={"requested_role": "admin", "has_mfa": False},
    )

    assert lineage.decision_id.startswith("dec_")
    assert lineage.merkle_root_hash != ""
    assert lineage.cas_ref is not None
    assert lineage.cas_ref.uri.startswith("atlas-cas://")

    # Integrity check passes
    assert tracer.verify_integrity(lineage.decision_id) is True

    # Causal chain query
    chain = tracer.get_task_causal_chain("task_audit_99")
    assert len(chain) == 1
    assert chain[0].decision_id == lineage.decision_id


# ==============================================================================
# 3. Active Human Steering & Child Idempotency Key Derivation Tests
# ==============================================================================
def test_steering_controller_pause_and_child_key_derivation():
    """Verify operator pause, modified parameter injection, and mathematical child key."""
    controller = SteeringController()

    # Attempting to inject into an unpaused workflow fails
    with pytest.raises(WorkflowNotPausedError):
        controller.inject_and_resume(
            process_instance_id="pinst_wire_01",
            task_instance_id="task_wire_10",
            operator_id="operator_dan",
            parent_operation_key="op_parent_abc",
            original_parameters={"amount": 100000},
            modified_parameters={"amount": 50000},
            reason="High value limit adjustment",
        )

    # 1. Operator pauses workflow
    controller.pause_workflow(
        process_instance_id="pinst_wire_01",
        task_instance_id="task_wire_10",
        operator_id="operator_dan",
        reason="Invoice verification needed",
    )
    assert controller.is_paused("pinst_wire_01") is True

    # 2. Operator injects modified parameters and resumes
    child_key, event = controller.inject_and_resume(
        process_instance_id="pinst_wire_01",
        task_instance_id="task_wire_10",
        operator_id="operator_dan",
        parent_operation_key="op_parent_abc",
        original_parameters={"amount": 100000},
        modified_parameters={"amount": 50000},
        reason="Lowered wire amount after supplier confirmation",
    )

    assert controller.is_paused("pinst_wire_01") is False
    assert event.child_operation_key == child_key
    assert child_key != "op_parent_abc"

    # Verify mathematical key derivation matches specification
    param_hash = hashlib.sha256(
        json.dumps({"amount": 50000}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    expected_compound = f"op_parent_abc:{event.steering_id}:{param_hash}"
    expected_key = hashlib.sha256(expected_compound.encode("utf-8")).hexdigest()
    assert child_key == expected_key


# ==============================================================================
# 4. Continuous Compliance Evidence Bundle Tests
# ==============================================================================
def test_compliance_evidence_generator_and_tamper_detection():
    """Verify cryptographic compliance bundle generation and tamper detection."""
    gen = ComplianceEvidenceGenerator(signing_secret="test-audit-key")

    records = [
        {"action": "LOGIN", "user": "admin", "ip": "10.0.0.1", "status": "SUCCESS"},
        {"action": "TRANSFER", "amount": 500, "currency": "USD", "status": "APPROVED"},
        {"action": "EXPORT", "dataset": "financial_records", "status": "LOGGED"},
    ]

    bundle = gen.generate_bundle(
        tenant_id="tenant_audit_01",
        framework="SOC2",
        records=records,
    )

    assert bundle.framework == "SOC2"
    assert bundle.record_count == 3
    assert gen.verify_bundle(bundle) is True

    # Tampering test: modify a single attribute in records
    tampered_records = list(records)
    tampered_records[0] = {"action": "LOGIN", "user": "admin", "ip": "10.0.0.1", "status": "FAILED"}
    tampered_bundle = bundle.model_copy(update={"records": tampered_records})

    # Tampered bundle fails verification
    assert gen.verify_bundle(tampered_bundle) is False


# ==============================================================================
# 5. Hermetic Policy Simulation Sandbox Tests
# ==============================================================================
def test_policy_simulation_engine_dry_run_and_sandbox_violation():
    """Verify policy simulation evaluates historical runs safely without side effects."""
    mock_connector = DryRunConnectorDriver("erp", {"create_po": {"po_id": "sim_123"}})
    engine = PolicySimulationEngine(connectors={"erp": mock_connector})

    historical = [
        {"action": "create_po", "parameters": {"amount_usd": 15000}},
        {"action": "create_po", "parameters": {"amount_usd": 65000}},
        {"action": "wire_transfer", "parameters": {"amount_usd": 10000}},
    ]

    # Evaluate draft policy: POs > $50,000 require approval; wire_transfer restricted
    rule = {
        "max_amount_usd": 50000,
        "restricted_actions": ["wire_transfer"],
    }

    result = engine.evaluate_draft_policy(rule, historical)
    assert result["total_evaluated"] == 3
    assert result["allowed"] == 1
    assert result["approvals_required"] == 1
    assert result["denied"] == 1
    assert result["safe_for_deployment"] is False

    # Sandbox violation test: Passing a non-dry-run driver fails closed
    with pytest.raises(
        SimulationSandboxViolationError, match="must be an instance of DryRunConnectorDriver"
    ):
        PolicySimulationEngine(connectors={"live_erp": object()})  # type: ignore
