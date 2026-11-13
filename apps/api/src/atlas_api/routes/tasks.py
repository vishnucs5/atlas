"""Task management routes for the ATLAS REST API."""

from typing import Annotated, Any

from atlas_core.contracts.task import Task, TaskRequest
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from atlas_api.auth import AuthenticatedUser, Role, require_role

router = APIRouter(prefix="/api/v1/tasks", tags=["Tasks"])


class TaskActionPayload(BaseModel):
    """Optional payload for task lifecycle action requests."""

    reason: str | None = None


def _get_runtime(request: Request):
    runtime = getattr(request.app.state, "runtime", None)
    if not runtime:
        from atlas_agent.runtime import ProductionRuntime

        storage = getattr(request.app.state, "storage", None)
        runtime = ProductionRuntime(storage=storage)
        request.app.state.runtime = runtime
    return runtime


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
async def submit_task(
    task_request: TaskRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
    wait: Annotated[bool, Query(description="Wait for initial step completion")] = False,
) -> Any:
    """Submit a new task for autonomous execution."""
    if task_request.metadata is None:
        task_request.metadata = {}
    task_request.metadata["owner_id"] = user.user_id
    task_request.metadata["owner_role"] = user.role.value
    runtime = _get_runtime(request)
    task = await runtime.submit_task(task_request, wait_until_complete=wait)
    return task


@router.get("", response_model=list[Task])
async def list_tasks(
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Any:
    """List tasks in reverse chronological order."""
    runtime = _get_runtime(request)
    tasks = await runtime.list_tasks(limit=limit, offset=offset)
    # If user is not admin, filter out private tasks owned by other users
    if user.role != Role.ADMIN:
        return [
            t
            for t in tasks
            if not t.metadata.get("private") or t.metadata.get("owner_id") == user.user_id
        ]
    return tasks


@router.get("/{task_id}", response_model=Task)
async def get_task(
    task_id: str,
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
) -> Any:
    """Retrieve details for a specific task."""
    runtime = _get_runtime(request)
    task = await runtime.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Task '{task_id}' not found."
        )
    if task.metadata.get("private") and user.role != Role.ADMIN:
        if task.metadata.get("owner_id") != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not have permission to access this private task.",
            )
    return task


@router.post("/{task_id}/pause", response_model=Task)
async def pause_task(
    task_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
    payload: TaskActionPayload | None = None,
) -> Any:
    """Pause an active task."""
    runtime = _get_runtime(request)
    task = await runtime.get_task(task_id)
    if task and task.metadata.get("private") and user.role != Role.ADMIN:
        if task.metadata.get("owner_id") != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not have permission to modify this private task.",
            )
    reason = payload.reason if payload else None
    try:
        return await runtime.pause_task(task_id, reason=reason)
    except KeyError as k_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Task '{task_id}' not found."
        ) from k_err
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err)
        ) from val_err


@router.post("/{task_id}/resume", response_model=Task)
async def resume_task(
    task_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
    wait: Annotated[bool, Query()] = False,
) -> Any:
    """Resume a paused task."""
    runtime = _get_runtime(request)
    task = await runtime.get_task(task_id)
    if task and task.metadata.get("private") and user.role != Role.ADMIN:
        if task.metadata.get("owner_id") != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not have permission to modify this private task.",
            )
    try:
        return await runtime.resume_task(task_id, wait_until_complete=wait)
    except KeyError as k_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Task '{task_id}' not found."
        ) from k_err
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err)
        ) from val_err


@router.post("/{task_id}/cancel", response_model=Task)
async def cancel_task(
    task_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
    payload: TaskActionPayload | None = None,
) -> Any:
    """Cancel an active or pending task."""
    runtime = _get_runtime(request)
    task = await runtime.get_task(task_id)
    if task and task.metadata.get("private") and user.role != Role.ADMIN:
        if task.metadata.get("owner_id") != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not have permission to modify this private task.",
            )
    reason = payload.reason if payload else None
    try:
        return await runtime.cancel_task(task_id, reason=reason)
    except KeyError as k_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Task '{task_id}' not found."
        ) from k_err
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err)
        ) from val_err
