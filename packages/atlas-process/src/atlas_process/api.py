"""ATLAS Process Execution FastAPI Endpoints.

Provides authenticated and tenant-authorized REST endpoints for process definition management,
instance execution, human approval tasks, operational analytics, and simulation.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from atlas_process.analytics import ProcessAnalyticsEngine
from atlas_process.approvals import ApprovalDecision, HumanApprovalEngine
from atlas_process.auth import (
    ProcessCallerIdentity,
    get_current_identity,
    verify_tenant_access,
)
from atlas_process.definitions import (
    ProcessDefinition,
    ProcessDefinitionValidator,
)
from atlas_process.engine import ProcessExecutionEngine
from atlas_process.simulation import ProcessSimulationEngine

router = APIRouter(prefix="/api/v1/processes", tags=["processes"])

CurrentIdentity = Annotated[ProcessCallerIdentity, Depends(get_current_identity)]

# Global singleton dependencies for the API layer
_engine = ProcessExecutionEngine()
_validator = ProcessDefinitionValidator()
_approval_engine = HumanApprovalEngine()
_analytics_engine = ProcessAnalyticsEngine()
_simulation_engine = ProcessSimulationEngine()


def get_engine() -> ProcessExecutionEngine:
    return _engine


def set_api_engine(engine: ProcessExecutionEngine) -> None:
    global _engine
    _engine = engine


def get_approval_engine() -> HumanApprovalEngine:
    return _approval_engine


def set_api_approval_engine(approval_engine: HumanApprovalEngine) -> None:
    global _approval_engine
    _approval_engine = approval_engine


def get_analytics_engine() -> ProcessAnalyticsEngine:
    return _analytics_engine


def set_api_analytics_engine(analytics_engine: ProcessAnalyticsEngine) -> None:
    global _analytics_engine
    _analytics_engine = analytics_engine


class StartProcessRequest(BaseModel):
    definition_id: str
    tenant_id: str
    variables: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class DecisionRequest(BaseModel):
    approver_id: str
    decision: ApprovalDecision
    comments: str = ""
    parameters: dict[str, Any] | None = None


@router.post("/definitions", status_code=status.HTTP_201_CREATED)
def create_definition(
    definition: ProcessDefinition,
    caller: CurrentIdentity,
) -> dict[str, Any]:
    """Register and validate a new process definition under caller's tenant."""
    if definition.tenant_id and definition.tenant_id != "tenant_default":
        verify_tenant_access(caller, definition.tenant_id)
    else:
        definition.tenant_id = caller.tenant_id

    errors = _validator.validate(definition)
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=errors)
    _engine.register_definition(definition)
    return {
        "definition_id": definition.definition_id,
        "version": definition.version,
        "status": definition.status.value,
        "hash": definition.definition_hash,
    }


@router.post("/instances", status_code=status.HTTP_201_CREATED)
def start_process_instance(
    req: StartProcessRequest,
    caller: CurrentIdentity,
) -> dict[str, Any]:
    """Instantiate and start a process within the caller's authorized tenant."""
    if req.tenant_id:
        verify_tenant_access(caller, req.tenant_id)
    else:
        req.tenant_id = caller.tenant_id

    try:
        inst = _engine.start_process(
            definition_id=req.definition_id,
            tenant_id=req.tenant_id,
            initial_variables=req.variables,
            idempotency_key=req.idempotency_key,
        )
        return {
            "instance_id": inst.instance_id,
            "status": inst.status.value,
            "created_at": inst.created_at,
        }
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/instances/{instance_id}")
def get_process_instance(
    instance_id: str,
    caller: CurrentIdentity,
) -> dict[str, Any]:
    """Retrieve details and task status for a process instance, enforcing tenant isolation."""
    inst = _engine.get_instance(instance_id)
    if not inst:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Process instance not found",
        )
    verify_tenant_access(caller, inst.tenant_id)
    return inst.model_dump()


@router.post("/approvals/{approval_id}/decide")
def submit_approval_decision(
    approval_id: str,
    req: DecisionRequest,
    caller: CurrentIdentity,
) -> dict[str, Any]:
    """Submit a decision for a human approval task, preventing user impersonation."""
    approval = _approval_engine.get_approval(approval_id)
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request '{approval_id}' not found.",
        )

    verify_tenant_access(caller, approval.tenant_id)

    # Disallow user impersonation: non-admins cannot submit decisions on behalf of others
    if req.approver_id and req.approver_id != caller.caller_id and not caller.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Authenticated user '{caller.caller_id}' cannot decide on behalf of '{req.approver_id}'.",
        )

    # Use authenticated caller ID if not specified
    approver_id = req.approver_id or caller.caller_id

    try:
        updated = _approval_engine.decide(
            approval_id=approval_id,
            approver_id=approver_id,
            decision=req.decision,
            comments=req.comments,
            current_parameters=req.parameters,
        )
        return {
            "approval_id": updated.approval_id,
            "status": updated.status.value,
        }
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/analytics/{tenant_id}")
def get_tenant_analytics(
    tenant_id: str,
    caller: CurrentIdentity,
) -> dict[str, Any]:
    """Retrieve process analytics summary for a tenant with tenant boundary enforcement."""
    verify_tenant_access(caller, tenant_id)
    summary = _analytics_engine.compute_summary(tenant_id)
    return summary.model_dump()
