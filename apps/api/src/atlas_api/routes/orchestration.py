"""Multi-Agent Orchestration REST API routes for ATLAS."""

import asyncio
import logging
import uuid
from typing import Annotated, Any

from atlas_core.contracts.agent import AgentDescriptor
from atlas_core.contracts.graph import TaskGraph
from atlas_core.contracts.memory import MemoryEntry
from atlas_core.contracts.message import AgentMessage
from atlas_orchestration.messaging import AgentMessageRouter
from atlas_orchestration.registry import AgentRegistry
from atlas_orchestration.supervisor import (
    AgentSupervisor,
    OrchestrationError,
    ReviewRejectionError,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from atlas_api.auth import AuthenticatedUser, Role, require_role

logger = logging.getLogger("atlas.api.orchestration")
router = APIRouter(prefix="/api/v1/orchestration", tags=["Multi-Agent Orchestration"])


class SubmitMultiAgentTaskPayload(BaseModel):
    """Payload to decompose and execute a multi-agent task objective."""

    task_id: str | None = None
    objective: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    max_parallel: int = 4
    enforce_review: bool = True
    required_outputs: list[str] | None = None
    execute_async: bool = False


class CancelMultiAgentTaskPayload(BaseModel):
    """Payload to cancel an active multi-agent task graph."""

    reason: str = "Cancelled by operator"


def _get_supervisor(request: Request) -> AgentSupervisor:
    """Retrieve or lazily initialize the AgentSupervisor singleton on app state."""
    supervisor = getattr(request.app.state, "orchestration_supervisor", None)
    if not supervisor:
        from atlas_core.contracts.agent import AgentCapability
        from atlas_orchestration.memory import SharedMemoryEngine
        from atlas_orchestration.recovery import MultiAgentRecoveryManager
        from atlas_orchestration.reviewer import IndependentReviewer
        from atlas_orchestration.specialist import (
            CodingSpecialist,
            DataAnalysisSpecialist,
            QASpecialist,
            ResearchSpecialist,
        )

        registry = getattr(request.app.state, "orchestration_registry", None) or AgentRegistry()
        memory = getattr(request.app.state, "orchestration_memory", None) or SharedMemoryEngine()
        msg_router = (
            getattr(request.app.state, "orchestration_router", None) or AgentMessageRouter()
        )
        reviewer = IndependentReviewer(memory)
        recovery_mgr = MultiAgentRecoveryManager(registry)

        supervisor = AgentSupervisor(
            registry=registry,
            memory=memory,
            router=msg_router,
            reviewer=reviewer,
            recovery_manager=recovery_mgr,
        )

        # Register baseline specialists
        supervisor.register_specialist(
            ResearchSpecialist(
                AgentDescriptor(
                    agent_id="agent_res_default",
                    name="Default Research Specialist",
                    role="Researcher",
                    capabilities=[AgentCapability.RESEARCH],
                ),
                memory=memory,
            )
        )
        supervisor.register_specialist(
            CodingSpecialist(
                AgentDescriptor(
                    agent_id="agent_code_default",
                    name="Default Coding Specialist",
                    role="Coder",
                    capabilities=[AgentCapability.CODE],
                ),
                memory=memory,
            )
        )
        supervisor.register_specialist(
            QASpecialist(
                AgentDescriptor(
                    agent_id="agent_qa_default",
                    name="Default QA Specialist",
                    role="QA Reviewer",
                    capabilities=[AgentCapability.QUALITY_ASSURANCE],
                ),
                memory=memory,
            )
        )
        supervisor.register_specialist(
            DataAnalysisSpecialist(
                AgentDescriptor(
                    agent_id="agent_data_default",
                    name="Default Data Specialist",
                    role="Data Analyst",
                    capabilities=[AgentCapability.DATA_ANALYSIS],
                ),
                memory=memory,
            )
        )

        request.app.state.orchestration_supervisor = supervisor
        request.app.state.orchestration_registry = registry
        request.app.state.orchestration_memory = memory
        request.app.state.orchestration_router = msg_router

    return supervisor


@router.get("/agents", response_model=list[AgentDescriptor])
async def list_agents(
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
) -> list[AgentDescriptor]:
    """List all registered agents and their current capabilities/status."""
    supervisor = _get_supervisor(request)
    return supervisor.registry.list_agents()


@router.post("/agents", response_model=AgentDescriptor, status_code=status.HTTP_201_CREATED)
async def register_agent(
    descriptor: AgentDescriptor,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
) -> AgentDescriptor:
    """Register a new autonomous specialist agent in the cluster."""
    supervisor = _get_supervisor(request)
    return supervisor.registry.register_agent(descriptor)


@router.post("/tasks", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
async def submit_multi_agent_task(
    payload: SubmitMultiAgentTaskPayload,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
) -> dict[str, Any]:
    """Decompose an objective into a DAG and orchestrate execution across specialist agents."""
    supervisor = _get_supervisor(request)
    task_id = payload.task_id or f"task_ma_{uuid.uuid4().hex[:8]}"

    # Decompose into execution DAG
    graph = supervisor.decompose_task(
        task_id=task_id,
        objective=payload.objective,
        parameters=payload.parameters,
    )

    if payload.execute_async:
        # Background fire-and-forget execution
        asyncio.create_task(
            supervisor.execute_graph(
                graph=graph,
                max_parallel=payload.max_parallel,
                enforce_review=payload.enforce_review,
                required_outputs=payload.required_outputs,
            )
        )
        return {
            "task_id": task_id,
            "graph_id": graph.graph_id,
            "status": "QUEUED",
            "message": "Task graph execution scheduled in background.",
            "graph": graph.model_dump(mode="json"),
        }

    # Synchronous execution
    try:
        completed_graph = await supervisor.execute_graph(
            graph=graph,
            max_parallel=payload.max_parallel,
            enforce_review=payload.enforce_review,
            required_outputs=payload.required_outputs,
        )
        return {
            "task_id": task_id,
            "graph_id": completed_graph.graph_id,
            "status": "COMPLETED",
            "message": "Task graph executed and verified successfully.",
            "graph": completed_graph.model_dump(mode="json"),
        }
    except ReviewRejectionError as rev_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Task deliverables rejected by Independent QA Reviewer: {rev_err}",
        ) from rev_err
    except OrchestrationError as orch_err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Multi-agent execution failure: {orch_err}",
        ) from orch_err


@router.get("/tasks", response_model=list[dict[str, Any]])
async def list_multi_agent_tasks(
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
) -> list[dict[str, Any]]:
    """List all registered multi-agent task execution graphs."""
    supervisor = _get_supervisor(request)
    with supervisor._lock:
        return [
            {
                "task_id": tid,
                "graph_id": eng.graph.graph_id,
                "is_complete": eng.graph.is_complete(),
                "has_failures": eng.graph.has_failures(),
                "node_count": len(eng.graph.nodes),
                "nodes": {nid: n.model_dump(mode="json") for nid, n in eng.graph.nodes.items()},
            }
            for tid, eng in supervisor._active_graphs.items()
        ]


@router.get("/tasks/{task_id}/graph", response_model=TaskGraph)
async def get_task_graph(
    task_id: str,
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
) -> TaskGraph:
    """Retrieve the current DAG execution graph and node statuses for a multi-agent task."""
    supervisor = _get_supervisor(request)
    graph = supervisor.get_task_graph(task_id)
    if not graph:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task graph for task '{task_id}' not found.",
        )
    return graph


@router.get("/tasks/{task_id}/messages", response_model=list[AgentMessage])
async def get_task_messages(
    task_id: str,
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
) -> list[AgentMessage]:
    """Retrieve chronological audit trail of all inter-agent messages for a task."""
    supervisor = _get_supervisor(request)
    return supervisor.router.get_task_message_history(task_id)


@router.get("/tasks/{task_id}/memory", response_model=list[MemoryEntry])
async def get_task_memory(
    task_id: str,
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
) -> list[MemoryEntry]:
    """Retrieve all shared memory artifacts and knowledge entries for a task."""
    supervisor = _get_supervisor(request)
    return supervisor.memory.list_task_memory(task_id)


@router.post("/tasks/{task_id}/cancel", response_model=dict[str, Any])
async def cancel_task(
    task_id: str,
    payload: CancelMultiAgentTaskPayload,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
) -> dict[str, Any]:
    """Cancel an active multi-agent task and propagate cancellation to active subtasks."""
    supervisor = _get_supervisor(request)
    supervisor.cancel_task(task_id=task_id, reason=payload.reason)
    return {
        "task_id": task_id,
        "status": "CANCELLED",
        "reason": payload.reason,
    }
