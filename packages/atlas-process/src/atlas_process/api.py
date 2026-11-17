"""ATLAS Process Execution FastAPI Endpoints.

Provides REST endpoints for process definition management, instance execution,
human approval tasks, operational analytics, and simulation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from atlas_process.analytics import ProcessAnalyticsEngine
from atlas_process.approvals import ApprovalDecision, HumanApprovalEngine
from atlas_process.definitions import (
    ProcessDefinition,
    ProcessDefinitionValidator,
)
from atlas_process.engine import ProcessExecutionEngine
from atlas_process.simulation import ProcessSimulationEngine

router = APIRouter(prefix="/api/v1/processes", tags=["processes"])

# Global singleton dependencies for the API layer
_engine = ProcessExecutionEngine()
_validator = ProcessDefinitionValidator()
_approval_engine = HumanApprovalEngine()
_analytics_engine = ProcessAnalyticsEngine()
_simulation_engine = ProcessSimulationEngine()


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
def create_definition(definition: ProcessDefinition) -> dict[str, Any]:
    """Register and validate a new process definition."""
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
def start_process_instance(req: StartProcessRequest) -> dict[str, Any]:
    """Instantiate and start a process."""
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
def get_process_instance(instance_id: str) -> dict[str, Any]:
    """Retrieve details and task status for a process instance."""
    inst = _engine.get_instance(instance_id)
    if not inst:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Process instance not found",
        )
    return inst.model_dump()


@router.post("/approvals/{approval_id}/decide")
def submit_approval_decision(approval_id: str, req: DecisionRequest) -> dict[str, Any]:
    """Submit a decision for a human approval task."""
    try:
        updated = _approval_engine.decide(
            approval_id=approval_id,
            approver_id=req.approver_id,
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
def get_tenant_analytics(tenant_id: str) -> dict[str, Any]:
    """Retrieve process analytics summary for a tenant."""
    summary = _analytics_engine.compute_summary(tenant_id)
    return summary.model_dump()
