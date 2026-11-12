"""Human approval management routes for elevated action authorization."""

from typing import Annotated, Any

from atlas_coordination.approval_manager import ApprovalRequest, ApprovalStatus
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from atlas_api.auth import AuthenticatedUser, Role, require_role

router = APIRouter(prefix="/api/v1/approvals", tags=["Approvals"])


class DecisionPayload(BaseModel):
    """Payload provided by operator when granting or denying an approval request."""

    reason: str | None = None


def _get_runtime(request: Request):
    runtime = getattr(request.app.state, "runtime", None)
    if not runtime:
        from atlas_agent.runtime import ProductionRuntime

        storage = getattr(request.app.state, "storage", None)
        runtime = ProductionRuntime(storage=storage)
        request.app.state.runtime = runtime
    return runtime


@router.get("", response_model=list[ApprovalRequest])
async def list_approvals(
    request: Request,
    user: Annotated[
        AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.VIEWER))
    ],
    task_id: Annotated[str | None, Query()] = None,
    status_filter: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
) -> Any:
    """List pending and resolved human approval requests."""
    runtime = _get_runtime(request)
    return runtime.approval_mgr.list_requests(task_id=task_id, status=status_filter)


@router.get("/{request_id}", response_model=ApprovalRequest)
async def get_approval(
    request_id: str,
    request: Request,
    user: Annotated[
        AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.VIEWER))
    ],
) -> Any:
    """Get details for a specific approval request."""
    runtime = _get_runtime(request)
    req = runtime.approval_mgr.get_request(request_id)
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request '{request_id}' not found.",
        )
    return req


@router.post("/{request_id}/grant")
async def grant_approval(
    request_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
    payload: DecisionPayload | None = None,
    wait: Annotated[bool, Query(description="Wait for resumed execution completion")] = False,
) -> Any:
    """Grant authorization for elevated action and resume task execution."""
    runtime = _get_runtime(request)
    operator_id = f"operator_{user.role.value}"
    reason = payload.reason if payload else None
    try:
        updated_task = await runtime.grant_approval(
            request_id=request_id,
            operator_id=operator_id,
            reason=reason,
            wait_until_complete=wait,
        )
        return {"status": "granted", "request_id": request_id, "task": updated_task}
    except KeyError as k_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(k_err)) from k_err
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err)
        ) from val_err


@router.post("/{request_id}/deny")
async def deny_approval(
    request_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
    payload: DecisionPayload | None = None,
) -> Any:
    """Deny authorization for elevated action and terminate task safely."""
    runtime = _get_runtime(request)
    operator_id = f"operator_{user.role.value}"
    reason = payload.reason if payload else None
    try:
        updated_task = await runtime.deny_approval(
            request_id=request_id,
            operator_id=operator_id,
            reason=reason,
        )
        return {"status": "denied", "request_id": request_id, "task": updated_task}
    except KeyError as k_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(k_err)) from k_err
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err)
        ) from val_err
