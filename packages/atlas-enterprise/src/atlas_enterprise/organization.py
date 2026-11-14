"""Enterprise organization, tenant provisioning, department hierarchy, and scoping manager."""

import logging
import threading
import uuid
from typing import Any

from atlas_enterprise.models import (
    Department,
    MembershipRole,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
    Project,
    Team,
    TenantOwnedResource,
    User,
)

logger = logging.getLogger("atlas.enterprise.organization")


class EnterpriseOrganizationError(Exception):
    """Base exception for organization and tenancy management errors."""


class CrossTenantAccessViolationError(EnterpriseOrganizationError):
    """Raised when an operation attempts to access resources across tenant boundaries."""


class OrganizationNotFoundError(EnterpriseOrganizationError):
    """Raised when the specified organization cannot be found."""


class DepartmentNotFoundError(EnterpriseOrganizationError):
    """Raised when the specified department cannot be found."""


class DuplicateEntityError(EnterpriseOrganizationError):
    """Raised when attempting to create an entity with an existing unique identifier or slug."""


class EnterpriseOrganizationManager:
    """Manages enterprise organizations, multi-tenant boundaries, departments, and memberships."""

    def __init__(self) -> None:
        self._orgs: dict[str, Organization] = {}
        self._org_slugs: dict[str, str] = {}  # slug -> org_id
        self._departments: dict[str, Department] = {}  # dept_id -> Department
        self._teams: dict[str, Team] = {}  # team_id -> Team
        self._projects: dict[str, Project] = {}  # proj_id -> Project
        self._users: dict[str, User] = {}  # user_id -> User
        self._memberships: dict[str, OrganizationMembership] = {}  # (org_id, user_id) -> Membership
        self._lock = threading.RLock()

    def create_organization(
        self,
        name: str,
        slug: str,
        owner_email: str,
        owner_name: str,
        settings: dict[str, Any] | None = None,
        retention_days: int = 90,
        max_concurrent_workers: int = 100,
    ) -> tuple[Organization, User, OrganizationMembership]:
        """Provision a new top-level enterprise organization and root owner identity."""
        with self._lock:
            if slug in self._org_slugs:
                raise DuplicateEntityError(f"Organization slug '{slug}' is already registered")

            org_id = f"org_{uuid.uuid4().hex[:12]}"
            org = Organization(
                org_id=org_id,
                name=name,
                slug=slug,
                status=OrganizationStatus.ACTIVE,
                settings=settings or {},
                retention_days=retention_days,
                max_concurrent_workers=max_concurrent_workers,
            )
            self._orgs[org_id] = org
            self._org_slugs[slug] = org_id

            # Create Owner User
            user_id = f"usr_{uuid.uuid4().hex[:12]}"
            user = User(
                user_id=user_id,
                email=owner_email,
                full_name=owner_name,
                is_active=True,
            )
            self._users[user_id] = user

            # Create Owner Membership
            membership_id = f"mem_{uuid.uuid4().hex[:12]}"
            membership = OrganizationMembership(
                membership_id=membership_id,
                org_id=org_id,
                user_id=user_id,
                role=MembershipRole.ORG_OWNER,
                is_active=True,
            )
            self._memberships[f"{org_id}:{user_id}"] = membership

            logger.info("Provisioned organization %s (%s) with owner %s", name, org_id, owner_email)
            return org, user, membership

    def get_organization(self, org_id: str) -> Organization | None:
        """Retrieve organization by ID."""
        with self._lock:
            return self._orgs.get(org_id)

    def suspend_organization(
        self, org_id: str, reason: str = "Administrative hold"
    ) -> Organization:
        """Suspend an organization, halting tenant task execution and login access."""
        with self._lock:
            org = self._orgs.get(org_id)
            if not org:
                raise OrganizationNotFoundError(f"Organization '{org_id}' not found")
            org.status = OrganizationStatus.SUSPENDED
            org.settings["suspension_reason"] = reason
            logger.warning("Suspended organization %s: %s", org_id, reason)
            return org

    def create_department(
        self,
        org_id: str,
        name: str,
        slug: str,
        lead_user_id: str | None = None,
        budget_usd: float = 10_000.0,
        settings: dict[str, Any] | None = None,
    ) -> Department:
        """Create a department / business unit within an organization."""
        with self._lock:
            org = self._orgs.get(org_id)
            if not org:
                raise OrganizationNotFoundError(f"Organization '{org_id}' not found")

            dept_id = f"dept_{uuid.uuid4().hex[:12]}"
            dept = Department(
                department_id=dept_id,
                org_id=org_id,
                name=name,
                slug=slug,
                lead_user_id=lead_user_id,
                budget_usd=budget_usd,
                settings=settings or {},
            )
            self._departments[dept_id] = dept
            logger.info("Created department %s (%s) in org %s", name, dept_id, org_id)
            return dept

    def get_department(
        self, department_id: str, caller_org_id: str | None = None
    ) -> Department | None:
        """Retrieve department with tenant boundary check."""
        with self._lock:
            dept = self._departments.get(department_id)
            if dept and caller_org_id and dept.org_id != caller_org_id:
                raise CrossTenantAccessViolationError(
                    f"Cross-tenant access denied: department {department_id} belongs to "
                    f"org {dept.org_id}, caller is from org {caller_org_id}"
                )
            return dept

    def create_team(self, org_id: str, department_id: str, name: str) -> Team:
        """Create a team within an existing department."""
        with self._lock:
            dept = self.get_department(department_id, caller_org_id=org_id)
            if not dept:
                raise DepartmentNotFoundError(
                    f"Department '{department_id}' not found in org '{org_id}'"
                )

            team_id = f"team_{uuid.uuid4().hex[:12]}"
            team = Team(
                team_id=team_id,
                org_id=org_id,
                department_id=department_id,
                name=name,
            )
            self._teams[team_id] = team
            return team

    def create_project(
        self,
        org_id: str,
        department_id: str,
        team_id: str,
        name: str,
    ) -> Project:
        """Create a project workstream within an existing team."""
        with self._lock:
            team = self._teams.get(team_id)
            if not team or team.org_id != org_id or team.department_id != department_id:
                raise EnterpriseOrganizationError(
                    "Invalid department or team hierarchy for project creation"
                )

            proj_id = f"proj_{uuid.uuid4().hex[:12]}"
            proj = Project(
                project_id=proj_id,
                org_id=org_id,
                department_id=department_id,
                team_id=team_id,
                name=name,
            )
            self._projects[proj_id] = proj
            return proj

    def add_member(
        self,
        org_id: str,
        email: str,
        full_name: str,
        role: MembershipRole = MembershipRole.VIEWER,
        department_id: str | None = None,
    ) -> tuple[User, OrganizationMembership]:
        """Add or enroll a user into an organization and assign an RBAC role."""
        with self._lock:
            org = self._orgs.get(org_id)
            if not org:
                raise OrganizationNotFoundError(f"Organization '{org_id}' not found")

            if department_id:
                dept = self.get_department(department_id, caller_org_id=org_id)
                if not dept:
                    raise DepartmentNotFoundError(
                        f"Department '{department_id}' not found in org '{org_id}'"
                    )

            # Check existing user by email or create new
            user = next((u for u in self._users.values() if u.email.lower() == email.lower()), None)
            if not user:
                user_id = f"usr_{uuid.uuid4().hex[:12]}"
                user = User(
                    user_id=user_id,
                    email=email,
                    full_name=full_name,
                    is_active=True,
                )
                self._users[user_id] = user

            mem_key = f"{org_id}:{user.user_id}"
            membership = OrganizationMembership(
                membership_id=f"mem_{uuid.uuid4().hex[:12]}",
                org_id=org_id,
                user_id=user.user_id,
                role=role,
                department_id=department_id,
                is_active=True,
            )
            self._memberships[mem_key] = membership
            logger.info("Enrolled user %s in org %s with role %s", email, org_id, role.value)
            return user, membership

    def get_membership(self, org_id: str, user_id: str) -> OrganizationMembership | None:
        """Retrieve user membership within an organization."""
        with self._lock:
            return self._memberships.get(f"{org_id}:{user_id}")

    def list_members(
        self,
        org_id: str,
        department_id: str | None = None,
    ) -> list[tuple[User, OrganizationMembership]]:
        """List active members belonging to an organization or department."""
        with self._lock:
            res: list[tuple[User, OrganizationMembership]] = []
            for mem in self._memberships.values():
                if mem.org_id != org_id or not mem.is_active:
                    continue
                if department_id and mem.department_id != department_id:
                    continue
                user = self._users.get(mem.user_id)
                if user and user.is_active:
                    res.append((user, mem))
            return res

    def assert_tenant_boundary(
        self, caller_org_id: str, target_resource: TenantOwnedResource
    ) -> None:
        """Assert that caller belongs to the same organization tenant as the target resource."""
        if caller_org_id != target_resource.org_id:
            error_msg = (
                f"Cross-Tenant Access Violation: Caller tenant '{caller_org_id}' cannot access "
                f"resource owned by tenant '{target_resource.org_id}'."
            )
            logger.error(error_msg)
            raise CrossTenantAccessViolationError(error_msg)
