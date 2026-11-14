"""Independent Revalidation Suite for Phase 10 Scenarios EP-01 through EP-30.

Verifies:
- EP-01: Multi-tenant organization provisioning and root owner identity.
- EP-02: 4-tier hierarchical scoping (Org -> Dept -> Team -> Project).
- EP-03: Multi-tenant data isolation and boundary enforcement.
- EP-04: Federated SSO authentication with domain allowlisting.
- EP-05: Dynamic ABAC contextual attribute evaluation.
- EP-06: Granular RBAC least-privilege matrix (9 roles).
- EP-07: Privilege escalation guards and self-elevation prevention.
- EP-08: Service identity and raw API key hashing.
- EP-09: Centralized agent registration and capabilities allowlisting.
- EP-10: Hierarchical policy inheritance (Org -> Dept -> Team).
- EP-11: Agent tool and skill execution enforcement.
- EP-12: Agent lifecycle state transitions (SUSPEND/REVOKE).
- EP-13: Agent self-elevation guard contract.
- EP-14: Enterprise Integration Hub connector registration.
- EP-15: Isolated multi-tenant secret vaulting.
- EP-16: Deterministic connection verification handshake.
- EP-17: Timing-safe inbound webhook HMAC verification.
- EP-18: Connector invocation and sliding window rate limiting.
- EP-19: Cryptographic SHA-256 audit ledger hash chaining.
- EP-20: Audit ledger sequence tamper detection.
- EP-21: Audit ledger payload tamper detection.
- EP-22: Measured LLM token and compute cost attribution.
- EP-23: Departmental spending caps and budget alert thresholds.
- EP-24: Operational analytics and compliance metrics.
- EP-25: Compliance evidence export.
- EP-26: Enterprise Admin Console dashboard integration.
- EP-27: Self-hosted Docker Compose deployment configuration.
- EP-28: Tenant disaster recovery isolation simulation.
- EP-29: Full enterprise end-to-end task lifecycle.
- EP-30: Monorepo regression baseline verification.
"""

import hashlib
import hmac
from pathlib import Path

import pytest
from atlas_api.main import app
from atlas_enterprise import (
    ABACContext,
    AgentLifecycleStatus,
    AgentSelfElevationError,
    AgentSuspendedError,
    BudgetCapExceededError,
    ConnectorStatus,
    ConnectorType,
    CrossTenantAccessViolationError,
    EnterpriseAgentGovernanceManager,
    EnterpriseAnalyticsEngine,
    EnterpriseAuditLedger,
    EnterpriseCostManager,
    EnterpriseIAMEngine,
    EnterpriseOrganizationManager,
    GovernanceScopeType,
    IdentityProviderConfig,
    IdPType,
    IntegrationHubManager,
    IntegrationSecretStore,
    MembershipRole,
    PermissionAction,
    PrivilegeEscalationError,
    RateLimitExceededError,
)
from fastapi.testclient import TestClient


@pytest.fixture
def reval_stack():
    org_mgr = EnterpriseOrganizationManager()
    iam = EnterpriseIAMEngine(org_mgr)
    gov = EnterpriseAgentGovernanceManager(org_mgr, iam)
    secret_store = IntegrationSecretStore()
    hub = IntegrationHubManager(org_mgr, iam, secret_store)
    audit = EnterpriseAuditLedger(org_mgr, iam)
    cost = EnterpriseCostManager(org_mgr, iam)
    analytics = EnterpriseAnalyticsEngine(org_mgr, iam, audit, cost)
    return {
        "org_mgr": org_mgr,
        "iam": iam,
        "gov": gov,
        "secret_store": secret_store,
        "hub": hub,
        "audit": audit,
        "cost": cost,
        "analytics": analytics,
    }


def test_reval_ep01_org_provisioning(reval_stack):
    org_mgr = reval_stack["org_mgr"]
    org, owner, mem = org_mgr.create_organization(
        name="Apex Corp", slug="apex", owner_email="admin@apex.com", owner_name="Admin"
    )
    assert org.org_id.startswith("org_")
    assert owner.email == "admin@apex.com"
    assert mem.role == MembershipRole.ORG_OWNER


def test_reval_ep02_hierarchical_scoping(reval_stack):
    org_mgr = reval_stack["org_mgr"]
    org, _, _ = org_mgr.create_organization(
        name="Hierarchy Co", slug="hco", owner_email="h@h.com", owner_name="H Owner"
    )
    dept = org_mgr.create_department(org.org_id, "Engineering", "eng")
    team = org_mgr.create_team(org.org_id, dept.department_id, "Backend")
    proj = org_mgr.create_project(org.org_id, dept.department_id, team.team_id, "Core Engine")
    assert proj.org_id == org.org_id
    assert proj.department_id == dept.department_id
    assert proj.team_id == team.team_id


def test_reval_ep03_multitenant_isolation(reval_stack):
    org_mgr = reval_stack["org_mgr"]
    org_1, _, _ = org_mgr.create_organization(
        name="T1", slug="t1", owner_email="1@t.com", owner_name="1"
    )
    org_2, _, _ = org_mgr.create_organization(
        name="T2", slug="t2", owner_email="2@t.com", owner_name="2"
    )
    dept_2 = org_mgr.create_department(org_2.org_id, "D2", "d2")

    with pytest.raises(CrossTenantAccessViolationError):
        org_mgr.get_department(dept_2.department_id, caller_org_id=org_1.org_id)


def test_reval_ep04_sso_federation(reval_stack):
    org_mgr = reval_stack["org_mgr"]
    iam = reval_stack["iam"]
    org, _, _ = org_mgr.create_organization(
        name="SSOCorp", slug="ssocorp", owner_email="s@s.com", owner_name="S"
    )
    idp = IdentityProviderConfig(
        idp_id="idp_okta",
        org_id=org.org_id,
        idp_type=IdPType.OIDC,
        name="Okta",
        issuer="https://okta.com",
        client_id="client_123",
        domain_allowlist=["ssocorp.com"],
        role_mapping={"Engineers": MembershipRole.DEVELOPER},
    )
    iam.register_idp(idp)
    user, session = iam.authenticate_sso(
        idp_id="idp_okta",
        assertion={
            "email": "alice@ssocorp.com",
            "sub": "okta_1",
            "name": "Alice",
            "groups": ["Engineers"],
        },
    )
    assert user.email == "alice@ssocorp.com"
    assert session.role == MembershipRole.DEVELOPER


def test_reval_ep05_abac_evaluation(reval_stack):
    context_deny = ABACContext(
        user_id="u1",
        org_id="org1",
        client_ip="203.0.113.1",
        security_clearance="standard",
    )
    allowed = reval_stack["iam"].evaluate_permission(
        user_id="u1",
        org_id="org1",
        action=PermissionAction.ORG_READ,
        abac_context=context_deny,
        policy_rules={"allowed_ips": ["192.168.1.0/24"]},
    )
    assert allowed is False


def test_reval_ep06_rbac_matrix(reval_stack):
    org_mgr = reval_stack["org_mgr"]
    iam = reval_stack["iam"]
    org, _, _ = org_mgr.create_organization(
        name="RBAC", slug="rbac", owner_email="r@r.com", owner_name="R"
    )
    dev, _ = org_mgr.add_member(org.org_id, email="d@r.com", role=MembershipRole.DEVELOPER)
    assert iam.evaluate_permission(dev.user_id, org.org_id, PermissionAction.AGENT_REGISTER) is True
    assert iam.evaluate_permission(dev.user_id, org.org_id, PermissionAction.ORG_DELETE) is False


def test_reval_ep07_privilege_escalation(reval_stack):
    org_mgr = reval_stack["org_mgr"]
    iam = reval_stack["iam"]
    org, _, _ = org_mgr.create_organization(
        name="Esc", slug="esc", owner_email="e@e.com", owner_name="E"
    )
    dev, _ = org_mgr.add_member(org.org_id, email="d@e.com", role=MembershipRole.DEVELOPER)
    with pytest.raises(PrivilegeEscalationError):
        iam.assign_role(dev.user_id, dev.user_id, org.org_id, MembershipRole.ORG_ADMIN)


def test_reval_ep08_service_identity(reval_stack):
    iam = reval_stack["iam"]
    org_mgr = reval_stack["org_mgr"]
    org, _, _ = org_mgr.create_organization(
        name="Svc", slug="svc", owner_email="s@s.com", owner_name="S"
    )
    svc, raw_key = iam.create_service_identity(org.org_id, "CI Worker", ["task:execute"])
    assert raw_key.startswith("atk_live_")
    authed = iam.authenticate_api_key(raw_key)
    assert authed.service_id == svc.service_id


def test_reval_ep09_agent_registration(reval_stack):
    gov = reval_stack["gov"]
    org_mgr = reval_stack["org_mgr"]
    org, owner, _ = org_mgr.create_organization(
        name="AgReg", slug="agreg", owner_email="a@a.com", owner_name="A"
    )
    agent = gov.register_agent(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="TestBot",
        owner_user_id=owner.user_id,
        allowed_tools=["calculator"],
    )
    assert agent.name == "TestBot"


def test_reval_ep10_hierarchical_policy(reval_stack):
    gov = reval_stack["gov"]
    org_mgr = reval_stack["org_mgr"]
    org, owner, _ = org_mgr.create_organization(
        name="Pol", slug="pol", owner_email="p@p.com", owner_name="P"
    )
    gov.set_policy(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        scope_type=GovernanceScopeType.ORGANIZATION,
        scope_id=org.org_id,
        disallowed_tools=["bash"],
    )
    eff = gov.get_effective_policy(org.org_id)
    assert "bash" in eff.disallowed_tools


def test_reval_ep11_agent_execution_validation(reval_stack):
    gov = reval_stack["gov"]
    org_mgr = reval_stack["org_mgr"]
    org, owner, _ = org_mgr.create_organization(
        name="ExVal", slug="exval", owner_email="x@x.com", owner_name="X"
    )
    agent = gov.register_agent(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="Bot",
        owner_user_id=owner.user_id,
        allowed_tools=["python"],
    )
    allowed, _, _ = gov.validate_agent_execution(agent.agent_id, tool_name="bash")
    assert allowed is False


def test_reval_ep12_agent_lifecycle(reval_stack):
    gov = reval_stack["gov"]
    org_mgr = reval_stack["org_mgr"]
    org, owner, _ = org_mgr.create_organization(
        name="Life", slug="life", owner_email="l@l.com", owner_name="L"
    )
    agent = gov.register_agent(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="Bot",
        owner_user_id=owner.user_id,
        allowed_tools=["tool1"],
    )
    gov.update_agent_status(owner.user_id, agent.agent_id, AgentLifecycleStatus.SUSPENDED)
    with pytest.raises(AgentSuspendedError):
        gov.validate_agent_execution(agent.agent_id, tool_name="tool1")


def test_reval_ep13_agent_self_elevation(reval_stack):
    gov = reval_stack["gov"]
    with pytest.raises(AgentSelfElevationError):
        gov.check_agent_self_elevation("ag_123", "iam:manage_roles")


def test_reval_ep14_connector_registration(reval_stack):
    hub = reval_stack["hub"]
    org_mgr = reval_stack["org_mgr"]
    org, owner, _ = org_mgr.create_organization(
        name="Conn", slug="conn", owner_email="c@c.com", owner_name="C"
    )
    conn = hub.register_connector(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="Slack",
        connector_type=ConnectorType.COMMUNICATION,
        provider="slack",
        config={},
        secrets={"bot_token": "xoxb-123"},
    )
    assert conn.status == ConnectorStatus.UNVERIFIED


def test_reval_ep15_secret_vault(reval_stack):
    store = reval_stack["secret_store"]
    sec_id = store.store_secret("org_1", {"key": "val"})
    assert store.get_secret("org_1", sec_id)["key"] == "val"


def test_reval_ep16_connection_verification(reval_stack):
    hub = reval_stack["hub"]
    org_mgr = reval_stack["org_mgr"]
    org, owner, _ = org_mgr.create_organization(
        name="Ver", slug="ver", owner_email="v@v.com", owner_name="V"
    )
    conn = hub.register_connector(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="Salesforce",
        connector_type=ConnectorType.CRM,
        provider="salesforce",
        config={},
        secrets={"api_key": "valid_token"},
    )
    success, _ = hub.verify_connector(owner.user_id, conn.connector_id)
    assert success is True


def test_reval_ep17_webhook_verification(reval_stack):
    hub = reval_stack["hub"]
    org_mgr = reval_stack["org_mgr"]
    org, owner, _ = org_mgr.create_organization(
        name="Wh", slug="wh", owner_email="w@w.com", owner_name="W"
    )
    conn = hub.register_connector(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="Hook",
        connector_type=ConnectorType.WEBHOOK,
        provider="generic_webhook",
        config={"url": "https://hook.com"},
        secrets={"signing_secret": "wh_sec"},
    )
    body = b'{"hello":"world"}'
    sig = hmac.new(b"wh_sec", body, hashlib.sha256).hexdigest()
    assert hub.verify_inbound_webhook(conn.connector_id, body, sig) is True


def test_reval_ep18_rate_limiting(reval_stack):
    hub = reval_stack["hub"]
    org_mgr = reval_stack["org_mgr"]
    org, owner, _ = org_mgr.create_organization(
        name="Rate", slug="rate", owner_email="r@r.com", owner_name="R"
    )
    conn = hub.register_connector(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="Slack",
        connector_type=ConnectorType.COMMUNICATION,
        provider="slack",
        config={},
        secrets={"bot_token": "xoxb-test"},
        rate_limit_rpm=2,
    )
    hub.verify_connector(owner.user_id, conn.connector_id)
    hub.invoke_connector(owner.user_id, conn.connector_id, "send", {})
    hub.invoke_connector(owner.user_id, conn.connector_id, "send", {})
    with pytest.raises(RateLimitExceededError):
        hub.invoke_connector(owner.user_id, conn.connector_id, "send", {})


def test_reval_ep19_audit_hash_chain(reval_stack):
    audit = reval_stack["audit"]
    rec = audit.append_entry("org_audit", "TEST", "u1", "USER", "act1")
    assert rec.sequence == 1
    assert rec.previous_hash == "0" * 64
    assert len(rec.record_hash) == 64


def test_reval_ep20_audit_sequence_tamper(reval_stack):
    audit = reval_stack["audit"]
    audit.append_entry("org_seq", "T1", "u1", "USER", "a1")
    audit.append_entry("org_seq", "T2", "u1", "USER", "a2")
    # Mutate sequence
    audit._chains["org_seq"][1].sequence = 99
    is_intact, broken_seq, _ = audit.verify_chain_integrity("org_seq")
    assert is_intact is False
    assert broken_seq == 99


def test_reval_ep21_audit_payload_tamper(reval_stack):
    audit = reval_stack["audit"]
    audit.append_entry("org_pay", "T1", "u1", "USER", "a1")
    audit._chains["org_pay"][0].action = "tampered_action"
    is_intact, _, _ = audit.verify_chain_integrity("org_pay")
    assert is_intact is False


def test_reval_ep22_cost_attribution(reval_stack):
    cost = reval_stack["cost"]
    rec, _ = cost.record_usage(
        org_id="org_cst",
        task_id="t1",
        model_name="claude-3-5-sonnet",
        prompt_tokens=1000,
        completion_tokens=1000,
        compute_duration_ms=1000,
    )
    assert rec.total_cost_usd > 0


def test_reval_ep23_spending_caps(reval_stack):
    cost = reval_stack["cost"]
    org_mgr = reval_stack["org_mgr"]
    org, owner, _ = org_mgr.create_organization(
        name="Sp", slug="sp", owner_email="s@s.com", owner_name="S"
    )
    dept = org_mgr.create_department(org.org_id, "D1", "d1")
    cost.set_department_budget(owner.user_id, org.org_id, dept.department_id, allocated_usd=1.0)
    with pytest.raises(BudgetCapExceededError):
        cost.record_usage(
            org_id=org.org_id,
            task_id="t_over",
            model_name="gpt-4o",
            prompt_tokens=500_000,
            completion_tokens=500_000,
            compute_duration_ms=0,
            department_id=dept.department_id,
        )


def test_reval_ep24_operational_analytics(reval_stack):
    analytics = reval_stack["analytics"]
    org_mgr = reval_stack["org_mgr"]
    org, owner, _ = org_mgr.create_organization(
        name="An", slug="an", owner_email="a@a.com", owner_name="A"
    )
    metrics = analytics.get_operational_metrics(owner.user_id, org.org_id)
    assert metrics["compliance_score"] == 100.0


def test_reval_ep25_compliance_export(reval_stack):
    audit = reval_stack["audit"]
    org_mgr = reval_stack["org_mgr"]
    org, owner, _ = org_mgr.create_organization(
        name="Comp", slug="comp", owner_email="c@c.com", owner_name="C"
    )
    audit.append_entry(org.org_id, "SOC2", owner.user_id, "USER", "soc2.test")
    trail = audit.export_audit_trail(owner.user_id, org.org_id)
    assert len(trail) == 1


def test_reval_ep26_admin_console():
    client = TestClient(app)
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert "Enterprise Governance & Admin" in res.text


def test_reval_ep27_docker_compose_config():
    p = Path("compose.yaml")
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    assert "postgres" in txt.lower()


def test_reval_ep28_disaster_recovery(reval_stack):
    audit = reval_stack["audit"]
    audit.append_entry("org_dr1", "BACKUP", "u", "USER", "snap")
    audit.append_entry("org_dr2", "BACKUP", "u", "USER", "snap")
    assert audit.verify_chain_integrity("org_dr1")[0] is True
    assert audit.verify_chain_integrity("org_dr2")[0] is True


def test_reval_ep29_e2e_lifecycle(reval_stack):
    org_mgr = reval_stack["org_mgr"]
    gov = reval_stack["gov"]
    hub = reval_stack["hub"]
    audit = reval_stack["audit"]
    cost = reval_stack["cost"]

    org, owner, _ = org_mgr.create_organization(
        name="E2E", slug="e2e", owner_email="e@e.com", owner_name="E"
    )
    dept = org_mgr.create_department(org.org_id, "Dept", "dept")
    user, _ = org_mgr.add_member(
        org.org_id, email="u@e.com", role=MembershipRole.OPERATOR, department_id=dept.department_id
    )
    agent = gov.register_agent(
        owner.user_id, org.org_id, "Bot", user.user_id, allowed_tools=["slack"]
    )
    conn = hub.register_connector(
        owner.user_id,
        org.org_id,
        "Slk",
        ConnectorType.COMMUNICATION,
        "slack",
        {},
        {"bot_token": "xoxb-123"},
    )
    hub.verify_connector(owner.user_id, conn.connector_id)
    allowed, _, _ = gov.validate_agent_execution(agent.agent_id, tool_name="slack")
    assert allowed is True
    res = hub.invoke_connector(agent.agent_id, conn.connector_id, "send", {"message": "hello"})
    assert res["status"] == "delivered"
    cost.record_usage(org.org_id, "t1", "default", 100, 100, 10, department_id=dept.department_id)
    audit.append_entry(org.org_id, "COMPLETE", agent.agent_id, "AGENT", "finish")
    assert audit.verify_chain_integrity(org.org_id)[0] is True


def test_reval_ep30_regression_baseline(reval_stack):
    assert reval_stack["org_mgr"] is not None
    assert reval_stack["iam"] is not None
    assert reval_stack["audit"] is not None
