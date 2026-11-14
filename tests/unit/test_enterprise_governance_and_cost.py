"""Unit tests for Enterprise Audit Ledger, Cost Management, Budgets, and Analytics (Milestone 5)."""

import pytest
from atlas_enterprise import (
    AuditTamperDetectedError,
    BudgetCapExceededError,
    EnterpriseAnalyticsEngine,
    EnterpriseAuditLedger,
    EnterpriseCostManager,
    EnterpriseIAMEngine,
    EnterpriseOrganizationManager,
)


@pytest.fixture
def org_manager() -> EnterpriseOrganizationManager:
    return EnterpriseOrganizationManager()


@pytest.fixture
def iam_engine(org_manager: EnterpriseOrganizationManager) -> EnterpriseIAMEngine:
    return EnterpriseIAMEngine(org_manager=org_manager)


@pytest.fixture
def audit_ledger(
    org_manager: EnterpriseOrganizationManager,
    iam_engine: EnterpriseIAMEngine,
) -> EnterpriseAuditLedger:
    return EnterpriseAuditLedger(org_manager=org_manager, iam_engine=iam_engine)


@pytest.fixture
def cost_manager(
    org_manager: EnterpriseOrganizationManager,
    iam_engine: EnterpriseIAMEngine,
) -> EnterpriseCostManager:
    return EnterpriseCostManager(org_manager=org_manager, iam_engine=iam_engine)


@pytest.fixture
def analytics_engine(
    org_manager: EnterpriseOrganizationManager,
    iam_engine: EnterpriseIAMEngine,
    audit_ledger: EnterpriseAuditLedger,
    cost_manager: EnterpriseCostManager,
) -> EnterpriseAnalyticsEngine:
    return EnterpriseAnalyticsEngine(
        org_manager=org_manager,
        iam_engine=iam_engine,
        audit_ledger=audit_ledger,
        cost_manager=cost_manager,
    )


def test_immutable_audit_hash_chaining(
    org_manager: EnterpriseOrganizationManager,
    audit_ledger: EnterpriseAuditLedger,
) -> None:
    """Verify append-only audit records form an unbroken SHA-256 hash chain."""
    org, owner, _ = org_manager.create_organization(
        name="SecurityCorp", slug="seccorp", owner_email="admin@seccorp.com", owner_name="Admin"
    )

    r1 = audit_ledger.append_entry(
        org_id=org.org_id,
        event_type="IAM_LOGIN",
        actor_id=owner.user_id,
        actor_type="USER",
        action="login.success",
        details={"ip": "10.0.0.1"},
    )
    assert r1.sequence == 1
    assert r1.previous_hash == "0" * 64
    assert len(r1.record_hash) == 64

    r2 = audit_ledger.append_entry(
        org_id=org.org_id,
        event_type="AGENT_REGISTERED",
        actor_id=owner.user_id,
        actor_type="USER",
        action="agent.create",
        details={"agent_name": "AuditBot"},
    )
    assert r2.sequence == 2
    assert r2.previous_hash == r1.record_hash

    r3 = audit_ledger.append_entry(
        org_id=org.org_id,
        event_type="WORKFLOW_EXECUTED",
        actor_id="ag_audit_bot",
        actor_type="AGENT",
        action="workflow.run",
        details={"workflow_id": "wf_123"},
    )
    assert r3.sequence == 3
    assert r3.previous_hash == r2.record_hash

    # Verify entire chain integrity
    is_intact, broken_seq, reason = audit_ledger.verify_chain_integrity(org.org_id)
    assert is_intact is True
    assert broken_seq is None
    assert reason is None


def test_audit_chain_tamper_detection(
    org_manager: EnterpriseOrganizationManager,
    audit_ledger: EnterpriseAuditLedger,
) -> None:
    """Verify that tampering with any historical audit entry is immediately detected."""
    org, owner, _ = org_manager.create_organization(
        name="TamperTestOrg", slug="ttorg", owner_email="admin@ttorg.com", owner_name="Admin"
    )

    # Append 3 legitimate entries
    for i in range(3):
        audit_ledger.append_entry(
            org_id=org.org_id,
            event_type="POLICY_EVAL",
            actor_id=owner.user_id,
            actor_type="USER",
            action=f"eval.action.{i}",
            details={"step": i},
        )

    # Verify baseline is intact
    is_intact, _, _ = audit_ledger.verify_chain_integrity(org.org_id)
    assert is_intact is True

    # Maliciously mutate record 2's action directly in stored memory
    chain = audit_ledger._chains[org.org_id]
    chain[1].action = "eval.action.MALICIOUS_ALTERATION"

    # Integrity verification catches the tamper
    is_intact, broken_seq, reason = audit_ledger.verify_chain_integrity(org.org_id)
    assert is_intact is False
    assert broken_seq == 2
    assert "Record hash mismatch" in reason

    # Exporting tampered audit trail raises AuditTamperDetectedError
    with pytest.raises(AuditTamperDetectedError):
        audit_ledger.export_audit_trail(caller_user_id=owner.user_id, org_id=org.org_id)


def test_measured_cost_attribution_and_model_pricing(
    org_manager: EnterpriseOrganizationManager,
    cost_manager: EnterpriseCostManager,
) -> None:
    """Verify accurate cost calculation across models and compute duration."""
    org, _, _ = org_manager.create_organization(
        name="CostCorp", slug="costcorp", owner_email="cfo@costcorp.com", owner_name="CFO"
    )

    # 1. Gemini Pro: 10,000 prompt tokens ($0.035) + 2,000 completion ($0.021) + 5,000ms compute ($0.0001)
    rec, is_alert = cost_manager.record_usage(
        org_id=org.org_id,
        task_id="task_gemini_1",
        model_name="gemini-1.5-pro",
        prompt_tokens=10_000,
        completion_tokens=2_000,
        compute_duration_ms=5_000,
    )
    assert rec.total_tokens == 12_000
    assert rec.token_cost_usd == pytest.approx(0.056, abs=1e-4)
    assert rec.compute_cost_usd == pytest.approx(0.0001, abs=1e-5)
    assert rec.total_cost_usd == pytest.approx(0.0561, abs=1e-4)
    assert is_alert is False


def test_department_budget_envelope_and_hard_cap(
    org_manager: EnterpriseOrganizationManager,
    cost_manager: EnterpriseCostManager,
) -> None:
    """Verify departmental budget tracking, alert thresholds, and hard spending caps."""
    org, owner, _ = org_manager.create_organization(
        name="FinBank", slug="finbank", owner_email="admin@finbank.com", owner_name="Admin"
    )
    dept = org_manager.create_department(org_id=org.org_id, name="Risk", slug="risk")

    # Set budget of $10.00 with 80% alert threshold and hard cap
    budget = cost_manager.set_department_budget(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        department_id=dept.department_id,
        allocated_usd=10.0,
        alert_threshold_pct=80.0,
        hard_cap_enabled=True,
    )
    assert budget.allocated_usd == 10.0
    assert budget.spent_usd == 0.0

    # 1. Spend $6.00 (60%) -> No alert
    _, is_alert = cost_manager.record_usage(
        org_id=org.org_id,
        department_id=dept.department_id,
        task_id="t1",
        model_name="gpt-4o",
        prompt_tokens=1_000_000,  # 1000 * 0.005 = $5.00
        completion_tokens=66_667,  # 66.667 * 0.015 = $1.00
        compute_duration_ms=0,
    )
    assert is_alert is False
    assert budget.spent_usd == pytest.approx(6.00, abs=0.01)

    # 2. Spend $2.50 (Total: $8.50 = 85%) -> Alert triggered!
    _, is_alert = cost_manager.record_usage(
        org_id=org.org_id,
        department_id=dept.department_id,
        task_id="t2",
        model_name="gpt-4o",
        prompt_tokens=500_000,  # $2.50
        completion_tokens=0,
        compute_duration_ms=0,
    )
    assert is_alert is True
    assert budget.spent_usd == pytest.approx(8.50, abs=0.01)

    # 3. Spend $2.00 (Total: $10.50 > $10.00) -> Breaches hard cap!
    with pytest.raises(BudgetCapExceededError):
        cost_manager.record_usage(
            org_id=org.org_id,
            department_id=dept.department_id,
            task_id="t3",
            model_name="gpt-4o",
            prompt_tokens=400_000,  # $2.00
            completion_tokens=0,
            compute_duration_ms=0,
        )


def test_enterprise_operational_analytics(
    org_manager: EnterpriseOrganizationManager,
    audit_ledger: EnterpriseAuditLedger,
    cost_manager: EnterpriseCostManager,
    analytics_engine: EnterpriseAnalyticsEngine,
) -> None:
    """Verify aggregated operational performance, worker utilization, and compliance score."""
    org, owner, _ = org_manager.create_organization(
        name="MetricsCorp",
        slug="metricscorp",
        owner_email="boss@metricscorp.com",
        owner_name="Boss",
    )

    # Add audit records
    audit_ledger.append_entry(org.org_id, "TASK_COMPLETE", "worker_1", "SERVICE", "task.finish")
    audit_ledger.append_entry(org.org_id, "TASK_COMPLETE", "worker_2", "SERVICE", "task.finish")

    # Add cost usage
    cost_manager.record_usage(
        org_id=org.org_id,
        task_id="t_100",
        model_name="claude-3-5-sonnet",
        prompt_tokens=5000,
        completion_tokens=1000,
        compute_duration_ms=2000,
    )

    metrics = analytics_engine.get_operational_metrics(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
    )

    assert metrics["audit_chain_verified"] is True
    assert metrics["compliance_score"] == 100.0
    assert metrics["total_audit_events"] == 2
    assert metrics["cost_and_usage"]["total_spend_usd"] > 0.0
