"""Enterprise REST API routes for multi-tenant governance, IAM, agents, connectors, audit, and cost."""

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from atlas_enterprise import (
    AgentLifecycleStatus,
    AuditTamperDetectedError,
    ConnectorType,
    EnterpriseAgentGovernanceManager,
    EnterpriseAnalyticsEngine,
    EnterpriseAuditLedger,
    EnterpriseCostManager,
    EnterpriseIAMEngine,
    EnterpriseOrganizationManager,
    EnterpriseStorage,
    GovernanceScopeType,
    IntegrationHubManager,
    MembershipRole,
    PermissionAction,
    SessionToken,
)
from atlas_enterprise.iam import (
    AgentSelfElevationError,
    PrivilegeEscalationError,
    SessionExpiredError,
    SessionRevokedError,
    UnauthorizedError,
    can_assign_role,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/enterprise", tags=["Enterprise Platform"])


def _get_services(
    request: Request,
) -> tuple[
    EnterpriseOrganizationManager,
    EnterpriseIAMEngine,
    EnterpriseAgentGovernanceManager,
    IntegrationHubManager,
    EnterpriseAuditLedger,
    EnterpriseCostManager,
    EnterpriseAnalyticsEngine,
]:
    state = request.app.state

    storage = getattr(state, "enterprise_storage", None)
    if storage is None:
        db_path = getattr(
            state, "enterprise_db_path", os.getenv("ATLAS_ENTERPRISE_DB_PATH", ":memory:")
        )
        storage = EnterpriseStorage(db_path=db_path)
        state.enterprise_storage = storage

    org_manager = getattr(state, "enterprise_org_manager", None)
    if org_manager is None:
        org_manager = EnterpriseOrganizationManager(storage=storage)
        state.enterprise_org_manager = org_manager

    iam_engine = getattr(state, "enterprise_iam_engine", None)
    if iam_engine is None:
        iam_engine = EnterpriseIAMEngine(org_manager, storage=storage)
        state.enterprise_iam_engine = iam_engine

    gov_manager = getattr(state, "enterprise_gov_manager", None)
    if gov_manager is None:
        gov_manager = EnterpriseAgentGovernanceManager(org_manager, iam_engine, storage=storage)
        state.enterprise_gov_manager = gov_manager

    hub_manager = getattr(state, "enterprise_hub_manager", None)
    if hub_manager is None:
        hub_manager = IntegrationHubManager(org_manager, iam_engine, storage=storage)
        state.enterprise_hub_manager = hub_manager

    audit_ledger = getattr(state, "enterprise_audit_ledger", None)
    if audit_ledger is None:
        audit_ledger = EnterpriseAuditLedger(org_manager, iam_engine, storage=storage)
        state.enterprise_audit_ledger = audit_ledger

    cost_manager = getattr(state, "enterprise_cost_manager", None)
    if cost_manager is None:
        cost_manager = EnterpriseCostManager(org_manager, iam_engine, storage=storage)
        state.enterprise_cost_manager = cost_manager

    analytics_engine = getattr(state, "enterprise_analytics_engine", None)
    if analytics_engine is None:
        analytics_engine = EnterpriseAnalyticsEngine(
            org_manager, iam_engine, audit_ledger, cost_manager
        )
        state.enterprise_analytics_engine = analytics_engine

    return (
        org_manager,
        iam_engine,
        gov_manager,
        hub_manager,
        audit_ledger,
        cost_manager,
        analytics_engine,
    )


# -----------------------------------------------------------------------------
# Enterprise Authentication & Authorization Dependency (SEC-01)
# -----------------------------------------------------------------------------


def get_current_enterprise_session(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> SessionToken:
    """Validate bearer session token or service API key, or system admin key."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_api_key and x_api_key.strip():
        token = x_api_key.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials required (Bearer session token or API key).",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _, iam_engine, _, _, _, _, _ = _get_services(request)

    # 1. Platform Super-Admin Key
    admin_key = os.getenv("ATLAS_API_KEY_ADMIN", "admin-key")
    if token == admin_key:
        now = datetime.now(UTC)
        return SessionToken(
            token_id="atk_sess_platform_admin",
            user_id="usr_platform_admin",
            org_id="*",
            role=MembershipRole.ORG_OWNER,
            client_ip=request.client.host if request.client else None,
            issued_at=now,
            expires_at=now + timedelta(hours=24),
            is_revoked=False,
        )

    # 2. Service Identity API Key (atk_live_...)
    if token.startswith("atk_live_"):
        try:
            svc = iam_engine.authenticate_api_key(token)
            now = datetime.now(UTC)
            return SessionToken(
                token_id=f"atk_sess_svc_{svc.service_id}",
                user_id=svc.service_id,
                org_id=svc.org_id,
                role=MembershipRole.OPERATOR,
                department_id=svc.department_id,
                client_ip=request.client.host if request.client else None,
                issued_at=now,
                expires_at=svc.expires_at or (now + timedelta(hours=24)),
                is_revoked=False,
            )
        except UnauthorizedError as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e

    # 3. User Session Token (atk_sess_...)
    try:
        session = iam_engine.validate_session(
            token, client_ip=request.client.host if request.client else None
        )
        return session
    except (UnauthorizedError, SessionExpiredError, SessionRevokedError) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e


def require_org_access(
    org_id: str,
    session: SessionToken,
    iam_engine: EnterpriseIAMEngine,
    required_action: PermissionAction | None = None,
) -> None:
    """Enforce tenant isolation and RBAC permission boundary."""
    if session.org_id != "*" and session.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cross-tenant access forbidden: session belongs to '{session.org_id}', not '{org_id}'",
        )
    if required_action and session.org_id != "*":
        try:
            iam_engine.assert_permission(
                user_id=session.user_id,
                org_id=org_id,
                action=required_action,
            )
        except UnauthorizedError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


# -----------------------------------------------------------------------------
# Request Schemas
# -----------------------------------------------------------------------------


class CreateOrgRequest(BaseModel):
    name: str
    slug: str
    owner_email: str
    owner_name: str
    settings: dict[str, Any] = Field(default_factory=dict)
    retention_days: int = 90
    max_concurrent_workers: int = 100


class CreateDeptRequest(BaseModel):
    name: str
    slug: str
    lead_user_id: str | None = None
    budget_usd: float = 10_000.0


class AddMemberRequest(BaseModel):
    email: str
    full_name: str
    role: MembershipRole = MembershipRole.VIEWER
    department_id: str | None = None


class LoginRequest(BaseModel):
    user_id: str
    org_id: str


class CreateServiceIdentityRequest(BaseModel):
    org_id: str
    name: str
    scopes: list[str] = Field(default_factory=list)
    department_id: str | None = None
    expires_in_days: int = 90


class RegisterAgentRequest(BaseModel):
    caller_user_id: str
    org_id: str
    name: str
    owner_user_id: str
    allowed_tools: list[str]
    allowed_skills: list[str] = Field(default_factory=list)
    allowed_workflows: list[str] = Field(default_factory=list)
    model_constraints: dict[str, Any] = Field(default_factory=dict)
    resource_limits: dict[str, Any] = Field(default_factory=dict)
    department_id: str | None = None
    team_id: str | None = None


class SetPolicyRequest(BaseModel):
    caller_user_id: str
    org_id: str
    scope_type: GovernanceScopeType
    scope_id: str
    disallowed_tools: list[str] = Field(default_factory=list)
    disallowed_skills: list[str] = Field(default_factory=list)
    disallowed_models: list[str] = Field(default_factory=list)
    require_approval_for_tools: list[str] = Field(default_factory=list)
    require_dual_custody: bool = False
    max_cost_per_task_usd: float = 100.0


class RegisterConnectorRequest(BaseModel):
    caller_user_id: str
    org_id: str
    name: str
    connector_type: ConnectorType
    provider: str
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    rate_limit_rpm: int = 60
    department_id: str | None = None


class InvokeConnectorRequest(BaseModel):
    caller_id: str
    action_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class RecordCostRequest(BaseModel):
    org_id: str
    task_id: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    compute_duration_ms: int
    department_id: str | None = None
    agent_id: str | None = None


class SetBudgetRequest(BaseModel):
    caller_user_id: str
    org_id: str
    department_id: str
    allocated_usd: float
    alert_threshold_pct: float = 80.0
    hard_cap_enabled: bool = True


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------


@router.post("/organizations")
def create_organization(payload: CreateOrgRequest, request: Request) -> dict[str, Any]:
    """Provision a new top-level enterprise organization and root owner identity."""
    org_mgr, iam_engine, _, _, audit, _, _ = _get_services(request)
    try:
        org, owner, mem = org_mgr.create_organization(
            name=payload.name,
            slug=payload.slug,
            owner_email=payload.owner_email,
            owner_name=payload.owner_name,
            settings=payload.settings,
            retention_days=payload.retention_days,
            max_concurrent_workers=payload.max_concurrent_workers,
        )
        audit.append_entry(
            org_id=org.org_id,
            event_type="ORG_PROVISIONED",
            actor_id=owner.user_id,
            actor_type="USER",
            action="organization.create",
            details={"name": org.name, "slug": org.slug},
        )
        # Mint initial authenticated session token for the owner
        session = iam_engine.create_session(user_id=owner.user_id, org_id=org.org_id)
        return {
            "organization": org.model_dump(mode="json"),
            "owner": owner.model_dump(mode="json"),
            "membership": mem.model_dump(mode="json"),
            "session_token": session.token_id,
            "token_id": session.token_id,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/organizations")
def list_organizations(
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> list[dict[str, Any]]:
    """List enterprise organizations accessible to the authenticated session."""
    org_mgr, _, _, _, _, _, _ = _get_services(request)
    all_orgs = org_mgr.list_organizations()
    if session.org_id == "*":
        return [o.model_dump(mode="json") for o in all_orgs]
    return [o.model_dump(mode="json") for o in all_orgs if o.org_id == session.org_id]


@router.get("/organizations/{org_id}")
def get_organization(
    org_id: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Retrieve organization metadata."""
    org_mgr, iam_engine, _, _, _, _, _ = _get_services(request)
    require_org_access(org_id, session, iam_engine, PermissionAction.ORG_READ)
    try:
        org = org_mgr.get_organization(org_id)
        if not org:
            raise HTTPException(status_code=404, detail=f"Organization '{org_id}' not found")
        return org.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/organizations/{org_id}/suspend")
def suspend_organization(
    org_id: str,
    reason: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Administrative suspension of an organization."""
    org_mgr, iam_engine, _, _, audit, _, _ = _get_services(request)
    require_org_access(org_id, session, iam_engine, PermissionAction.ORG_UPDATE)
    try:
        org = org_mgr.suspend_organization(org_id, reason=reason)
        audit.append_entry(
            org_id=org_id,
            event_type="ORG_SUSPENDED",
            actor_id=session.user_id,
            actor_type="USER",
            action="organization.suspend",
            details={"reason": reason},
        )
        return org.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/organizations/{org_id}/departments")
def create_department(
    org_id: str,
    payload: CreateDeptRequest,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Create a new department within an organization."""
    org_mgr, iam_engine, _, _, audit, _, _ = _get_services(request)
    require_org_access(org_id, session, iam_engine, PermissionAction.DEPT_MANAGE)
    try:
        dept = org_mgr.create_department(
            org_id=org_id,
            name=payload.name,
            slug=payload.slug,
            lead_user_id=payload.lead_user_id,
            budget_usd=payload.budget_usd,
        )
        audit.append_entry(
            org_id=org_id,
            department_id=dept.department_id,
            event_type="DEPARTMENT_CREATED",
            actor_id=session.user_id,
            actor_type="USER",
            action="department.create",
            details={"name": dept.name, "slug": dept.slug},
        )
        return dept.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/organizations/{org_id}/departments")
def list_departments(
    org_id: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> list[dict[str, Any]]:
    """List departments within an organization."""
    org_mgr, iam_engine, _, _, _, _, _ = _get_services(request)
    require_org_access(org_id, session, iam_engine, PermissionAction.ORG_READ)
    depts = [d for d in org_mgr._departments.values() if d.org_id == org_id] or (
        org_mgr.storage.list_departments(org_id) if org_mgr.storage else []
    )
    return [d.model_dump(mode="json") for d in depts]


@router.post("/organizations/{org_id}/members")
def add_member(
    org_id: str,
    payload: AddMemberRequest,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Enroll a user into an organization with role assignment (SEC-01 & SEC-02)."""
    org_mgr, iam_engine, _, _, audit, _, _ = _get_services(request)
    require_org_access(org_id, session, iam_engine, PermissionAction.MEMBER_MANAGE)

    # Privilege Escalation Guard: caller cannot grant a role equal to or higher than their own
    if session.org_id != "*" and not can_assign_role(session.role, payload.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Privilege escalation prevented: role '{session.role}' cannot assign role '{payload.role}'",
        )

    try:
        user, mem = org_mgr.add_member(
            org_id=org_id,
            email=payload.email,
            full_name=payload.full_name,
            role=payload.role,
            department_id=payload.department_id,
        )
        audit.append_entry(
            org_id=org_id,
            department_id=payload.department_id,
            event_type="MEMBER_ENROLLED",
            actor_id=session.user_id,
            actor_type="USER",
            action="member.enroll",
            details={"email": user.email, "role": mem.role.value},
        )
        return {"user": user.model_dump(mode="json"), "membership": mem.model_dump(mode="json")}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/organizations/{org_id}/members")
def list_members(
    org_id: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> list[dict[str, Any]]:
    """List members belonging to an organization."""
    org_mgr, iam_engine, _, _, _, _, _ = _get_services(request)
    require_org_access(org_id, session, iam_engine, PermissionAction.ORG_READ)
    members = org_mgr.list_members(org_id)
    return [
        {"user": u.model_dump(mode="json"), "membership": m.model_dump(mode="json")}
        for u, m in members
    ]


@router.post("/iam/login")
def login(payload: LoginRequest, request: Request) -> dict[str, Any]:
    """Authenticate credentials and generate active session token."""
    _, iam, _, _, audit, _, _ = _get_services(request)
    try:
        client_ip = request.client.host if request.client else None
        session = iam.create_session(
            user_id=payload.user_id,
            org_id=payload.org_id,
            client_ip=client_ip,
        )
        audit.append_entry(
            org_id=payload.org_id,
            event_type="IAM_LOGIN",
            actor_id=payload.user_id,
            actor_type="USER",
            action="login.success",
            details={"client_ip": client_ip},
        )
        return session.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/iam/sessions/{token_id}/revoke")
def revoke_session(
    token_id: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, str]:
    """Revoke an active session token."""
    _, iam, _, _, _, _, _ = _get_services(request)
    try:
        iam.revoke_session(token_id)
        return {"status": "revoked", "token_id": token_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/iam/service-identities")
def create_service_identity(
    payload: CreateServiceIdentityRequest,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Create a scoped service identity with raw secret API key."""
    _, iam, _, _, audit, _, _ = _get_services(request)
    require_org_access(payload.org_id, session, iam, PermissionAction.IAM_MANAGE_CREDENTIALS)
    try:
        svc, raw_key = iam.create_service_identity(
            org_id=payload.org_id,
            name=payload.name,
            scopes=payload.scopes,
            department_id=payload.department_id,
            expires_in_days=payload.expires_in_days,
        )
        audit.append_entry(
            org_id=payload.org_id,
            event_type="SERVICE_IDENTITY_CREATED",
            actor_id=session.user_id,
            actor_type="USER",
            action="service_identity.create",
            details={"service_id": svc.service_id, "name": svc.name},
        )
        return {"service": svc.model_dump(mode="json"), "api_key": raw_key}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/agents")
def register_agent(
    payload: RegisterAgentRequest,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Register an autonomous agent under organizational governance."""
    _, _, gov, _, audit, _, _ = _get_services(request)
    require_org_access(payload.org_id, session, gov.iam_engine, PermissionAction.AGENT_REGISTER)
    try:
        caller = session.user_id if session.org_id != "*" else payload.caller_user_id
        agent = gov.register_agent(
            caller_user_id=caller,
            org_id=payload.org_id,
            name=payload.name,
            owner_user_id=payload.owner_user_id,
            allowed_tools=payload.allowed_tools,
            allowed_skills=payload.allowed_skills,
            allowed_workflows=payload.allowed_workflows,
            model_constraints=payload.model_constraints,
            resource_limits=payload.resource_limits,
            department_id=payload.department_id,
            team_id=payload.team_id,
        )
        audit.append_entry(
            org_id=payload.org_id,
            department_id=payload.department_id,
            event_type="AGENT_REGISTERED",
            actor_id=caller,
            actor_type="USER",
            action="agent.register",
            details={"agent_id": agent.agent_id, "name": agent.name},
        )
        return agent.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agents/{agent_id}")
def get_agent(
    agent_id: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
    org_id: str | None = None,
) -> dict[str, Any]:
    """Retrieve agent metadata with tenant boundary check."""
    _, _, gov, _, _, _, _ = _get_services(request)
    try:
        target_org = session.org_id if session.org_id != "*" else org_id
        agent = gov.get_agent(agent_id, caller_org_id=target_org)
        return agent.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/status")
def update_agent_status(
    agent_id: str,
    caller_user_id: str,
    new_status: AgentLifecycleStatus,
    reason: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Update agent lifecycle status."""
    _, _, gov, _, audit, _, _ = _get_services(request)
    try:
        agent = gov.update_agent_status(caller_user_id, agent_id, new_status, reason)
        require_org_access(agent.org_id, session, gov.iam_engine, PermissionAction.AGENT_UPDATE)
        audit.append_entry(
            org_id=agent.org_id,
            event_type="AGENT_STATUS_UPDATED",
            actor_id=session.user_id,
            actor_type="USER",
            action="agent.update_status",
            details={"agent_id": agent_id, "new_status": new_status, "reason": reason},
        )
        return agent.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/policies")
def set_policy(
    payload: SetPolicyRequest,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Configure enterprise policy envelope at Org, Dept, or Team scope."""
    _, _, gov, _, audit, _, _ = _get_services(request)
    require_org_access(payload.org_id, session, gov.iam_engine, PermissionAction.IAM_MANAGE_POLICY)
    caller = session.user_id if session.org_id != "*" else payload.caller_user_id
    try:
        policy = gov.set_policy(
            caller_user_id=caller,
            org_id=payload.org_id,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            disallowed_tools=payload.disallowed_tools,
            disallowed_skills=payload.disallowed_skills,
            disallowed_models=payload.disallowed_models,
            require_approval_for_tools=payload.require_approval_for_tools,
            require_dual_custody=payload.require_dual_custody,
            max_cost_per_task_usd=payload.max_cost_per_task_usd,
        )
        audit.append_entry(
            org_id=payload.org_id,
            event_type="POLICY_CONFIGURED",
            actor_id=caller,
            actor_type="USER",
            action="policy.set",
            details={"policy_id": policy.policy_id, "scope": payload.scope_type},
        )
        return policy.model_dump(mode="json")
    except (AgentSelfElevationError, PrivilegeEscalationError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/connectors")
def register_connector(
    payload: RegisterConnectorRequest,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Register a new third-party integration connector."""
    _, _, _, hub, audit, _, _ = _get_services(request)
    require_org_access(payload.org_id, session, hub.iam_engine, PermissionAction.INTEGRATION_MANAGE)
    caller = session.user_id if session.org_id != "*" else payload.caller_user_id
    try:
        conn = hub.register_connector(
            caller_user_id=caller,
            org_id=payload.org_id,
            name=payload.name,
            connector_type=payload.connector_type,
            provider=payload.provider,
            config=payload.config,
            secrets=payload.secrets,
            rate_limit_rpm=payload.rate_limit_rpm,
            department_id=payload.department_id,
        )
        audit.append_entry(
            org_id=payload.org_id,
            department_id=payload.department_id,
            event_type="CONNECTOR_REGISTERED",
            actor_id=caller,
            actor_type="USER",
            action="connector.register",
            details={"connector_id": conn.connector_id, "provider": conn.provider},
        )
        return conn.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/connectors")
def list_connectors(
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
    org_id: str | None = None,
) -> list[dict[str, Any]]:
    """List registered connectors for an organization."""
    _, _, _, hub, _, _, _ = _get_services(request)
    target_org = org_id or (session.org_id if session.org_id != "*" else None)
    if target_org:
        require_org_access(target_org, session, hub.iam_engine, PermissionAction.INTEGRATION_READ)
    connectors = hub.list_connectors(target_org)
    return [c.model_dump(mode="json") for c in connectors]


@router.post("/connectors/{connector_id}/verify")
def verify_connector(
    connector_id: str,
    caller_user_id: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Verify connector credentials via live handshake."""
    _, _, _, hub, audit, _, _ = _get_services(request)
    conn = hub.get_connector(connector_id)
    require_org_access(conn.org_id, session, hub.iam_engine, PermissionAction.INTEGRATION_MANAGE)
    caller = session.user_id if session.org_id != "*" else caller_user_id
    try:
        success, reason = hub.verify_connector(caller, connector_id)
        conn = hub.get_connector(connector_id)
        audit.append_entry(
            org_id=conn.org_id,
            event_type="CONNECTOR_VERIFIED",
            actor_id=caller,
            actor_type="USER",
            action="connector.verify",
            details={"connector_id": connector_id, "success": success, "reason": reason},
        )
        return {"success": success, "reason": reason, "status": conn.status}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/connectors/{connector_id}/invoke")
def invoke_connector(
    connector_id: str,
    payload: InvokeConnectorRequest,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Invoke a connector action with authorization and rate limiting."""
    _, _, _, hub, audit, _, _ = _get_services(request)
    conn = hub.get_connector(connector_id)
    require_org_access(conn.org_id, session, hub.iam_engine, PermissionAction.INTEGRATION_INVOKE)
    caller = session.user_id if session.org_id != "*" else payload.caller_id
    try:
        res = hub.invoke_connector(
            caller_id=caller,
            connector_id=connector_id,
            action_name=payload.action_name,
            parameters=payload.parameters,
        )
        audit.append_entry(
            org_id=conn.org_id,
            event_type="CONNECTOR_INVOKED",
            actor_id=caller,
            actor_type="SERVICE",
            action=payload.action_name,
            details={"connector_id": connector_id},
        )
        return res
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/webhooks/{connector_id}")
async def handle_inbound_webhook(
    connector_id: str,
    request: Request,
    x_hub_signature_256: str = Header(default=""),
) -> dict[str, Any]:
    """Handle inbound webhook with HMAC signature verification and event dispatch (Gap B)."""
    _, _, _, hub, audit, _, _ = _get_services(request)
    body = await request.body()
    try:
        is_valid = hub.verify_inbound_webhook(
            connector_id=connector_id,
            payload_bytes=body,
            signature_header=x_hub_signature_256,
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid HMAC webhook signature",
            )

        conn = hub.get_connector(connector_id)
        audit.append_entry(
            org_id=conn.org_id,
            event_type="WEBHOOK_INGESTED",
            actor_id="external_webhook",
            actor_type="SERVICE",
            action="webhook.ingest",
            details={"connector_id": connector_id, "bytes_received": len(body)},
        )
        return {
            "status": "accepted",
            "connector_id": connector_id,
            "dispatched": True,
            "bytes_processed": len(body),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/audit")
def query_audit_logs(
    caller_user_id: str,
    org_id: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query audit ledger records."""
    _, _, _, _, audit, _, _ = _get_services(request)
    require_org_access(org_id, session, audit.iam_engine, PermissionAction.AUDIT_READ)
    caller = session.user_id if session.org_id != "*" else caller_user_id
    try:
        records = audit.query_records(caller_user_id=caller, org_id=org_id, limit=limit)
        return [r.model_dump(mode="json") for r in records]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/audit/export")
def export_audit_trail(
    org_id: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> list[dict[str, Any]]:
    """Export complete verifiable audit trail for compliance (Gap C)."""
    _, _, _, _, audit, _, _ = _get_services(request)
    require_org_access(org_id, session, audit.iam_engine, PermissionAction.AUDIT_EXPORT)
    caller = session.user_id if session.org_id != "*" else "usr_export_admin"
    try:
        return audit.export_audit_trail(caller_user_id=caller, org_id=org_id)
    except AuditTamperDetectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/audit/verify")
def verify_audit_chain(
    org_id: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Verify cryptographic SHA-256 hash chain integrity."""
    _, _, _, _, audit, _, _ = _get_services(request)
    require_org_access(org_id, session, audit.iam_engine, PermissionAction.AUDIT_READ)
    is_intact, seq, reason = audit.verify_chain_integrity(org_id)
    return {
        "org_id": org_id,
        "is_intact": is_intact,
        "broken_sequence": seq,
        "reason": reason,
    }


@router.post("/cost/usage")
def record_cost_usage(
    payload: RecordCostRequest,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Record token and compute usage."""
    _, _, _, _, _, cost_mgr, _ = _get_services(request)
    require_org_access(payload.org_id, session, cost_mgr.iam_engine, PermissionAction.COST_READ)
    try:
        rec, is_alert = cost_mgr.record_usage(
            org_id=payload.org_id,
            task_id=payload.task_id,
            model_name=payload.model_name,
            prompt_tokens=payload.prompt_tokens,
            completion_tokens=payload.completion_tokens,
            compute_duration_ms=payload.compute_duration_ms,
            department_id=payload.department_id,
            agent_id=payload.agent_id,
        )
        return {
            "record": rec.model_dump(mode="json"),
            "is_alert_triggered": is_alert,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cost/summary")
def get_cost_summary(
    caller_user_id: str,
    org_id: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
    department_id: str | None = None,
) -> dict[str, Any]:
    """Aggregate total cost and token consumption."""
    _, _, _, _, _, cost_mgr, _ = _get_services(request)
    require_org_access(org_id, session, cost_mgr.iam_engine, PermissionAction.COST_READ)
    caller = session.user_id if session.org_id != "*" else caller_user_id
    try:
        return cost_mgr.get_cost_summary(
            caller_user_id=caller,
            org_id=org_id,
            department_id=department_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/cost/budgets")
def set_department_budget(
    payload: SetBudgetRequest,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
) -> dict[str, Any]:
    """Set departmental budget envelope."""
    _, _, _, _, _, cost_mgr, _ = _get_services(request)
    require_org_access(payload.org_id, session, cost_mgr.iam_engine, PermissionAction.BUDGET_MANAGE)
    caller = session.user_id if session.org_id != "*" else payload.caller_user_id
    try:
        budget = cost_mgr.set_department_budget(
            caller_user_id=caller,
            org_id=payload.org_id,
            department_id=payload.department_id,
            allocated_usd=payload.allocated_usd,
            alert_threshold_pct=payload.alert_threshold_pct,
            hard_cap_enabled=payload.hard_cap_enabled,
        )
        return budget.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analytics")
def get_operational_metrics(
    caller_user_id: str,
    org_id: str,
    request: Request,
    session: Annotated[SessionToken, Depends(get_current_enterprise_session)],
    department_id: str | None = None,
) -> dict[str, Any]:
    """Get operational performance metrics and compliance score."""
    _, _, _, _, _, _, analytics = _get_services(request)
    require_org_access(org_id, session, analytics.iam_engine, PermissionAction.AUDIT_READ)
    caller = session.user_id if session.org_id != "*" else caller_user_id
    try:
        return analytics.get_operational_metrics(
            caller_user_id=caller,
            org_id=org_id,
            department_id=department_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
