"""ExecutionReplayEngine for time-travel state reconstruction, audit timelines, and divergence checking."""

from typing import Any

from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.task import TaskStatus
from atlas_storage.interfaces import CheckpointStoreProtocol, EventStoreProtocol

from atlas_coordination.checkpoint_manager import redact_secrets


class ExecutionReplayEngine:
    """Reconstructs state history, exports audit timelines, and checks divergence against checkpoints."""

    def __init__(
        self,
        event_store: EventStoreProtocol,
        checkpoint_store: CheckpointStoreProtocol | None = None,
    ) -> None:
        self.event_store = event_store
        self.checkpoint_store = checkpoint_store

    def get_events_until(self, task_id: str, sequence_number: int) -> list[ExecutionEvent]:
        """Fetch all execution events for a task up to the specified sequence number."""
        all_events = self.event_store.get_events(task_id, since_sequence=0)
        return [e for e in all_events if e.sequence <= sequence_number]

    def reconstruct_state_at(self, task_id: str, sequence_number: int) -> dict[str, Any]:
        """Deterministically fold event stream up to sequence_number into state representation."""
        events = self.get_events_until(task_id, sequence_number)

        state: dict[str, Any] = {
            "task_id": task_id,
            "replayed_sequence": sequence_number,
            "status": TaskStatus.CREATED.value,
            "objective": "",
            "plan_id": None,
            "current_step": None,
            "completed_actions": [],
            "action_outputs": {},
            "verifications": {},
            "environment_snapshots": {},
            "checkpoints": [],
        }

        for e in events:
            payload = e.payload
            if e.event_type == EventType.TASK_CREATED:
                state["objective"] = payload.get("objective", "")
                state["status"] = TaskStatus.CREATED.value
            elif e.event_type == EventType.PLAN_GENERATED:
                state["plan_id"] = payload.get("plan_id")
                state["status"] = TaskStatus.PLANNING.value
            elif e.event_type == EventType.ACTION_STARTED:
                state["current_step"] = payload.get("step_id") or payload.get("action_id")
                state["status"] = TaskStatus.RUNNING.value
            elif e.event_type == EventType.ACTION_COMPLETED:
                act_id = payload.get("action_id")
                if act_id:
                    state["completed_actions"].append(act_id)
                    state["action_outputs"][act_id] = payload.get("output")
            elif e.event_type == EventType.VERIFICATION_COMPLETED:
                act_id = payload.get("action_id")
                if act_id:
                    state["verifications"][act_id] = payload.get("verification_result")
            elif e.event_type == EventType.OBSERVATION_CAPTURED:
                state["environment_snapshots"] = payload.get("observation", {})
            elif e.event_type == EventType.CHECKPOINT_CREATED:
                state["checkpoints"].append(payload.get("checkpoint_id"))
            elif e.event_type == EventType.TASK_COMPLETED:
                state["status"] = TaskStatus.COMPLETED.value
            elif e.event_type == EventType.TASK_FAILED:
                state["status"] = TaskStatus.FAILED.value
            elif e.event_type == EventType.TASK_PAUSED:
                state["status"] = TaskStatus.PAUSED.value
            elif e.event_type == EventType.TASK_CANCELLED:
                state["status"] = TaskStatus.CANCELLED.value

        return state

    def export_timeline(
        self,
        task_id: str,
        until_sequence: int | None = None,
    ) -> list[dict[str, Any]]:
        """Export chronologically ordered, sanitized audit timeline."""
        all_events = self.event_store.get_events(task_id, since_sequence=0)
        if until_sequence is not None:
            all_events = [e for e in all_events if e.sequence <= until_sequence]

        timeline: list[dict[str, Any]] = []
        for e in all_events:
            clean_payload = redact_secrets(e.payload)
            timeline.append(
                {
                    "sequence": e.sequence,
                    "event_id": e.event_id,
                    "event_type": e.event_type.value,
                    "timestamp": e.timestamp.isoformat(),
                    "correlation_id": e.correlation_id,
                    "payload": clean_payload,
                }
            )

        return timeline

    def detect_divergence(
        self,
        task_id: str,
        checkpoint_id: str,
    ) -> dict[str, Any] | None:
        """Compare replayed event state with recorded checkpoint snapshot to detect drift."""
        if self.checkpoint_store is None:
            return None

        chk = self.checkpoint_store.get_checkpoint(checkpoint_id)
        if chk is None:
            return {"divergence": "checkpoint_not_found", "checkpoint_id": checkpoint_id}

        replayed = self.reconstruct_state_at(task_id, chk.last_event_sequence)

        divergences: dict[str, Any] = {}
        # Check completed action count
        replayed_completed = set(replayed.get("completed_actions", []))
        chk_completed = set(chk.completed_action_ids)

        if replayed_completed != chk_completed:
            divergences["completed_actions"] = {
                "replayed": list(replayed_completed),
                "checkpoint": list(chk_completed),
            }

        return divergences if divergences else None
