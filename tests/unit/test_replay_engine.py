"""Unit tests for ExecutionReplayEngine: time-travel reconstruction, timelines, and divergence checking."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from atlas_coordination.checkpoint_manager import CheckpointManager
from atlas_coordination.replay import ExecutionReplayEngine
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.task import TaskStatus
from atlas_storage.sqlite import SQLiteStorage


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStorage:
    db = tmp_path / "test_replay.db"
    s = SQLiteStorage(str(db))
    s.initialize()
    return s


def test_time_travel_state_reconstruction(store: SQLiteStorage) -> None:
    task_id = "task_replay_1"
    now = datetime.now(UTC)

    # Sequence of events
    events = [
        ExecutionEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            task_id=task_id,
            sequence=1,
            event_type=EventType.TASK_CREATED,
            timestamp=now,
            payload={"objective": "Search flights"},
            correlation_id=task_id,
        ),
        ExecutionEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            task_id=task_id,
            sequence=2,
            event_type=EventType.PLAN_GENERATED,
            timestamp=now,
            payload={"plan_id": "plan_flights", "steps": 3},
            correlation_id=task_id,
        ),
        ExecutionEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            task_id=task_id,
            sequence=3,
            event_type=EventType.ACTION_STARTED,
            timestamp=now,
            payload={"action_id": "act_nav_google", "step_id": "step_1"},
            correlation_id=task_id,
        ),
        ExecutionEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            task_id=task_id,
            sequence=4,
            event_type=EventType.ACTION_COMPLETED,
            timestamp=now,
            payload={
                "action_id": "act_nav_google",
                "output": {"url": "https://google.com"},
                "token": "secret_jwt",
            },
            correlation_id=task_id,
        ),
        ExecutionEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            task_id=task_id,
            sequence=5,
            event_type=EventType.VERIFICATION_COMPLETED,
            timestamp=now,
            payload={"action_id": "act_nav_google", "verification_result": {"status": "ok"}},
            correlation_id=task_id,
        ),
        ExecutionEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            task_id=task_id,
            sequence=6,
            event_type=EventType.TASK_COMPLETED,
            timestamp=now,
            payload={"summary": "Done"},
            correlation_id=task_id,
        ),
    ]
    store.append_events(events)

    replay = ExecutionReplayEngine(event_store=store, checkpoint_store=store)

    # Reconstruct state at sequence 2 (before any action executed)
    s2 = replay.reconstruct_state_at(task_id, 2)
    assert s2["status"] == TaskStatus.PLANNING.value
    assert s2["plan_id"] == "plan_flights"
    assert len(s2["completed_actions"]) == 0

    # Reconstruct state at sequence 4 (after action completed)
    s4 = replay.reconstruct_state_at(task_id, 4)
    assert "act_nav_google" in s4["completed_actions"]
    assert s4["action_outputs"]["act_nav_google"]["url"] == "https://google.com"

    # Reconstruct final state at sequence 6
    s6 = replay.reconstruct_state_at(task_id, 6)
    assert s6["status"] == TaskStatus.COMPLETED.value
    assert "act_nav_google" in s6["verifications"]

    # Export timeline with secret masking
    timeline = replay.export_timeline(task_id)
    assert len(timeline) == 6
    assert timeline[0]["sequence"] == 1
    # Check that secrets in payload are masked
    assert timeline[3]["payload"]["token"] == "***REDACTED***"


def test_detect_divergence_against_checkpoint(store: SQLiteStorage) -> None:
    task_id = "task_diverge_1"
    now = datetime.now(UTC)

    # Events: action 1 completed
    events = [
        ExecutionEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            task_id=task_id,
            sequence=1,
            event_type=EventType.TASK_CREATED,
            timestamp=now,
            payload={"objective": "Test divergence"},
            correlation_id=task_id,
        ),
        ExecutionEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            task_id=task_id,
            sequence=2,
            event_type=EventType.ACTION_COMPLETED,
            timestamp=now,
            payload={"action_id": "act_1"},
            correlation_id=task_id,
        ),
    ]
    store.append_events(events)

    chk_mgr = CheckpointManager(store)
    # Checkpoint claims act_1 and act_2 completed (divergence!)
    chk = chk_mgr.create_checkpoint(
        task_id=task_id,
        state=TaskStatus.RUNNING,
        sequence=2,
        last_event_sequence=2,
        completed_action_ids=["act_1", "act_2"],
    )

    replay = ExecutionReplayEngine(event_store=store, checkpoint_store=store)
    divergence = replay.detect_divergence(task_id, chk.checkpoint_id)
    assert divergence is not None
    assert "completed_actions" in divergence
