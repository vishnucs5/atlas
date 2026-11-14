"""Enterprise REST API routes for multi-tenant governance, IAM, agents, connectors, audit, and cost."""

from typing import Any

from atlas_enterprise import (
    AgentLifecycleStatus,
    ConnectorType,
    EnterpriseAgentGovernanceManager,
    EnterpriseAnalyticsEngine,
    EnterpriseAuditLedger,
    EnterpriseCostManager,
    EnterpriseIAMEngine,
    EnterpriseOrganizationManager,
    GovernanceScopeType,
    IntegrationHubManager,
    MembershipRole,
)
from fastapi import APIRouter, Header, HTTPException, Request
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
    org_manager = getattr(state, "enterprise_org_manager", None)
    if org_manager is None:
        org_manager = EnterpriseOrganizationManager()
        state.enterprise_org_manager = org_manager

    iam_engine = getattr(state, "enterprise_iam_engine", None)
    if iam_engine is None:
        iam_engine = EnterpriseIAMEngine(org_manager)
        state.enterprise_iam_engine = iam_engine

    gov_manager = getattr(state, "enterprise_gov_manager", None)
    if gov_manager is None:
        gov_manager = EnterpriseAgentGovernanceManager(org_manager, iam_engine)
        state.enterprise_gov_manager = gov_manager

    hub_manager = getattr(state, "enterprise_hub_manager", None)
    if hub_manager is None:
        hub_manager = IntegrationHubManager(org_manager, iam_engine)
        state.enterprise_hub_manager = hub_manager

    audit_ledger = getattr(state, "enterprise_audit_ledger", None)
    if audit_ledger is None:
        audit_ledger = EnterpriseAuditLedger(org_manager, iam_engine)
        state.enterprise_audit_ledger = audit_ledger

    cost_manager = getattr(state, "enterprise_cost_manager", None)
    if cost_manager is None:
        cost_manager = EnterpriseCostManager(org_manager, iam_engine)
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
    org_mgr, _, _, _, audit, _, _ = _get_services(request)
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
        return {
            "organization": org.model_dump(mode="json"),
            "owner": owner.model_dump(mode="json"),
            "membership": mem.model_dump(mode="json"),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/organizations/{org_id}")
def get_organization(org_id: str, request: Request) -> dict[str, Any]:
    org_mgr, _, _, _, _, _, _ = _get_services(request)
    try:
        org = org_mgr.get_organization(org_id)
        return org.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/organizations/{org_id}/suspend")
def suspend_organization(org_id: str, reason: str, request: Request) -> dict[str, Any]:
    org_mgr, _, _, _, audit, _, _ = _get_services(request)
    try:
        org = org_mgr.suspend_organization(org_id, reason=reason)
        audit.append_entry(
            org_id=org_id,
            event_type="ORG_SUSPENDED",
            actor_id="system",
            actor_type="SYSTEM",
            action="organization.suspend",
            details={"reason": reason},
        )
        return org.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/organizations/{org_id}/departments")
def create_department(org_id: str, payload: CreateDeptRequest, request: Request) -> dict[str, Any]:
    org_mgr, _, _, _, audit, _, _ = _get_services(request)
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
            actor_id="admin",
            actor_type="USER",
            action="department.create",
            details={"name": dept.name, "slug": dept.slug},
        )
        return dept.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/organizations/{org_id}/members")
def add_member(org_id: str, payload: AddMemberRequest, request: Request) -> dict[str, Any]:
    org_mgr, _, _, _, audit, _, _ = _get_services(request)
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
            actor_id=user.user_id,
            actor_type="USER",
            action="member.enroll",
            details={"email": user.email, "role": mem.role.value},
        )
        return {"user": user.model_dump(mode="json"), "membership": mem.model_dump(mode="json")}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/iam/login")
def login(payload: LoginRequest, request: Request) -> dict[str, Any]:
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
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/iam/sessions/{token_id}/revoke")
def revoke_session(token_id: str, request: Request) -> dict[str, str]:
    _, iam, _, _, _, _, _ = _get_services(request)
    try:
        iam.revoke_session(token_id)
        return {"status": "revoked", "token_id": token_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/iam/service-identities")
def create_service_identity(
    payload: CreateServiceIdentityRequest, request: Request
) -> dict[str, Any]:
    _, iam, _, _, audit, _, _ = _get_services(request)
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
            actor_id="admin",
            actor_type="USER",
            action="service_identity.create",
            details={"service_id": svc.service_id, "name": svc.name},
        )
        return {"service": svc.model_dump(mode="json"), "api_key": raw_key}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/agents")
def register_agent(payload: RegisterAgentRequest, request: Request) -> dict[str, Any]:
    _, _, gov, _, audit, _, _ = _get_services(request)
    try:
        agent = gov.register_agent(
            caller_user_id=payload.caller_user_id,
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
            actor_id=payload.caller_user_id,
            actor_type="USER",
            action="agent.register",
            details={"agent_id": agent.agent_id, "name": agent.name},
        )
        return agent.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, request: Request, org_id: str | None = None) -> dict[str, Any]:
    _, _, gov, _, _, _, _ = _get_services(request)
    try:
        agent = gov.get_agent(agent_id, caller_org_id=org_id)
        return agent.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/status")
def update_agent_status(
    agent_id: str,
    caller_user_id: str,
    new_status: AgentLifecycleStatus,
    reason: str,
    request: Request,
) -> dict[str, Any]:
    _, _, gov, _, audit, _, _ = _get_services(request)
    try:
        agent = gov.update_agent_status(caller_user_id, agent_id, new_status, reason)
        audit.append_entry(
            org_id=agent.org_id,
            event_type="AGENT_STATUS_UPDATED",
            actor_id=caller_user_id,
            actor_type="USER",
            action="agent.update_status",
            details={"agent_id": agent_id, "new_status": new_status, "reason": reason},
        )
        return agent.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/policies")
def set_policy(payload: SetPolicyRequest, request: Request) -> dict[str, Any]:
    _, _, gov, _, audit, _, _ = _get_services(request)
    try:
        policy = gov.set_policy(
            caller_user_id=payload.caller_user_id,
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
            actor_id=payload.caller_user_id,
            actor_type="USER",
            action="policy.set",
            details={"policy_id": policy.policy_id, "scope": payload.scope_type},
        )
        return policy.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/connectors")
def register_connector(payload: RegisterConnectorRequest, request: Request) -> dict[str, Any]:
    _, _, _, hub, audit, _, _ = _get_services(request)
    try:
        conn = hub.register_connector(
            caller_user_id=payload.caller_user_id,
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
            actor_id=payload.caller_user_id,
            actor_type="USER",
            action="connector.register",
            details={"connector_id": conn.connector_id, "provider": conn.provider},
        )
        return conn.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/connectors/{connector_id}/verify")
def verify_connector(connector_id: str, caller_user_id: str, request: Request) -> dict[str, Any]:
    _, _, _, hub, audit, _, _ = _get_services(request)
    try:
        success, reason = hub.verify_connector(caller_user_id, connector_id)
        conn = hub.get_connector(connector_id)
        audit.append_entry(
            org_id=conn.org_id,
            event_type="CONNECTOR_VERIFIED",
            actor_id=caller_user_id,
            actor_type="USER",
            action="connector.verify",
            details={"connector_id": connector_id, "success": success, "reason": reason},
        )
        return {"success": success, "reason": reason, "status": conn.status}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/connectors/{connector_id}/invoke")
def invoke_connector(
    connector_id: str, payload: InvokeConnectorRequest, request: Request
) -> dict[str, Any]:
    _, _, _, hub, audit, _, _ = _get_services(request)
    try:
        res = hub.invoke_connector(
            caller_id=payload.caller_id,
            connector_id=connector_id,
            action_name=payload.action_name,
            parameters=payload.parameters,
        )
        conn = hub.get_connector(connector_id)
        audit.append_entry(
            org_id=conn.org_id,
            event_type="CONNECTOR_INVOKED",
            actor_id=payload.caller_id,
            actor_type="SERVICE",
            action=payload.action_name,
            details={"connector_id": connector_id},
        )
        return res
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/webhooks/{connector_id}")
async def handle_inbound_webhook(
    connector_id: str,
    request: Request,
    x_hub_signature_256: str = Header(default=""),
) -> dict[str, str]:
    _, _, _, hub, audit, _, _ = _get_services(request)
    body = await request.body()
    try:
        is_valid = hub.verify_inbound_webhook(
            connector_id=connector_id,
            payload_bytes=body,
            signature_header=x_hub_signature_256,
        )
        if not is_valid:
            raise HTTPException(status_code=401, detail="Invalid HMAC webhook signature")

        conn = hub.get_connector(connector_id)
        audit.append_entry(
            org_id=conn.org_id,
            event_type="WEBHOOK_INGESTED",
            actor_id="external_webhook",
            actor_type="SERVICE",
            action="webhook.ingest",
            details={"connector_id": connector_id},
        )
        return {"status": "accepted"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/audit")
def query_audit_logs(
    caller_user_id: str,
    org_id: str,
    request: Request,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _, _, _, _, audit, _, _ = _get_services(request)
    try:
        records = audit.query_records(caller_user_id=caller_user_id, org_id=org_id, limit=limit)
        return [r.model_dump(mode="json") for r in records]
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/audit/verify")
def verify_audit_chain(org_id: str, request: Request) -> dict[str, Any]:
    _, _, _, _, audit, _, _ = _get_services(request)
    is_intact, seq, reason = audit.verify_chain_integrity(org_id)
    return {
        "org_id": org_id,
        "is_intact": is_intact,
        "broken_sequence": seq,
        "reason": reason,
    }


@router.post("/cost/usage")
def record_cost_usage(payload: RecordCostRequest, request: Request) -> dict[str, Any]:
    _, _, _, _, _, cost_mgr, _ = _get_services(request)
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
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cost/summary")
def get_cost_summary(
    caller_user_id: str, org_id: str, request: Request, department_id: str | None = None
) -> dict[str, Any]:
    _, _, _, _, _, cost_mgr, _ = _get_services(request)
    try:
        return cost_mgr.get_cost_summary(
            caller_user_id=caller_user_id,
            org_id=org_id,
            department_id=department_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/cost/budgets")
def set_department_budget(payload: SetBudgetRequest, request: Request) -> dict[str, Any]:
    _, _, _, _, _, cost_mgr, _ = _get_services(request)
    try:
        budget = cost_mgr.set_department_budget(
            caller_user_id=payload.caller_user_id,
            org_id=payload.org_id,
            department_id=payload.department_id,
            allocated_usd=payload.allocated_usd,
            alert_threshold_pct=payload.alert_threshold_pct,
            hard_cap_enabled=payload.hard_cap_enabled,
        )
        return budget.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analytics")
def get_operational_metrics(
    caller_user_id: str, org_id: str, request: Request, department_id: str | None = None
) -> dict[str, Any]:
    _, _, _, _, _, _, analytics = _get_services(request)
    try:
        return analytics.get_operational_metrics(
            caller_user_id=caller_user_id,
            org_id=org_id,
            department_id=department_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
