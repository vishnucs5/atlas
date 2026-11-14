"""Unit tests for Enterprise Multi-Tenant Organization Architecture (Milestone 1)."""

import pytest
from atlas_enterprise.models import (
    MembershipRole,
    OrganizationStatus,
    TenantOwnedResource,
)
from atlas_enterprise.organization import (
    CrossTenantAccessViolationError,
    DuplicateEntityError,
    EnterpriseOrganizationManager,
    OrganizationNotFoundError,
)


@pytest.fixture
def org_manager() -> EnterpriseOrganizationManager:
    return EnterpriseOrganizationManager()


def test_organization_provisioning(org_manager):
    """Verify organization creation automatically provisions owner user and root membership."""
    org, owner, mem = org_manager.create_organization(
        name="Acme Corporation",
        slug="acme-corp",
        owner_email="ceo@acme.com",
        owner_name="Alice Owner",
        retention_days=180,
    )

    assert org.org_id.startswith("org_")
    assert org.slug == "acme-corp"
    assert org.status == OrganizationStatus.ACTIVE
    assert org.retention_days == 180

    assert owner.user_id.startswith("usr_")
    assert owner.email == "ceo@acme.com"

    assert mem.role == MembershipRole.ORG_OWNER
    assert mem.org_id == org.org_id
    assert mem.user_id == owner.user_id


def test_duplicate_organization_slug_rejection(org_manager):
    """Verify duplicate organization slug registration is strictly rejected."""
    org_manager.create_organization(
        name="Org 1", slug="duplicate-slug", owner_email="a@o1.com", owner_name="User 1"
    )
    with pytest.raises(DuplicateEntityError):
        org_manager.create_organization(
            name="Org 2", slug="duplicate-slug", owner_email="b@o2.com", owner_name="User 2"
        )


def test_department_team_project_hierarchy(org_manager):
    """Verify hierarchical containment from Organization down to Department, Team, and Project."""
    org, _, _ = org_manager.create_organization(
        name="Global Corp", slug="global-corp", owner_email="admin@global.com", owner_name="Admin"
    )

    # 1. Department
    dept = org_manager.create_department(
        org_id=org.org_id,
        name="Finance",
        slug="finance",
        budget_usd=50_000.0,
    )
    assert dept.department_id.startswith("dept_")
    assert dept.org_id == org.org_id
    assert dept.budget_usd == 50_000.0

    # 2. Team
    team = org_manager.create_team(
        org_id=org.org_id,
        department_id=dept.department_id,
        name="Billing Automation",
    )
    assert team.team_id.startswith("team_")
    assert team.department_id == dept.department_id
    assert team.org_id == org.org_id

    # 3. Project
    project = org_manager.create_project(
        org_id=org.org_id,
        department_id=dept.department_id,
        team_id=team.team_id,
        name="Invoice Reconciliation Workstream",
    )
    assert project.project_id.startswith("proj_")
    assert project.team_id == team.team_id
    assert project.department_id == dept.department_id
    assert project.org_id == org.org_id


def test_cross_tenant_access_violation(org_manager):
    """Verify strict tenant isolation preventing cross-tenant access at service layer."""
    org_a, _, _ = org_manager.create_organization(
        name="Tenant Alpha", slug="alpha", owner_email="a@alpha.com", owner_name="Alpha"
    )
    org_b, _, _ = org_manager.create_organization(
        name="Tenant Beta", slug="beta", owner_email="b@beta.com", owner_name="Beta"
    )

    dept_b = org_manager.create_department(org_id=org_b.org_id, name="Beta Ops", slug="beta-ops")

    # Caller from Tenant Alpha attempts to access Tenant Beta's department
    with pytest.raises(CrossTenantAccessViolationError) as exc_info:
        org_manager.get_department(dept_b.department_id, caller_org_id=org_a.org_id)
    assert "Cross-tenant access denied" in str(exc_info.value)

    # Tenant boundary assertion on resource
    mock_resource = TenantOwnedResource(org_id=org_b.org_id)
    with pytest.raises(CrossTenantAccessViolationError):
        org_manager.assert_tenant_boundary(
            caller_org_id=org_a.org_id, target_resource=mock_resource
        )


def test_member_enrollment_and_department_scoping(org_manager):
    """Verify adding organization members with specific roles and department scopes."""
    org, _, _ = org_manager.create_organization(
        name="Enterprise", slug="ent", owner_email="ceo@ent.com", owner_name="CEO"
    )
    dept = org_manager.create_department(org_id=org.org_id, name="Security", slug="sec")

    # Add security admin
    user_sec, mem_sec = org_manager.add_member(
        org_id=org.org_id,
        email="sec@ent.com",
        full_name="Bob Security",
        role=MembershipRole.SECURITY_ADMIN,
        department_id=dept.department_id,
    )
    assert mem_sec.role == MembershipRole.SECURITY_ADMIN
    assert mem_sec.department_id == dept.department_id

    # List department members
    dept_members = org_manager.list_members(org_id=org.org_id, department_id=dept.department_id)
    assert len(dept_members) == 1
    assert dept_members[0][0].email == "sec@ent.com"


def test_organization_suspension(org_manager):
    """Verify organization suspension transitions lifecycle status."""
    org, _, _ = org_manager.create_organization(
        name="Late Payer", slug="late-pay", owner_email="bill@late.com", owner_name="Bill"
    )
    suspended_org = org_manager.suspend_organization(org.org_id, reason="Billing arrears")
    assert suspended_org.status == OrganizationStatus.SUSPENDED
    assert suspended_org.settings["suspension_reason"] == "Billing arrears"

    with pytest.raises(OrganizationNotFoundError):
        org_manager.suspend_organization("org_non_existent")
