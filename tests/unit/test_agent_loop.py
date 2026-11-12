"""Unit tests for the 11-step AutonomousAgentLoop."""

from datetime import UTC, datetime
from typing import Any

import pytest
from atlas_agent.loop import AutonomousAgentLoop
from atlas_agent.planner import PlanBudget
from atlas_core.contracts.action import ActionResult, ComputerAction, ExpectedState
from atlas_core.contracts.model import ModelRequest, ModelResponse, ToolCall
from atlas_core.contracts.observation import Observation
from atlas_core.contracts.policy import PolicyDecision, PolicyDecisionType, RiskLevel
from atlas_core.contracts.session import Session, SessionStatus
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_core.lifecycle import TaskStateMachine


class MockDriver:
    """Mock ComputerDriver for testing loop execution without launching browsers."""

    def __init__(self) -> None:
        self.executed_actions: list[ComputerAction] = []
        self.observe_count = 0

    async def observe(self, session_id: str) -> Observation:
        self.observe_count += 1
        return Observation(
            observation_id=f"obs_{self.observe_count}",
            task_id="t1",
            session_id=session_id,
            window_title="Test Page",
            metadata={"url": "https://example.com", "interactive_elements": []},
            timestamp=datetime.now(UTC),
        )

    async def execute(self, action: ComputerAction) -> ActionResult:
        self.executed_actions.append(action)
        return ActionResult(
            action_id=action.action_id,
            task_id=action.task_id,
            success=True,
            duration_ms=50,
            output="Action executed successfully",
        )


class MockFirewall:
    """Mock ActionFirewall."""

    def __init__(self, deny_actions: set[str] | None = None) -> None:
        self.deny_actions = deny_actions or set()
        self.evaluated_actions: list[ComputerAction] = []

    async def evaluate(self, action: ComputerAction) -> PolicyDecision:
        self.evaluated_actions.append(action)
        if action.action_type in self.deny_actions:
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                reason="Denied by mock firewall policy",
                risk_level=RiskLevel.CRITICAL,
            )
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="Allowed by mock policy",
            risk_level=RiskLevel.LOW,
        )


class MockRouter:
    """Mock ModelRouter returning staged tool calls or completion text."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest, fallback: bool = True) -> ModelResponse:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return ModelResponse(
            response_id="resp_done",
            request_id=request.request_id,
            model_name="mock",
            content="Task goal accomplished",
        )


class MockVerification:
    """Mock VerificationEngine."""

    async def verify(self, expected_state: ExpectedState | None, timeout_ms: int = 1000) -> bool:
        return True


class MockEventStore:
    """Mock EventStore recording execution events."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def append_event(self, event: Any) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_agent_loop_single_step_and_complete():
    """Verify AutonomousAgentLoop executes observe -> model -> firewall -> driver -> verify -> done."""
    # Staged responses: first proposes action, second signals completion
    r1 = ModelResponse(
        response_id="r1",
        request_id="req_1",
        model_name="mock",
        tool_calls=[
            ToolCall(
                id="c1",
                name="browser_navigate",
                arguments={"url": "https://example.com"},
            )
        ],
    )
    r2 = ModelResponse(
        response_id="r2",
        request_id="req_2",
        model_name="mock",
        content="Goal achieved, page loaded",
    )

    router = MockRouter([r1, r2])
    driver = MockDriver()
    firewall = MockFirewall()
    verification = MockVerification()
    event_store = MockEventStore()
    state_machine = TaskStateMachine()

    loop = AutonomousAgentLoop(
        model_router=router,
        action_firewall=firewall,
        driver=driver,
        verification_engine=verification,
        event_store=event_store,
        task_state_machine=state_machine,
    )

    now = datetime.now(UTC)
    task = Task(
        task_id="t1",
        objective="Load example.com",
        priority=TaskPriority.NORMAL,
        status=TaskStatus.READY,
        created_at=now,
        updated_at=now,
    )
    session = Session(
        session_id="s1", task_id="t1", status=SessionStatus.ACTIVE, created_at=now, updated_at=now
    )

    finished_task = await loop.run(task=task, session=session, budget=PlanBudget(max_steps=5))
    assert finished_task.status == TaskStatus.COMPLETED

    assert finished_task.status == TaskStatus.COMPLETED
    assert len(driver.executed_actions) == 1
    assert driver.executed_actions[0].action_type == "browser.navigate"
    assert driver.executed_actions[0].parameters["url"] == "https://example.com"
    assert len(firewall.evaluated_actions) == 1
    assert len(event_store.events) > 0


@pytest.mark.asyncio
async def test_agent_loop_firewall_denial_blocks_execution():
    """Verify Constitutional Rule 2: Action Firewall DENY strictly prevents driver execution."""
    r1 = ModelResponse(
        response_id="r1",
        request_id="req_1",
        model_name="mock",
        tool_calls=[
            ToolCall(
                id="c1",
                name="os_delete_all",
                arguments={"path": "/"},
            )
        ],
    )
    r2 = ModelResponse(
        response_id="r2",
        request_id="req_2",
        model_name="mock",
        content="Aborting due to policy rejection",
    )

    router = MockRouter([r1, r2])
    driver = MockDriver()
    firewall = MockFirewall(deny_actions={"os.delete_all"})
    verification = MockVerification()
    event_store = MockEventStore()
    state_machine = TaskStateMachine()

    loop = AutonomousAgentLoop(
        model_router=router,
        action_firewall=firewall,
        driver=driver,
        verification_engine=verification,
        event_store=event_store,
        task_state_machine=state_machine,
    )

    now = datetime.now(UTC)
    task = Task(
        task_id="t2",
        objective="Test policy deny",
        status=TaskStatus.READY,
        created_at=now,
        updated_at=now,
    )
    session = Session(
        session_id="s2", task_id="t2", status=SessionStatus.ACTIVE, created_at=now, updated_at=now
    )

    finished_task = await loop.run(task=task, session=session, budget=PlanBudget(max_steps=5))
    assert finished_task.status == TaskStatus.COMPLETED

    # Driver must NEVER have executed the denied action!
    assert len(driver.executed_actions) == 0
    assert len(firewall.evaluated_actions) == 1
