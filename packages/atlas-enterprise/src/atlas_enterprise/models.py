"""Enterprise domain contracts and data models for ATLAS Autonomous Operating Platform."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrganizationStatus(StrEnum):
    """Lifecycle status of an enterprise organization."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class MembershipRole(StrEnum):
    """Initial granular enterprise RBAC roles."""

    ORG_OWNER = "OrganizationOwner"
    ORG_ADMIN = "OrganizationAdmin"
    SECURITY_ADMIN = "SecurityAdmin"
    DEPT_ADMIN = "DepartmentAdmin"
    DEVELOPER = "Developer"
    WORKFLOW_PUBLISHER = "WorkflowPublisher"
    OPERATOR = "Operator"
    AUDITOR = "Auditor"
    VIEWER = "Viewer"


class TenantOwnedResource(BaseModel):
    """Base mixin enforcing tenant ownership on all persistent entities."""

    model_config = ConfigDict(validate_assignment=True)

    org_id: str
    department_id: str | None = None
    team_id: str | None = None
    project_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class User(BaseModel):
    """Enterprise human user identity."""

    model_config = ConfigDict(validate_assignment=True)

    user_id: str
    email: str
    full_name: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Organization(BaseModel):
    """Top-level enterprise tenant boundary."""

    model_config = ConfigDict(validate_assignment=True)

    org_id: str
    name: str
    slug: str
    status: OrganizationStatus = OrganizationStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    settings: dict[str, Any] = Field(default_factory=dict)
    retention_days: int = 90
    max_concurrent_workers: int = 100


class Department(TenantOwnedResource):
    """Functional department / business unit within an organization."""

    department_id: str
    name: str
    slug: str
    lead_user_id: str | None = None
    budget_usd: float = 10_000.0
    settings: dict[str, Any] = Field(default_factory=dict)


class Team(TenantOwnedResource):
    """Operational team within a department."""

    team_id: str
    name: str


class Project(TenantOwnedResource):
    """Project workstream containing task graphs and workflows."""

    project_id: str
    name: str
    status: str = "ACTIVE"


class OrganizationMembership(BaseModel):
    """User membership and assigned RBAC role within an organization and optional department."""

    model_config = ConfigDict(validate_assignment=True)

    membership_id: str
    org_id: str
    user_id: str
    role: MembershipRole = MembershipRole.VIEWER
    department_id: str | None = None
    is_active: bool = True
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ServiceIdentity(TenantOwnedResource):
    """Non-human service identity for automated pipelines, CI/CD, or worker daemons."""

    service_id: str
    name: str
    api_key_hash: str
    scopes: list[str] = Field(default_factory=list)
    is_active: bool = True
    expires_at: datetime | None = None
