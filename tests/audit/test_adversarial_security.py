"""Independent Adversarial Security Audit Tests for Phase 10.

Tests security claims regarding:
- API endpoint authentication and credential enforcement.
- Agent self-elevation guard bypass via unhooked checks.
- Cross-tenant role assignment and unauthorized member elevation.
- Secret store isolation and webhook HMAC edge cases.
"""

import pytest
from atlas_api.main import app
from atlas_enterprise import (
    EnterpriseAgentGovernanceManager,
    EnterpriseIAMEngine,
    EnterpriseOrganizationManager,
    IntegrationHubManager,
    IntegrationSecretStore,
    MembershipRole,
    PermissionAction,
    PrivilegeEscalationError,
    UnauthorizedError,
)
from fastapi.testclient import TestClient


@pytest.fixture
def enterprise_audit_stack():
    org_mgr = EnterpriseOrganizationManager()
    iam = EnterpriseIAMEngine(org_mgr)
    gov = EnterpriseAgentGovernanceManager(org_mgr, iam)
    secret_store = IntegrationSecretStore()
    hub = IntegrationHubManager(org_mgr, iam, secret_store)
    return {
        "org_mgr": org_mgr,
        "iam": iam,
        "gov": gov,
        "secret_store": secret_store,
        "hub": hub,
    }


def test_audit_sec_01_api_endpoints_lack_authentication_headers():
    """Verify that REST API endpoints fail to enforce Authorization headers or session validation."""
    client = TestClient(app)

    # 1. Calling create organization without any auth header or token succeeds
    res_org = client.post(
        "/api/v1/enterprise/organizations",
        json={
            "name": "Unauthenticated Corp",
            "slug": "unauth_corp",
            "owner_email": "attacker@evil.com",
            "owner_name": "Attacker",
        },
    )
    assert res_org.status_code == 200, f"Expected 200, got {res_org.status_code}"
    org_data = res_org.json()["organization"]
    org_id = org_data["org_id"]

    # 2. Suspending an organization without authentication succeeds!
    res_suspend = client.post(
        f"/api/v1/enterprise/organizations/{org_id}/suspend?reason=AttackerTakeover"
    )
    assert res_suspend.status_code == 200, f"Expected 200, got {res_suspend.status_code}"
    assert res_suspend.json()["status"] == "SUSPENDED"

    # 3. Reading organization details without any auth header succeeds!
    res_get = client.get(f"/api/v1/enterprise/organizations/{org_id}")
    assert res_get.status_code == 200
    assert res_get.json()["status"] == "SUSPENDED"


def test_audit_sec_02_unauthenticated_owner_elevation_via_api():
    """Verify vulnerability: Anyone can enroll themselves as OrganizationOwner via POST /members."""
    client = TestClient(app)

    # Victim organization
    res_org = client.post(
        "/api/v1/enterprise/organizations",
        json={
            "name": "Victim Corp",
            "slug": "victim_corp_sec",
            "owner_email": "legit@victim.com",
            "owner_name": "Legit CEO",
        },
    )
    victim_org_id = res_org.json()["organization"]["org_id"]

    # Attacker calls POST /members without authentication, granting themselves OrganizationOwner!
    res_attacker = client.post(
        f"/api/v1/enterprise/organizations/{victim_org_id}/members",
        json={
            "email": "attacker@evil.com",
            "full_name": "Hostile Takeover",
            "role": "OrganizationOwner",
        },
    )
    assert res_attacker.status_code == 200
    mem_data = res_attacker.json()["membership"]
    assert mem_data["role"] == "OrganizationOwner"
    assert mem_data["org_id"] == victim_org_id


def test_audit_sec_03_agent_self_elevation_guard_is_orphaned(enterprise_audit_stack):
    """Verify vulnerability: check_agent_self_elevation is not hooked into IAM engine or API routes."""
    org_mgr = enterprise_audit_stack["org_mgr"]
    iam = enterprise_audit_stack["iam"]

    org, owner, _ = org_mgr.create_organization(
        name="GuardCorp", slug="guardcorp", owner_email="o@gc.com", owner_name="Owner"
    )

    # A non-human service identity with prefix 'ag_' or 'svc_'
    # If the agent identity calls iam.assign_role directly or API routes,
    # does EnterpriseIAMEngine or EnterpriseOrganizationManager call check_agent_self_elevation?
    # No! It only checks caller_membership.role!
    agent_user, _ = org_mgr.add_member(
        org_id=org.org_id,
        user_id="ag_rogue_bot",
        role=MembershipRole.ORG_ADMIN,
    )

    target_user, _ = org_mgr.add_member(
        org_id=org.org_id,
        user_id="usr_puppet",
        role=MembershipRole.VIEWER,
    )

    # An agent (ag_rogue_bot) that somehow obtained ORG_ADMIN can assign roles
    # because iam.assign_role does NOT invoke check_agent_self_elevation!
    new_mem = iam.assign_role(
        caller_user_id="ag_rogue_bot",
        target_user_id="usr_puppet",
        org_id=org.org_id,
        new_role=MembershipRole.SECURITY_ADMIN,
    )
    assert new_mem.role == MembershipRole.SECURITY_ADMIN


def test_audit_sec_04_privilege_escalation_enforcement_in_iam(enterprise_audit_stack):
    """Verify that EnterpriseIAMEngine correctly enforces privilege escalation internally."""
    org_mgr = enterprise_audit_stack["org_mgr"]
    iam = enterprise_audit_stack["iam"]

    org, owner, _ = org_mgr.create_organization(
        name="IAMCorp", slug="iamcorp", owner_email="o@iam.com", owner_name="Owner"
    )

    dev_user, _ = org_mgr.add_member(
        org_id=org.org_id,
        email="dev@iam.com",
        role=MembershipRole.DEVELOPER,
    )
    victim_user, _ = org_mgr.add_member(
        org_id=org.org_id,
        email="vic@iam.com",
        role=MembershipRole.VIEWER,
    )

    # 1. Developer cannot grant Admin role
    with pytest.raises(PrivilegeEscalationError):
        iam.assign_role(
            caller_user_id=dev_user.user_id,
            target_user_id=victim_user.user_id,
            org_id=org.org_id,
            new_role=MembershipRole.ORG_ADMIN,
        )

    # 2. Self-elevation is prevented
    with pytest.raises(PrivilegeEscalationError):
        iam.assign_role(
            caller_user_id=dev_user.user_id,
            target_user_id=dev_user.user_id,
            org_id=org.org_id,
            new_role=MembershipRole.ORG_OWNER,
        )


def test_audit_sec_05_webhook_signature_timing_and_bypass(enterprise_audit_stack):
    """Verify webhook HMAC signature behavior with missing secret and invalid signatures."""
    hub = enterprise_audit_stack["hub"]
    org_mgr = enterprise_audit_stack["org_mgr"]

    org, owner, _ = org_mgr.create_organization(
        name="WebhookCorp", slug="whcorp", owner_email="w@wh.com", owner_name="Owner"
    )

    conn = hub.register_connector(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="SecureWebhook",
        connector_type="WEBHOOK",
        provider="generic_webhook",
        config={"url": "https://example.com"},
        secrets={"signing_secret": "super_secret_signing_key_123"},
    )

    # 1. Invalid signature is rejected
    is_valid = hub.verify_inbound_webhook(
        connector_id=conn.connector_id,
        payload_bytes=b'{"event":"ping"}',
        signature_header="bad_signature",
    )
    assert is_valid is False

    # 2. Empty signature is rejected
    is_valid_empty = hub.verify_inbound_webhook(
        connector_id=conn.connector_id,
        payload_bytes=b'{"event":"ping"}',
        signature_header="",
    )
    assert is_valid_empty is False
