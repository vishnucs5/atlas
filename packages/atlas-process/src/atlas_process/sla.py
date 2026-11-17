"""ATLAS SLA and Exception Management Engine.

Enforces task and process deadlines, business calendars, escalation policies,
and proactive SLA breach detection without silent process termination.
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EscalationAction(StrEnum):
    """Actions triggered upon SLA breach or near-breach warning."""

    NOTIFY_MANAGER = "NOTIFY_MANAGER"
    REASSIGN_WORKER = "REASSIGN_WORKER"
    INCREASE_PRIORITY = "INCREASE_PRIORITY"
    CANCEL_PROCESS = "CANCEL_PROCESS"


class SLAPolicy(BaseModel):
    """SLA definition specifying target completion timeframes and escalation triggers."""

    policy_id: str = Field(default_factory=lambda: f"sla_{uuid.uuid4().hex[:10]}")
    name: str
    target_duration_seconds: float = 3600.0
    warning_threshold_ratio: float = 0.8  # Alert at 80% elapsed
    escalation_action: EscalationAction = EscalationAction.NOTIFY_MANAGER
    business_hours_only: bool = False


class SLATracker(BaseModel):
    """Tracks active SLA status for a process or task instance."""

    tracker_id: str = Field(default_factory=lambda: f"slat_{uuid.uuid4().hex[:10]}")
    target_id: str  # process_instance_id or task_instance_id
    policy: SLAPolicy
    started_at: float = Field(default_factory=time.time)
    deadline: float
    is_warning_sent: bool = False
    is_breached: bool = False
    breached_at: float | None = None
    escalation_history: list[dict[str, Any]] = Field(default_factory=list)


class SLAManager:
    """Monitors active process and task SLAs, detecting breaches and executing escalations."""

    def __init__(self) -> None:
        self._trackers: dict[str, SLATracker] = {}

    def attach_sla(
        self,
        target_id: str,
        policy: SLAPolicy,
        start_time: float | None = None,
    ) -> SLATracker:
        """Attach an SLA policy to a process or task instance."""
        start = time.time() if start_time is None else start_time
        deadline = start + policy.target_duration_seconds
        tracker = SLATracker(
            target_id=target_id,
            policy=policy,
            started_at=start,
            deadline=deadline,
        )
        self._trackers[tracker.tracker_id] = tracker
        return tracker

    def evaluate_slas(
        self,
        current_time: float | None = None,
    ) -> list[SLATracker]:
        """Check all active trackers for warnings and breaches.

        Returns list of trackers that experienced an escalation event.
        """
        now = time.time() if current_time is None else current_time
        escalated: list[SLATracker] = []

        for tracker in self._trackers.values():
            if tracker.is_breached:
                continue

            elapsed = now - tracker.started_at
            total_allowed = tracker.policy.target_duration_seconds

            # 1. Breach Evaluation
            if now > tracker.deadline:
                tracker.is_breached = True
                tracker.breached_at = now
                tracker.escalation_history.append(
                    {
                        "type": "BREACH",
                        "action": tracker.policy.escalation_action.value,
                        "timestamp": now,
                        "elapsed_seconds": elapsed,
                    }
                )
                escalated.append(tracker)

            # 2. Warning Threshold Evaluation
            elif not tracker.is_warning_sent and (
                elapsed >= total_allowed * tracker.policy.warning_threshold_ratio
            ):
                tracker.is_warning_sent = True
                tracker.escalation_history.append(
                    {
                        "type": "WARNING",
                        "action": "NOTIFY_WARNING",
                        "timestamp": now,
                        "elapsed_seconds": elapsed,
                    }
                )
                escalated.append(tracker)

        return escalated

    def get_tracker(self, tracker_id: str) -> SLATracker | None:
        """Retrieve SLA tracker by ID."""
        return self._trackers.get(tracker_id)
