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


class PermissionAction(StrEnum):
    """Granular enterprise permission actions."""

    # Organization
    ORG_READ = "org:read"
    ORG_UPDATE = "org:update"
    ORG_DELETE = "org:delete"
    MEMBER_MANAGE = "member:manage"
    DEPT_MANAGE = "dept:manage"

    # IAM & Security
    IAM_MANAGE_ROLES = "iam:manage_roles"
    IAM_MANAGE_POLICY = "iam:manage_policy"
    IAM_MANAGE_CREDENTIALS = "iam:manage_credentials"

    # Agent Governance
    AGENT_REGISTER = "agent:register"
    AGENT_READ = "agent:read"
    AGENT_UPDATE = "agent:update"
    AGENT_DELETE = "agent:delete"
    AGENT_EXECUTE = "agent:execute"

    # Workflow Ecosystem
    WORKFLOW_REGISTER = "workflow:register"
    WORKFLOW_PUBLISH = "workflow:publish"
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_EXECUTE = "workflow:execute"

    # Skills
    SKILL_MANAGE = "skill:manage"
    SKILL_READ = "skill:read"

    # Integrations
    INTEGRATION_MANAGE = "integration:manage"
    INTEGRATION_READ = "integration:read"
    INTEGRATION_INVOKE = "integration:invoke"

    # Compliance & Audit
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"

    # Cost & Budgets
    COST_READ = "cost:read"
    BUDGET_MANAGE = "budget:manage"

    # Approvals
    APPROVAL_SUBMIT = "approval:submit"
    APPROVAL_DECIDE = "approval:decide"


class SessionToken(BaseModel):
    """Authenticated user session token with cryptographic ID and lifecycle state."""

    model_config = ConfigDict(validate_assignment=True)

    token_id: str
    user_id: str
    org_id: str
    role: MembershipRole
    department_id: str | None = None
    client_ip: str | None = None
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    is_revoked: bool = False


class ABACContext(BaseModel):
    """Dynamic contextual attributes evaluated during Attribute-Based Access Control."""

    model_config = ConfigDict(validate_assignment=True)

    user_id: str
    org_id: str
    department_id: str | None = None
    client_ip: str | None = None
    current_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    security_clearance: str = "standard"  # standard, confidential, secret, top_secret
    environment_tags: dict[str, Any] = Field(default_factory=dict)


class IdPType(StrEnum):
    """Supported Identity Provider protocols."""

    OIDC = "OIDC"
    SAML = "SAML"
    LOCAL = "LOCAL"


class IdentityProviderConfig(BaseModel):
    """Enterprise Identity Provider configuration and claim mapping rules."""

    model_config = ConfigDict(validate_assignment=True)

    idp_id: str
    org_id: str
    idp_type: IdPType = IdPType.OIDC
    name: str
    issuer: str
    client_id: str
    client_secret: str | None = None
    domain_allowlist: list[str] = Field(default_factory=list)
    role_mapping: dict[str, MembershipRole] = Field(default_factory=dict)
    is_active: bool = True


class UserIdentity(BaseModel):
    """Federated identity claims returned by IdP authentication."""

    model_config = ConfigDict(validate_assignment=True)

    sub: str
    email: str
    full_name: str
    groups: list[str] = Field(default_factory=list)
    claims: dict[str, Any] = Field(default_factory=dict)


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


class AgentLifecycleStatus(StrEnum):
    """Lifecycle status of an enterprise autonomous agent."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class GovernanceScopeType(StrEnum):
    """Hierarchy level for enterprise governance policies."""

    ORGANIZATION = "ORGANIZATION"
    DEPARTMENT = "DEPARTMENT"
    TEAM = "TEAM"


class EnterpriseAgentRecord(TenantOwnedResource):
    """Registered enterprise AI agent metadata, allowed capabilities, and resource envelopes."""

    agent_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    owner_user_id: str
    status: AgentLifecycleStatus = AgentLifecycleStatus.ACTIVE
    model_constraints: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_skills: list[str] = Field(default_factory=list)
    allowed_workflows: list[str] = Field(default_factory=list)
    resource_limits: dict[str, Any] = Field(default_factory=dict)


class EnterprisePolicyEnvelope(TenantOwnedResource):
    """Enterprise policy envelope defining security constraints, tool bans, and approval triggers."""

    policy_id: str
    scope_type: GovernanceScopeType
    scope_id: str  # org_id, dept_id, or team_id
    disallowed_tools: list[str] = Field(default_factory=list)
    disallowed_skills: list[str] = Field(default_factory=list)
    disallowed_models: list[str] = Field(default_factory=list)
    require_approval_for_tools: list[str] = Field(default_factory=list)
    require_dual_custody: bool = False
    max_cost_per_task_usd: float = 100.0
    rules: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True


class ConnectorType(StrEnum):
    """Supported enterprise integration categories."""

    CRM = "CRM"
    ERP = "ERP"
    PROJECT_MANAGEMENT = "PROJECT_MANAGEMENT"
    COMMUNICATION = "COMMUNICATION"
    CLOUD_STORAGE = "CLOUD_STORAGE"
    WEBHOOK = "WEBHOOK"


class ConnectorStatus(StrEnum):
    """Lifecycle and verification status of an enterprise connector."""

    UNVERIFIED = "UNVERIFIED"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    DISABLED = "DISABLED"


class IntegrationConnectorRecord(TenantOwnedResource):
    """Registered enterprise integration connector configuration and status."""

    connector_id: str
    name: str
    connector_type: ConnectorType
    provider: str  # salesforce, jira, slack, github, generic_webhook
    config: dict[str, Any] = Field(default_factory=dict)
    secret_id: str  # Pointer to vaulted credentials
    status: ConnectorStatus = ConnectorStatus.UNVERIFIED
    last_verified_at: datetime | None = None
    rate_limit_rpm: int = 60
    retry_max_attempts: int = 3
    is_active: bool = True


class AuditRecord(TenantOwnedResource):
    """Immutable audit trail record cryptographically bound to previous hash."""

    record_id: str
    sequence: int
    event_type: str
    actor_id: str
    actor_type: str  # USER, AGENT, SERVICE
    action: str
    target_resource_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    previous_hash: str
    record_hash: str


class CostRecord(TenantOwnedResource):
    """Measured operational resource and model cost attribution record."""

    record_id: str
    task_id: str
    agent_id: str | None = None
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    compute_duration_ms: int = 0
    token_cost_usd: float = 0.0
    compute_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DepartmentBudget(TenantOwnedResource):
    """Departmental financial budget envelope with spending cap enforcement."""

    budget_id: str
    department_id: str
    allocated_usd: float = 10_000.0
    spent_usd: float = 0.0
    alert_threshold_pct: float = 80.0
    hard_cap_enabled: bool = True
    period_start: datetime = Field(default_factory=lambda: datetime.now(UTC))
    period_end: datetime = Field(default_factory=lambda: datetime.now(UTC))
