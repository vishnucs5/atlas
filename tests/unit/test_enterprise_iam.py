"""Unit tests for Enterprise Identity & Access Management (IAM), RBAC, ABAC, and Service Identity (Milestone 2)."""

import pytest
from atlas_enterprise import (
    ABACContext,
    ABACPolicyViolationError,
    EnterpriseIAMEngine,
    EnterpriseOrganizationManager,
    IdentityProviderConfig,
    IdPType,
    MembershipRole,
    PermissionAction,
    PrivilegeEscalationError,
    SessionRevokedError,
    UnauthorizedError,
)


@pytest.fixture
def org_manager() -> EnterpriseOrganizationManager:
    return EnterpriseOrganizationManager()


@pytest.fixture
def iam_engine(org_manager: EnterpriseOrganizationManager) -> EnterpriseIAMEngine:
    return EnterpriseIAMEngine(org_manager=org_manager)


def test_rbac_least_privilege_enforcement(
    org_manager: EnterpriseOrganizationManager,
    iam_engine: EnterpriseIAMEngine,
) -> None:
    """Verify least privilege and granular permission evaluation across roles."""
    org, owner, _ = org_manager.create_organization(
        name="Acme Corp", slug="acme", owner_email="owner@acme.com", owner_name="Acme Owner"
    )
    developer = org_manager.provision_user("usr_dev", "dev@acme.com", "Acme Dev")
    viewer = org_manager.provision_user("usr_view", "view@acme.com", "Acme Viewer")

    org_manager.add_member(org.org_id, developer.user_id, MembershipRole.DEVELOPER)
    org_manager.add_member(org.org_id, viewer.user_id, MembershipRole.VIEWER)

    # Owner has full permissions
    assert (
        iam_engine.evaluate_permission(owner.user_id, org.org_id, PermissionAction.ORG_DELETE)
        is True
    )
    assert (
        iam_engine.evaluate_permission(owner.user_id, org.org_id, PermissionAction.IAM_MANAGE_ROLES)
        is True
    )

    # Developer can register and execute agents, but cannot delete org or manage IAM
    assert (
        iam_engine.evaluate_permission(
            developer.user_id, org.org_id, PermissionAction.AGENT_REGISTER
        )
        is True
    )
    assert (
        iam_engine.evaluate_permission(
            developer.user_id, org.org_id, PermissionAction.AGENT_EXECUTE
        )
        is True
    )
    assert (
        iam_engine.evaluate_permission(developer.user_id, org.org_id, PermissionAction.ORG_DELETE)
        is False
    )
    assert (
        iam_engine.evaluate_permission(
            developer.user_id, org.org_id, PermissionAction.IAM_MANAGE_ROLES
        )
        is False
    )

    # Viewer has read-only access
    assert (
        iam_engine.evaluate_permission(viewer.user_id, org.org_id, PermissionAction.AGENT_READ)
        is True
    )
    assert (
        iam_engine.evaluate_permission(viewer.user_id, org.org_id, PermissionAction.AGENT_EXECUTE)
        is False
    )
    assert (
        iam_engine.evaluate_permission(viewer.user_id, org.org_id, PermissionAction.AGENT_REGISTER)
        is False
    )

    with pytest.raises(UnauthorizedError):
        iam_engine.assert_permission(viewer.user_id, org.org_id, PermissionAction.AGENT_EXECUTE)


def test_abac_dynamic_context_evaluation(
    org_manager: EnterpriseOrganizationManager,
    iam_engine: EnterpriseIAMEngine,
) -> None:
    """Verify ABAC evaluates client IP allowlists, operating hours, and security clearance."""
    org, _, _ = org_manager.create_organization(
        name="Defense Tech", slug="deftech", owner_email="admin@deftech.com", owner_name="Defense Admin"
    )
    user = org_manager.provision_user("usr_sec", "sec@deftech.com", "Sec Officer")
    org_manager.add_member(org.org_id, user.user_id, MembershipRole.SECURITY_ADMIN)

    # 1. IP allowlist check
    allowed_ip_rules = {"allowed_ips": ["10.0.0.0/24", "192.168.1.50"]}
    ctx_valid_ip = ABACContext(
        user_id=user.user_id,
        org_id=org.org_id,
        client_ip="10.0.0.42",
        security_clearance="secret",
    )
    ctx_invalid_ip = ABACContext(
        user_id=user.user_id,
        org_id=org.org_id,
        client_ip="203.0.113.1",
        security_clearance="secret",
    )

    assert (
        iam_engine.evaluate_permission(
            user.user_id,
            org.org_id,
            PermissionAction.AUDIT_READ,
            abac_context=ctx_valid_ip,
            policy_rules=allowed_ip_rules,
        )
        is True
    )

    assert (
        iam_engine.evaluate_permission(
            user.user_id,
            org.org_id,
            PermissionAction.AUDIT_READ,
            abac_context=ctx_invalid_ip,
            policy_rules=allowed_ip_rules,
        )
        is False
    )

    with pytest.raises(ABACPolicyViolationError):
        iam_engine.assert_permission(
            user.user_id,
            org.org_id,
            PermissionAction.AUDIT_READ,
            abac_context=ctx_invalid_ip,
            policy_rules=allowed_ip_rules,
        )

    # 2. Security clearance check
    clearance_rules = {"required_clearance": "top_secret"}
    assert (
        iam_engine.evaluate_permission(
            user.user_id,
            org.org_id,
            PermissionAction.AUDIT_READ,
            abac_context=ctx_valid_ip,  # clearance is 'secret', requires 'top_secret'
            policy_rules=clearance_rules,
        )
        is False
    )

    ctx_top_secret = ABACContext(
        user_id=user.user_id,
        org_id=org.org_id,
        client_ip="10.0.0.42",
        security_clearance="top_secret",
    )
    assert (
        iam_engine.evaluate_permission(
            user.user_id,
            org.org_id,
            PermissionAction.AUDIT_READ,
            abac_context=ctx_top_secret,
            policy_rules=clearance_rules,
        )
        is True
    )


def test_privilege_escalation_prevention(
    org_manager: EnterpriseOrganizationManager,
    iam_engine: EnterpriseIAMEngine,
) -> None:
    """Verify that users cannot grant themselves or others higher permissions than allowed."""
    org, owner, _ = org_manager.create_organization(
        name="GovCorp", slug="govcorp", owner_email="root@govcorp.com", owner_name="Root Admin"
    )
    dept_admin = org_manager.provision_user("usr_da", "da@govcorp.com", "Dept Lead")
    dev = org_manager.provision_user("usr_dev2", "dev2@govcorp.com", "Junior Dev")

    org_manager.add_member(org.org_id, dept_admin.user_id, MembershipRole.DEPT_ADMIN)
    org_manager.add_member(org.org_id, dev.user_id, MembershipRole.DEVELOPER)

    # Dept admin can grant developer role to junior dev
    membership = iam_engine.assign_role(
        caller_user_id=dept_admin.user_id,
        target_user_id=dev.user_id,
        org_id=org.org_id,
        new_role=MembershipRole.OPERATOR,
    )
    assert membership.role == MembershipRole.OPERATOR

    # Dept admin CANNOT grant OrgOwner or OrgAdmin (PrivilegeEscalationError)
    with pytest.raises(PrivilegeEscalationError):
        iam_engine.assign_role(
            caller_user_id=dept_admin.user_id,
            target_user_id=dev.user_id,
            org_id=org.org_id,
            new_role=MembershipRole.ORG_ADMIN,
        )

    # Developer cannot grant ANY role (level < 70)
    with pytest.raises(PrivilegeEscalationError):
        iam_engine.assign_role(
            caller_user_id=dev.user_id,
            target_user_id=dev.user_id,
            org_id=org.org_id,
            new_role=MembershipRole.DEPT_ADMIN,
        )

    # Self-elevation is strictly prohibited even for admins
    with pytest.raises(PrivilegeEscalationError):
        iam_engine.assign_role(
            caller_user_id=dept_admin.user_id,
            target_user_id=dept_admin.user_id,
            org_id=org.org_id,
            new_role=MembershipRole.ORG_OWNER,
        )


def test_session_lifecycle_and_revocation(
    org_manager: EnterpriseOrganizationManager,
    iam_engine: EnterpriseIAMEngine,
) -> None:
    """Verify session creation, validation, expiry, and revocation."""
    org, _, _ = org_manager.create_organization(
        name="FinTech", slug="fintech", owner_email="admin@fintech.com", owner_name="Fintech Admin"
    )
    user = org_manager.provision_user("usr_trader", "trader@fintech.com", "Senior Trader")
    org_manager.add_member(org.org_id, user.user_id, MembershipRole.OPERATOR)

    # Create session
    session = iam_engine.create_session(
        user.user_id, org.org_id, client_ip="192.168.1.10", ttl_hours=2.0
    )
    assert session.token_id.startswith("atk_sess_")
    assert session.is_revoked is False

    # Validate active session
    validated = iam_engine.validate_session(session.token_id)
    assert validated.token_id == session.token_id

    # Revoke single session
    iam_engine.revoke_session(session.token_id)
    with pytest.raises(SessionRevokedError):
        iam_engine.validate_session(session.token_id)

    # Create multiple sessions and test mass revocation
    s1 = iam_engine.create_session(user.user_id, org.org_id)
    s2 = iam_engine.create_session(user.user_id, org.org_id)
    count = iam_engine.revoke_user_sessions(user.user_id)
    assert count >= 2

    with pytest.raises(SessionRevokedError):
        iam_engine.validate_session(s1.token_id)
    with pytest.raises(SessionRevokedError):
        iam_engine.validate_session(s2.token_id)


def test_service_identity_and_cryptographic_api_keys(
    org_manager: EnterpriseOrganizationManager,
    iam_engine: EnterpriseIAMEngine,
) -> None:
    """Verify non-human service identity provisioning, raw key masking, and rotation."""
    org, _, _ = org_manager.create_organization(
        name="CloudOps", slug="cloudops", owner_email="admin@cloudops.com", owner_name="CloudOps Admin"
    )

    # Create service identity
    svc, raw_key = iam_engine.create_service_identity(
        org_id=org.org_id,
        name="GitHub-CI-Worker",
        scopes=["workflow:execute", "agent:execute"],
    )
    assert raw_key.startswith("atk_live_")
    assert svc.api_key_hash != raw_key  # Hash must never equal raw key

    # Authenticate with raw key
    authenticated_svc = iam_engine.authenticate_api_key(raw_key)
    assert authenticated_svc.service_id == svc.service_id
    assert authenticated_svc.name == "GitHub-CI-Worker"

    # Authenticate with bogus key fails
    with pytest.raises(UnauthorizedError):
        iam_engine.authenticate_api_key("atk_live_invalidkey12345")

    # Rotate key
    new_raw_key = iam_engine.rotate_api_key(svc.service_id)
    assert new_raw_key != raw_key

    # Old key fails immediately
    with pytest.raises(UnauthorizedError):
        iam_engine.authenticate_api_key(raw_key)

    # New key succeeds
    assert iam_engine.authenticate_api_key(new_raw_key).service_id == svc.service_id

    # Revoke service identity
    iam_engine.revoke_service_identity(svc.service_id)
    with pytest.raises(UnauthorizedError):
        iam_engine.authenticate_api_key(new_raw_key)


def test_sso_and_scim_lifecycle(
    org_manager: EnterpriseOrganizationManager,
    iam_engine: EnterpriseIAMEngine,
) -> None:
    """Verify OIDC/SAML federated authentication and SCIM directory sync provisioning."""
    org, _, _ = org_manager.create_organization(
        name="Enterprise Co", slug="enterpriseco", owner_email="admin@enterpriseco.com", owner_name="Enterprise Admin"
    )

    # Register OIDC IdP with claim-to-role mappings
    idp_config = IdentityProviderConfig(
        idp_id="okta-corp",
        org_id=org.org_id,
        idp_type=IdPType.OIDC,
        name="Okta Workforce",
        issuer="https://corp.okta.com",
        client_id="atlas-client-id",
        domain_allowlist=["enterpriseco.com"],
        role_mapping={
            "engineers": MembershipRole.DEVELOPER,
            "security": MembershipRole.SECURITY_ADMIN,
        },
    )
    iam_engine.register_idp(idp_config)

    # Authenticate via SSO assertion
    sso_assertion = {
        "sub": "auth0|123456",
        "email": "alice@enterpriseco.com",
        "name": "Alice Engineer",
        "groups": ["engineers", "contractors"],
    }
    user, session = iam_engine.authenticate_sso("okta-corp", sso_assertion, client_ip="10.10.10.5")
    assert user.email == "alice@enterpriseco.com"
    assert session.role == MembershipRole.DEVELOPER

    # SCIM Provisioning
    scim_payload = {
        "userName": "bob@enterpriseco.com",
        "displayName": "Bob Architect",
        "role": "SecurityAdmin",
    }
    scim_user = iam_engine.scim_provision_user(org.org_id, scim_payload)
    assert scim_user.full_name == "Bob Architect"
    membership = org_manager.get_membership(org.org_id, scim_user.user_id)
    assert membership is not None
    assert membership.role == MembershipRole.SECURITY_ADMIN

    # SCIM Deprovisioning
    iam_engine.scim_deprovision_user(org.org_id, scim_user.user_id)
    assert scim_user.is_active is False
    assert org_manager.get_membership(org.org_id, scim_user.user_id).is_active is False
