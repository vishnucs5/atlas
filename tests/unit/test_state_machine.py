from datetime import UTC, datetime
from typing import Any

import pytest
from atlas_core.contracts.event import ExecutionEvent
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_core.lifecycle.exceptions import InvalidStateTransitionError, LifecycleError
from atlas_core.lifecycle.state_machine import TaskStateMachine
from atlas_core.runtime.interface import AtlasRuntime


def test_exception_hierarchy():
    """Verify InvalidStateTransitionError inherits from LifecycleError."""
    assert issubclass(InvalidStateTransitionError, LifecycleError)
    err = InvalidStateTransitionError(TaskStatus.CREATED, TaskStatus.COMPLETED)
    assert err.from_status == TaskStatus.CREATED
    assert err.to_status == TaskStatus.COMPLETED
    assert "Invalid state transition from CREATED to COMPLETED" in str(err)


def test_top_level_atlas_core_exports():
    """Verify state machine and runtime exports from atlas_core root."""
    import atlas_core

    assert hasattr(atlas_core, "TaskStateMachine")
    assert hasattr(atlas_core, "InvalidStateTransitionError")
    assert hasattr(atlas_core, "LifecycleError")
    assert hasattr(atlas_core, "AtlasRuntime")


def test_valid_lifecycle_transitions():
    """Verify standard happy-path progression through task lifecycle."""
    sm = TaskStateMachine()
    assert sm.transition(TaskStatus.CREATED, TaskStatus.QUEUED) == TaskStatus.QUEUED
    assert sm.transition(TaskStatus.QUEUED, TaskStatus.PLANNING) == TaskStatus.PLANNING
    assert sm.transition(TaskStatus.PLANNING, TaskStatus.READY) == TaskStatus.READY
    assert sm.transition(TaskStatus.READY, TaskStatus.RUNNING) == TaskStatus.RUNNING
    assert (
        sm.transition(TaskStatus.RUNNING, TaskStatus.WAITING_APPROVAL)
        == TaskStatus.WAITING_APPROVAL
    )
    assert sm.transition(TaskStatus.WAITING_APPROVAL, TaskStatus.RUNNING) == TaskStatus.RUNNING
    assert sm.transition(TaskStatus.RUNNING, TaskStatus.VERIFYING) == TaskStatus.VERIFYING
    assert sm.transition(TaskStatus.VERIFYING, TaskStatus.COMPLETED) == TaskStatus.COMPLETED


def test_invalid_lifecycle_transition_raises():
    """Verify illegal direct state transitions raise InvalidStateTransitionError."""
    sm = TaskStateMachine()
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        sm.transition(TaskStatus.CREATED, TaskStatus.COMPLETED)
    assert exc_info.value.from_status == TaskStatus.CREATED
    assert exc_info.value.to_status == TaskStatus.COMPLETED

    with pytest.raises(InvalidStateTransitionError):
        sm.transition(TaskStatus.CREATED, TaskStatus.RUNNING)

    with pytest.raises(InvalidStateTransitionError):
        sm.transition(TaskStatus.QUEUED, TaskStatus.COMPLETED)


def test_terminal_state_cannot_transition():
    """Verify terminal states (COMPLETED, FAILED, CANCELLED, EXPIRED) reject all transitions."""
    sm = TaskStateMachine()
    terminal_states = [
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.EXPIRED,
    ]

    for term_state in terminal_states:
        assert sm.is_terminal(term_state) is True
        for any_state in TaskStatus:
            with pytest.raises(InvalidStateTransitionError):
                sm.transition(term_state, any_state)


def test_non_terminal_can_transition_to_cancelled_and_expired():
    """Verify all non-terminal states can transition directly to CANCELLED or EXPIRED."""
    sm = TaskStateMachine()
    terminal_states = {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.EXPIRED,
    }
    non_terminal_states = [s for s in TaskStatus if s not in terminal_states]

    assert len(non_terminal_states) == 10

    for state in non_terminal_states:
        assert sm.is_terminal(state) is False
        assert sm.can_transition(state, TaskStatus.CANCELLED) is True
        assert sm.transition(state, TaskStatus.CANCELLED) == TaskStatus.CANCELLED
        assert sm.can_transition(state, TaskStatus.EXPIRED) is True
        assert sm.transition(state, TaskStatus.EXPIRED) == TaskStatus.EXPIRED


def test_intermediate_lifecycle_branching():
    """Verify pausing, environment waits, and recovery transitions."""
    sm = TaskStateMachine()

    # Pause and resume
    assert sm.transition(TaskStatus.RUNNING, TaskStatus.PAUSED) == TaskStatus.PAUSED
    assert sm.transition(TaskStatus.PAUSED, TaskStatus.RUNNING) == TaskStatus.RUNNING

    # Waiting for environment and resume
    assert (
        sm.transition(TaskStatus.RUNNING, TaskStatus.WAITING_FOR_ENVIRONMENT)
        == TaskStatus.WAITING_FOR_ENVIRONMENT
    )
    assert (
        sm.transition(TaskStatus.WAITING_FOR_ENVIRONMENT, TaskStatus.RUNNING) == TaskStatus.RUNNING
    )

    # Recovery branch
    assert sm.transition(TaskStatus.RUNNING, TaskStatus.RECOVERING) == TaskStatus.RECOVERING
    assert sm.transition(TaskStatus.RECOVERING, TaskStatus.RUNNING) == TaskStatus.RUNNING
    assert sm.transition(TaskStatus.RECOVERING, TaskStatus.FAILED) == TaskStatus.FAILED

    # Verifying failure
    assert sm.transition(TaskStatus.VERIFYING, TaskStatus.FAILED) == TaskStatus.FAILED

    # Running failure
    assert sm.transition(TaskStatus.RUNNING, TaskStatus.FAILED) == TaskStatus.FAILED


def test_transition_task_and_event_emission():
    """Verify transition_task mutates task and emits an ExecutionEvent to hooks (AC-05)."""
    sm = TaskStateMachine()
    emitted_events: list[ExecutionEvent] = []

    def hook(event: ExecutionEvent) -> None:
        emitted_events.append(event)

    sm.register_hook(hook)

    now = datetime.now(UTC)
    task = Task(
        task_id="task_state_001",
        objective="Run validation test",
        status=TaskStatus.CREATED,
        priority=TaskPriority.HIGH,
        created_at=now,
        updated_at=now,
    )

    event = sm.transition_task(
        task=task,
        target_status=TaskStatus.QUEUED,
        reason="Enqueued for scheduling",
        actor="orchestrator",
    )

    assert task.status == TaskStatus.QUEUED
    assert len(emitted_events) == 1
    assert emitted_events[0] is event
    assert event.task_id == "task_state_001"
    assert event.payload["from_status"] == TaskStatus.CREATED.value
    assert event.payload["to_status"] == TaskStatus.QUEUED.value
    assert event.payload["reason"] == "Enqueued for scheduling"
    assert event.payload["actor"] == "orchestrator"

    # Unregister hook
    sm.unregister_hook(hook)
    sm.transition_task(task, TaskStatus.PLANNING)
    assert task.status == TaskStatus.PLANNING
    assert len(emitted_events) == 1  # Not called again after unregister


def test_all_14_states_accounted_for():
    """Verify all 14 states defined in TaskStatus are mapped in the state machine (AC-04)."""
    sm = TaskStateMachine()
    assert len(TaskStatus) == 14
    for status in TaskStatus:
        valid_targets = sm.get_valid_transitions(status)
        assert isinstance(valid_targets, set)


def test_atlas_runtime_protocol_conformance():
    """Verify AtlasRuntime Protocol is runtime checkable."""

    class DummyRuntime:
        async def submit_task(self, request: Any) -> Task:
            raise NotImplementedError

        async def get_task(self, task_id: str) -> Task | None:
            raise NotImplementedError

        async def list_tasks(self, limit: int = 50, offset: int = 0) -> list[Task]:
            raise NotImplementedError

        async def cancel_task(self, task_id: str, reason: str | None = None) -> Task:
            raise NotImplementedError

        async def pause_task(self, task_id: str, reason: str | None = None) -> Task:
            raise NotImplementedError

        async def resume_task(self, task_id: str) -> Task:
            raise NotImplementedError

    dummy = DummyRuntime()
    assert isinstance(dummy, AtlasRuntime)

    class IncompleteRuntime:
        pass

    assert not isinstance(IncompleteRuntime(), AtlasRuntime)
