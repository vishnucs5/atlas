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
    PrivilegeEscalationError,
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
    """Verify that REST API endpoints strictly enforce Authorization headers and session validation."""
    client = TestClient(app)

    # 1. Calling create organization returns initial token
    res_org = client.post(
        "/api/v1/enterprise/organizations",
        json={
            "name": "Secured Corp",
            "slug": "secured_corp",
            "owner_email": "owner@secured.com",
            "owner_name": "Owner",
        },
    )
    assert res_org.status_code == 200, f"Expected 200, got {res_org.status_code}"
    org_data = res_org.json()["organization"]
    org_id = org_data["org_id"]
    token_id = res_org.json()["token_id"]

    # 2. Suspending an organization without authentication is rejected with 401!
    res_suspend = client.post(
        f"/api/v1/enterprise/organizations/{org_id}/suspend?reason=AttackerTakeover"
    )
    assert res_suspend.status_code == 401

    # 3. Reading organization details without any auth header is rejected with 401!
    res_get = client.get(f"/api/v1/enterprise/organizations/{org_id}")
    assert res_get.status_code == 401

    # 4. Authenticated call succeeds
    res_auth = client.post(
        f"/api/v1/enterprise/organizations/{org_id}/suspend?reason=LegitHold",
        headers={"Authorization": f"Bearer {token_id}"},
    )
    assert res_auth.status_code == 200
    assert res_auth.json()["status"] == "SUSPENDED"


def test_audit_sec_02_unauthenticated_owner_elevation_via_api():
    """Verify vulnerability resolution: Unauthenticated and unauthorized users cannot enroll as OrganizationOwner."""
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
    owner_token = res_org.json()["token_id"]

    # Attacker calls POST /members without authentication -> rejected with 401!
    res_attacker = client.post(
        f"/api/v1/enterprise/organizations/{victim_org_id}/members",
        json={
            "email": "attacker@evil.com",
            "full_name": "Hostile Takeover",
            "role": "OrganizationOwner",
        },
    )
    assert res_attacker.status_code == 401

    # Developer user enrolls and tries to escalate to Owner -> rejected with 403!
    res_dev = client.post(
        f"/api/v1/enterprise/organizations/{victim_org_id}/members",
        json={
            "email": "dev@victim.com",
            "full_name": "Dev User",
            "role": "Developer",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_dev.status_code == 200
    dev_id = res_dev.json()["user"]["user_id"]

    login_res = client.post(
        "/api/v1/enterprise/iam/login",
        json={"user_id": dev_id, "org_id": victim_org_id},
    )
    dev_token = login_res.json()["token_id"]

    res_escalate = client.post(
        f"/api/v1/enterprise/organizations/{victim_org_id}/members",
        json={
            "email": "puppet@victim.com",
            "full_name": "Puppet",
            "role": "OrganizationOwner",
        },
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    assert res_escalate.status_code == 403


def test_audit_sec_03_agent_self_elevation_guard_is_orphaned(enterprise_audit_stack):
    """Verify that check_agent_self_elevation is strictly enforced in IAM assign_role and governance set_policy."""
    org_mgr = enterprise_audit_stack["org_mgr"]
    iam = enterprise_audit_stack["iam"]
    gov = enterprise_audit_stack["gov"]

    org, owner, _ = org_mgr.create_organization(
        name="GuardCorp", slug="guardcorp", owner_email="o@gc.com", owner_name="Owner"
    )

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

    # An agent (ag_rogue_bot) attempting to assign roles is strictly blocked!
    from atlas_enterprise.iam import AgentSelfElevationError

    with pytest.raises(AgentSelfElevationError):
        iam.assign_role(
            caller_user_id="ag_rogue_bot",
            target_user_id="usr_puppet",
            org_id=org.org_id,
            new_role=MembershipRole.SECURITY_ADMIN,
        )

    # An agent attempting to configure policy is strictly blocked!
    with pytest.raises(AgentSelfElevationError):
        gov.set_policy(
            caller_user_id="ag_rogue_bot",
            org_id=org.org_id,
            scope_type="ORGANIZATION",
            scope_id=org.org_id,
            disallowed_tools=[],
        )


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
