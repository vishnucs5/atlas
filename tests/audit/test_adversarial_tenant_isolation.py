"""Independent Adversarial Multi-Tenant Isolation Tests for Phase 10.

Tests boundary enforcement between distinct organizations:
- Cross-tenant connector invocation.
- Cross-tenant secret vault access.
- Cross-tenant audit trail inspection and leakage.
- Cross-tenant budget allocation and manipulation.
- Cross-tenant agent registration and execution.
"""

import pytest
from atlas_api.main import app
from atlas_enterprise import (
    ConnectorStatus,
    ConnectorType,
    CrossTenantAccessViolationError,
    EnterpriseAgentGovernanceManager,
    EnterpriseAuditLedger,
    EnterpriseCostManager,
    EnterpriseIAMEngine,
    EnterpriseOrganizationManager,
    IntegrationHubManager,
    IntegrationSecretStore,
    MembershipRole,
    PermissionAction,
    UnauthorizedError,
)
from fastapi.testclient import TestClient


@pytest.fixture
def multi_tenant_fixture():
    org_mgr = EnterpriseOrganizationManager()
    iam = EnterpriseIAMEngine(org_mgr)
    gov = EnterpriseAgentGovernanceManager(org_mgr, iam)
    secret_store = IntegrationSecretStore()
    hub = IntegrationHubManager(org_mgr, iam, secret_store)
    audit = EnterpriseAuditLedger(org_mgr, iam)
    cost = EnterpriseCostManager(org_mgr, iam)

    # Org Alpha
    org_a, owner_a, _ = org_mgr.create_organization(
        name="Org Alpha", slug="alpha", owner_email="a@alpha.com", owner_name="Owner A"
    )
    user_a, _ = org_mgr.add_member(
        org_id=org_a.org_id,
        email="dev@alpha.com",
        role=MembershipRole.DEVELOPER,
    )

    # Org Beta
    org_b, owner_b, _ = org_mgr.create_organization(
        name="Org Beta", slug="beta", owner_email="b@beta.com", owner_name="Owner B"
    )
    user_b, _ = org_mgr.add_member(
        org_id=org_b.org_id,
        email="dev@beta.com",
        role=MembershipRole.DEVELOPER,
    )

    return {
        "org_mgr": org_mgr,
        "iam": iam,
        "gov": gov,
        "secret_store": secret_store,
        "hub": hub,
        "audit": audit,
        "cost": cost,
        "org_a": org_a,
        "owner_a": owner_a,
        "user_a": user_a,
        "org_b": org_b,
        "owner_b": owner_b,
        "user_b": user_b,
    }


def test_audit_iso_01_cross_tenant_connector_invocation_vulnerability(multi_tenant_fixture):
    """Verify vulnerability: invoke_connector does NOT check caller tenant or permissions.

    A user or agent from Org B can invoke an active connector owned by Org A
    using Org A's credentials/secrets!
    """
    hub = multi_tenant_fixture["hub"]
    org_a = multi_tenant_fixture["org_a"]
    owner_a = multi_tenant_fixture["owner_a"]
    user_b = multi_tenant_fixture["user_b"]

    # Org A registers and verifies a Salesforce connector
    conn_a = hub.register_connector(
        caller_user_id=owner_a.user_id,
        org_id=org_a.org_id,
        name="Alpha-Salesforce",
        connector_type=ConnectorType.CRM,
        provider="salesforce",
        config={},
        secrets={"api_key": "alpha_production_secret_key"},
    )
    verified, _ = hub.verify_connector(owner_a.user_id, conn_a.connector_id)
    assert verified is True

    # User B from Org B invokes Org A's connector!
    # Because invoke_connector does not verify that caller belongs to conn_a.org_id,
    # User B successfully invokes Org A's connector!
    result = hub.invoke_connector(
        caller_id=user_b.user_id,
        connector_id=conn_a.connector_id,
        action_name="query_account",
        parameters={"account_id": "001_SECRET_ALPHA"},
    )
    assert result["account_id"] == "001_SECRET_ALPHA"
    assert result["status"] == "Active"


def test_audit_iso_02_secret_store_enforces_tenant_boundary(multi_tenant_fixture):
    """Verify that IntegrationSecretStore strictly blocks cross-tenant secret retrieval."""
    secret_store = multi_tenant_fixture["secret_store"]
    org_a = multi_tenant_fixture["org_a"]
    org_b = multi_tenant_fixture["org_b"]

    secret_id = secret_store.store_secret(
        org_id=org_a.org_id,
        secrets={"db_pass": "super_secret_alpha_db_password"},
    )

    # Retrieval by Org A succeeds
    sec_a = secret_store.get_secret(org_a.org_id, secret_id)
    assert sec_a["db_pass"] == "super_secret_alpha_db_password"

    # Retrieval by Org B raises CrossTenantAccessViolationError
    with pytest.raises(CrossTenantAccessViolationError):
        secret_store.get_secret(org_b.org_id, secret_id)


def test_audit_iso_03_cross_tenant_audit_query_blocked(multi_tenant_fixture):
    """Verify that audit querying enforces tenant boundaries when caller is from another org."""
    audit = multi_tenant_fixture["audit"]
    org_a = multi_tenant_fixture["org_a"]
    org_b = multi_tenant_fixture["org_b"]
    owner_a = multi_tenant_fixture["owner_a"]
    user_b = multi_tenant_fixture["user_b"]

    audit.append_entry(org_a.org_id, "SECRET_ACCESSED", owner_a.user_id, "USER", "secret.read")

    # User B from Org B queries Org A's audit log
    with pytest.raises(UnauthorizedError):
        audit.query_records(
            caller_user_id=user_b.user_id,
            org_id=org_a.org_id,
        )


def test_audit_iso_04_cross_tenant_budget_leakage_and_tampering(multi_tenant_fixture):
    """Verify that department budgets cannot be inspected or modified across tenants."""
    cost = multi_tenant_fixture["cost"]
    org_mgr = multi_tenant_fixture["org_mgr"]
    org_a = multi_tenant_fixture["org_a"]
    org_b = multi_tenant_fixture["org_b"]
    owner_a = multi_tenant_fixture["owner_a"]
    owner_b = multi_tenant_fixture["owner_b"]

    dept_a = org_mgr.create_department(org_a.org_id, "Alpha Ops", "alphaops")
    budget_a = cost.set_department_budget(
        caller_user_id=owner_a.user_id,
        org_id=org_a.org_id,
        department_id=dept_a.department_id,
        allocated_usd=25000.0,
    )

    # Org B trying to inspect Org A's budget raises CrossTenantAccessViolationError
    with pytest.raises(CrossTenantAccessViolationError):
        cost.get_department_budget(org_id=org_b.org_id, department_id=dept_a.department_id)

    # Org B owner trying to set Org A's budget raises CrossTenantAccessViolationError / EnterpriseCostError
    with pytest.raises(Exception):
        cost.set_department_budget(
            caller_user_id=owner_b.user_id,
            org_id=org_b.org_id,
            department_id=dept_a.department_id,
            allocated_usd=999999.0,
        )
