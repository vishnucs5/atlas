"""Task artifact retrieval and inspection routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from atlas_api.auth import AuthenticatedUser, Role, require_role

router = APIRouter(prefix="/api/v1/tasks/{task_id}/artifacts", tags=["Artifacts"])


def _get_runtime(request: Request):
    runtime = getattr(request.app.state, "runtime", None)
    if not runtime:
        from atlas_agent.runtime import ProductionRuntime

        storage = getattr(request.app.state, "storage", None)
        runtime = ProductionRuntime(storage=storage)
        request.app.state.runtime = runtime
    return runtime


@router.get("")
async def list_task_artifacts(
    task_id: str,
    request: Request,
    user: Annotated[
        AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.VIEWER))
    ],
) -> list[dict[str, Any]]:
    """List all artifacts (screenshots, logs, DOM snapshots) captured for a task."""
    runtime = _get_runtime(request)
    task = await runtime.get_task(task_id)
    if task and task.metadata.get("private") and user.role != Role.ADMIN:
        if task.metadata.get("owner_id") != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not have permission to access artifacts of this private task.",
            )
    return runtime.artifact_mgr.list_artifacts(task_id)


@router.get("/{name:path}")
async def get_task_artifact(
    task_id: str,
    name: str,
    request: Request,
    user: Annotated[
        AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.VIEWER))
    ],
) -> Response:
    """Retrieve the raw binary or textual content of a named task artifact."""
    runtime = _get_runtime(request)
    task = await runtime.get_task(task_id)
    if task and task.metadata.get("private") and user.role != Role.ADMIN:
        if task.metadata.get("owner_id") != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not have permission to access artifacts of this private task.",
            )
    try:
        data, content_type = runtime.artifact_mgr.read_artifact(task_id, name)
        return Response(content=data, media_type=content_type)
    except FileNotFoundError as fnf_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact '{name}' not found for task '{task_id}'.",
        ) from fnf_err
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Security violation or invalid artifact reference: {exc}",
        ) from exc
