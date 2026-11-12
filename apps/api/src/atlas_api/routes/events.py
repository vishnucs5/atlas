"""Task execution event logging and real-time Server-Sent Events (SSE) streaming."""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from atlas_core.contracts.event import ExecutionEvent
from atlas_core.contracts.task import TaskStatus
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from atlas_api.auth import AuthenticatedUser, Role, require_role

router = APIRouter(prefix="/api/v1/tasks/{task_id}/events", tags=["Events"])


def _get_runtime(request: Request):
    runtime = getattr(request.app.state, "runtime", None)
    if not runtime:
        from atlas_agent.runtime import ProductionRuntime

        storage = getattr(request.app.state, "storage", None)
        runtime = ProductionRuntime(storage=storage)
        request.app.state.runtime = runtime
    return runtime


@router.get("", response_model=list[ExecutionEvent])
async def get_task_events(
    task_id: str,
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
    after_sequence: Annotated[int, Query(ge=0)] = 0,
) -> Any:
    """Retrieve historical execution events for a task."""
    runtime = _get_runtime(request)
    events = runtime.storage.get_events(task_id, since_sequence=after_sequence)
    return events


async def _event_stream_generator(
    runtime: Any,
    task_id: str,
    initial_seq: int = 0,
    poll_interval: float = 0.2,
    max_idle_polls: int = 60,
) -> AsyncGenerator[str, None]:
    """Poll for new task events and yield Server-Sent Events (SSE) formatted text."""
    last_seq = initial_seq
    idle_count = 0

    while True:
        events = runtime.storage.get_events(task_id, since_sequence=last_seq)
        if events:
            idle_count = 0
            for event in events:
                last_seq = max(last_seq, event.sequence)
                payload_json = json.dumps(event.model_dump(), default=str)
                yield f"event: {event.event_type.value}\ndata: {payload_json}\n\n"
        else:
            idle_count += 1

        # Check if task reached terminal state
        task = runtime.storage.get_task(task_id)
        if task and task.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.EXPIRED,
        ):
            # Check if any final events remaining
            final_events = runtime.storage.get_events(task_id, since_sequence=last_seq)
            for event in final_events:
                payload_json = json.dumps(event.model_dump(), default=str)
                yield f"event: {event.event_type.value}\ndata: {payload_json}\n\n"
            yield 'event: close\ndata: {"message": "Task reached terminal state"}\n\n'
            break

        if idle_count >= max_idle_polls:
            # Yield heartbeat to keep connection alive
            yield ": keepalive\n\n"
            idle_count = 0

        await asyncio.sleep(poll_interval)


@router.get("/stream")
async def stream_task_events(
    task_id: str,
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
    after_sequence: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """Stream live task execution events via Server-Sent Events (SSE)."""
    runtime = _get_runtime(request)
    task = await runtime.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Task '{task_id}' not found."
        )

    return StreamingResponse(
        _event_stream_generator(runtime, task_id, initial_seq=after_sequence),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
