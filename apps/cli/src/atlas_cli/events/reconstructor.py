"""Reconstruct deterministic UI state from ordered ExecutionEvent streams."""

from typing import Any

from atlas_core.contracts.event import EventType, ExecutionEvent
from pydantic import BaseModel, Field


class UIState(BaseModel):
    """Normalized, live UI state reconstructed deterministically from event history."""

    task_id: str = ""
    status: str = "CREATED"
    objective: str = ""
    plan_steps: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    file_changes: list[dict[str, Any]] = Field(default_factory=list)
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    terminal_logs: list[str] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    event_count: int = 0
    last_sequence: int = -1


def reconstruct_state_from_events(events: list[ExecutionEvent]) -> UIState:
    """Project a chronological stream of ExecutionEvents into a unified UIState."""
    sorted_events = sorted(events, key=lambda e: e.sequence)
    state = UIState()

    seen_ids: set[str] = set()

    for event in sorted_events:
        if event.event_id in seen_ids:
            continue
        seen_ids.add(event.event_id)

        state.event_count += 1
        state.last_sequence = max(state.last_sequence, event.sequence)
        if not state.task_id and event.task_id:
            state.task_id = event.task_id

        # Timeline entry for every event
        timestamp_str = (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        )
        state.timeline.append(
            {
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "timestamp": timestamp_str,
                "details": event.payload.get("message") or event.payload.get("action_type") or "",
            }
        )

        # State transition projection
        etype = event.event_type
        payload = event.payload

        if etype == EventType.TASK_CREATED:
            state.status = "CREATED"
            state.objective = payload.get("objective", "")

        elif etype == EventType.TASK_QUEUED:
            state.status = "QUEUED"

        elif etype == EventType.PLAN_GENERATED:
            state.status = "PLANNING"
            steps = payload.get("plan", {}).get("steps", []) or payload.get("steps", [])
            state.plan_steps = steps

        elif etype == EventType.ACTION_PROPOSED:
            action_info = {
                "action_id": payload.get("action_id"),
                "action_type": payload.get("action_type"),
                "target": payload.get("target"),
                "status": "PROPOSED",
                "parameters": payload.get("parameters", {}),
            }
            state.actions.append(action_info)

        elif etype == EventType.APPROVAL_REQUESTED:
            state.status = "WAITING_APPROVAL"
            state.approvals.append(
                {
                    "request_id": payload.get("request_id"),
                    "action_type": payload.get("action_type"),
                    "risk_level": payload.get("risk_level", "HIGH"),
                    "reason": payload.get("reason", ""),
                    "target": payload.get("target"),
                    "status": "PENDING",
                    "parameters": payload.get("parameters", {}),
                    "scope": payload.get("scope", "workspace"),
                    "policy_version": payload.get("policy_version", "1.0"),
                }
            )

        elif etype == EventType.APPROVAL_GRANTED:
            req_id = payload.get("request_id")
            for app in state.approvals:
                if app.get("request_id") == req_id:
                    app["status"] = "GRANTED"
                    app["justification"] = payload.get("reason", "")

        elif etype == EventType.APPROVAL_DENIED:
            req_id = payload.get("request_id")
            for app in state.approvals:
                if app.get("request_id") == req_id:
                    app["status"] = "DENIED"
                    app["reason"] = payload.get("reason", "")

        elif etype == EventType.ACTION_STARTED:
            state.status = "RUNNING"
            act_id = payload.get("action_id")
            for a in state.actions:
                if a.get("action_id") == act_id:
                    a["status"] = "RUNNING"

        elif etype == EventType.ACTION_COMPLETED:
            act_id = payload.get("action_id")
            for a in state.actions:
                if a.get("action_id") == act_id:
                    a["status"] = "COMPLETED"
                    a["result"] = payload.get("result", {})

            # If action was a terminal or file operation, record into specialized views
            if payload.get("action_type", "").startswith("terminal."):
                cmd = payload.get("parameters", {}).get("command") or payload.get("result", {}).get(
                    "command"
                )
                out = payload.get("result", {}).get("stdout") or ""
                if cmd:
                    state.terminal_logs.append(f"$ {cmd}")
                if out:
                    state.terminal_logs.append(out)

            elif payload.get("action_type", "").startswith("file."):
                path = payload.get("parameters", {}).get("path") or payload.get("target")
                if path:
                    state.file_changes.append(
                        {
                            "path": str(path),
                            "change_type": payload.get("action_type", "")
                            .replace("file.", "")
                            .upper(),
                            "after_hash": payload.get("result", {}).get("after_hash"),
                        }
                    )

        elif etype == EventType.ACTION_FAILED:
            act_id = payload.get("action_id")
            for a in state.actions:
                if a.get("action_id") == act_id:
                    a["status"] = "FAILED"
                    a["error"] = payload.get("error", "")

        elif etype == EventType.VERIFICATION_COMPLETED:
            state.verification = payload

        elif etype == EventType.TASK_COMPLETED:
            state.status = "COMPLETED"

        elif etype == EventType.TASK_FAILED:
            state.status = "FAILED"

        elif etype == EventType.TASK_CANCELLED:
            state.status = "CANCELLED"

    return state
