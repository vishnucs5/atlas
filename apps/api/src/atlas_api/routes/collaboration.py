"""Collaboration, Steering & Explainability routes for ATLAS API."""

from __future__ import annotations

from typing import Any

from atlas_collaboration.compliance import ComplianceEvidenceGenerator
from atlas_collaboration.explainability import CausalDecisionTracer
from atlas_collaboration.models import (
    ComplianceBundle,
    WorkspaceRole,
)
from atlas_collaboration.steering import SteeringController
from atlas_collaboration.workspace import CollaborativeWorkspaceHub
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1", tags=["Collaboration & Governance"])

# Singleton managers for API process
workspace_hub = CollaborativeWorkspaceHub()
decision_tracer = CausalDecisionTracer()
steering_controller = SteeringController()
compliance_generator = ComplianceEvidenceGenerator()


class CreateSessionRequest(BaseModel):
    tenant_id: str
    workspace_name: str
    owner_identity: str


class AcquireLeaseRequest(BaseModel):
    identity: str
    duration_seconds: float = 30.0


class PauseSteeringRequest(BaseModel):
    task_instance_id: str
    operator_id: str
    reason: str


class ResumeSteeringRequest(BaseModel):
    task_instance_id: str
    operator_id: str
    parent_operation_key: str
    original_parameters: dict[str, Any] = Field(default_factory=dict)
    modified_parameters: dict[str, Any]
    reason: str


class GenerateComplianceRequest(BaseModel):
    tenant_id: str
    framework: str
    records: list[dict[str, Any]]


@router.post("/workspaces/sessions", status_code=status.HTTP_201_CREATED)
def create_workspace_session(req: CreateSessionRequest) -> dict[str, Any]:
    session = workspace_hub.create_session(
        tenant_id=req.tenant_id,
        workspace_name=req.workspace_name,
        owner_identity=req.owner_identity,
    )
    return {
        "session_id": session.session_id,
        "tenant_id": session.tenant_id,
        "workspace_name": session.workspace_name,
        "status": session.status,
        "created_at": session.created_at,
    }


@router.get("/workspaces/sessions/{session_id}")
def get_workspace_session(session_id: str) -> dict[str, Any]:
    try:
        return workspace_hub.get_snapshot(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/workspaces/sessions/{session_id}/lease")
def acquire_workspace_lease(session_id: str, req: AcquireLeaseRequest) -> dict[str, Any]:
    try:
        # Auto-enroll as editor if not yet enrolled
        session = workspace_hub.get_session(session_id)
        if session and req.identity not in session.collaborators:
            workspace_hub.join_session(session_id, req.identity, role=WorkspaceRole.EDITOR)

        lease = workspace_hub.acquire_turn_lease(
            session_id, req.identity, duration_seconds=req.duration_seconds
        )
        return {
            "lease_id": lease.lease_id,
            "holder_identity": lease.holder_identity,
            "fencing_token": lease.fencing_token,
            "expires_at": lease.expires_at,
            "is_human": lease.is_human,
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/instances/{instance_id}/steering/pause")
def pause_workflow(instance_id: str, req: PauseSteeringRequest) -> dict[str, Any]:
    record = steering_controller.pause_workflow(
        process_instance_id=instance_id,
        task_instance_id=req.task_instance_id,
        operator_id=req.operator_id,
        reason=req.reason,
    )
    return record


@router.post("/instances/{instance_id}/steering/resume")
def resume_workflow(instance_id: str, req: ResumeSteeringRequest) -> dict[str, Any]:
    try:
        child_key, event = steering_controller.inject_and_resume(
            process_instance_id=instance_id,
            task_instance_id=req.task_instance_id,
            operator_id=req.operator_id,
            parent_operation_key=req.parent_operation_key,
            original_parameters=req.original_parameters,
            modified_parameters=req.modified_parameters,
            reason=req.reason,
        )
        return {
            "status": "RESUMED",
            "child_operation_key": child_key,
            "steering_id": event.steering_id,
            "timestamp": event.timestamp,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/governance/compliance/bundles", response_model=ComplianceBundle)
def generate_compliance_bundle(req: GenerateComplianceRequest) -> ComplianceBundle:
    try:
        return compliance_generator.generate_bundle(
            tenant_id=req.tenant_id,
            framework=req.framework,
            records=req.records,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
