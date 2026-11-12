"""End-to-end integration tests for ATLAS Autonomous Planning & Agent Loop (Phase 3)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from atlas_agent.context import ContextManager
from atlas_agent.loop import AutonomousAgentLoop
from atlas_agent.planner import PlanBudget
from atlas_agent.safety import SafetyEngine
from atlas_browser.config import BrowserConfig
from atlas_browser.driver import PlaywrightBrowserDriver
from atlas_core.contracts.model import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ProviderHealth,
    TokenUsage,
    ToolCall,
)
from atlas_core.contracts.session import Session, SessionStatus
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_core.lifecycle.state_machine import TaskStateMachine
from atlas_models.adapter import ModelAdapter
from atlas_models.router import ModelRouter
from atlas_policy.firewall import ActionFirewall
from atlas_storage.sqlite import SQLiteStorage
from atlas_verification.engine import VerificationEngine

from tests.fixtures.synthetic_server import SyntheticServer


@pytest.fixture(scope="module")
def synthetic_server():
    server = SyntheticServer()
    base_url = server.start()
    yield base_url
    server.stop()


class StagedAgentModelAdapter(ModelAdapter):
    """Deterministic mock adapter delivering a sequence of planned responses for testing."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []

    @property
    def name(self) -> str:
        return "mock:staged-agent"

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            model_name="staged-agent",
            provider="mock",
            vision=True,
            tool_calling=True,
            context_window=128000,
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self._responses:
            return self._responses.pop(0)
        return ModelResponse(
            response_id="resp_fallback_done",
            request_id=request.request_id,
            model_name="staged-agent",
            content="Task workflow accomplished",
        )

    def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        async def _gen():
            yield "Done"

        return _gen()

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(status="HEALTHY", provider_id="mock")


@pytest.mark.asyncio
async def test_autonomous_agent_e2e_form_workflow(synthetic_server, tmp_path):
    """Verify autonomous agent executes complete observe-plan-act-verify loop on local web portal."""
    db_file = tmp_path / "atlas_tasks_e2e.db"
    storage = SQLiteStorage(str(db_file))
    storage.initialize()

    # 1. Staged Model Responses for 4-step workflow + final completion
    login_url = f"{synthetic_server}/login"
    r1 = ModelResponse(
        response_id="resp_step1",
        request_id="req_1",
        model_name="staged-agent",
        tool_calls=[ToolCall(id="c1", name="browser_navigate", arguments={"url": login_url})],
        usage=TokenUsage(
            prompt_tokens=150, completion_tokens=30, total_tokens=180, estimated_cost_usd=0.001
        ),
    )
    r2 = ModelResponse(
        response_id="resp_step2",
        request_id="req_2",
        model_name="staged-agent",
        tool_calls=[
            ToolCall(
                id="c2",
                name="browser_type",
                arguments={"selector": "#username", "text": "agent_smith"},
            )
        ],
        usage=TokenUsage(
            prompt_tokens=180, completion_tokens=25, total_tokens=205, estimated_cost_usd=0.001
        ),
    )
    r3 = ModelResponse(
        response_id="resp_step3",
        request_id="req_3",
        model_name="staged-agent",
        tool_calls=[
            ToolCall(
                id="c3",
                name="browser_type",
                arguments={"selector": "#password", "text": "agent_pass_123"},
            )
        ],
        usage=TokenUsage(
            prompt_tokens=210, completion_tokens=25, total_tokens=235, estimated_cost_usd=0.001
        ),
    )
    r4 = ModelResponse(
        response_id="resp_step4",
        request_id="req_4",
        model_name="staged-agent",
        tool_calls=[ToolCall(id="c4", name="browser_click", arguments={"selector": "#submit-btn"})],
        usage=TokenUsage(
            prompt_tokens=240, completion_tokens=20, total_tokens=260, estimated_cost_usd=0.001
        ),
    )
    r5 = ModelResponse(
        response_id="resp_step5",
        request_id="req_5",
        model_name="staged-agent",
        content="Login credentials entered and form submitted successfully.",
        usage=TokenUsage(
            prompt_tokens=260, completion_tokens=15, total_tokens=275, estimated_cost_usd=0.0005
        ),
    )

    model_adapter = StagedAgentModelAdapter([r1, r2, r3, r4, r5])
    router = ModelRouter()
    router.register_adapter(model_adapter, priority=10)

    # 2. Browser Driver, Firewall, Verification, and Safety Harness
    driver = PlaywrightBrowserDriver(
        BrowserConfig(headless=True, downloads_path=str(tmp_path / "downloads"))
    )
    await driver.connect()

    firewall = ActionFirewall(allowed_domains=["127.0.0.1", "localhost"])
    verification = VerificationEngine()
    state_machine = TaskStateMachine()
    context_manager = ContextManager()
    safety = SafetyEngine()

    loop = AutonomousAgentLoop(
        model_router=router,
        action_firewall=firewall,
        driver=driver,
        verification_engine=verification,
        event_store=storage,
        task_state_machine=state_machine,
        context_manager=context_manager,
        safety_engine=safety,
    )

    now = datetime.now(UTC)
    task_id = "task_autonomous_001"
    task = Task(
        task_id=task_id,
        objective="Log in to the portal with agent credentials",
        priority=TaskPriority.HIGH,
        status=TaskStatus.READY,
        created_at=now,
        updated_at=now,
    )
    storage.save_task(task)

    session_id = "session_auto_001"
    session = Session(
        session_id=session_id,
        task_id=task_id,
        status=SessionStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )

    try:
        # Run autonomous agent loop
        finished_task = await loop.run(task=task, session=session, budget=PlanBudget(max_steps=10))

        assert finished_task.status == TaskStatus.COMPLETED

        # Verify page state reflects successful login form submission
        obs = await driver.observe()
        assert obs.dom_snapshot is not None
        assert "Authenticated" in obs.dom_snapshot

        # Verify event sourcing integrity in SQLite
        events = storage.get_events(task_id)
        assert len(events) >= 8
        event_types = [e.event_type for e in events]
        assert "OBSERVATION_CAPTURED" in event_types
        assert "MODEL_REQUESTED" in event_types
        assert "MODEL_RESPONDED" in event_types
        assert "ACTION_PROPOSED" in event_types
        assert "POLICY_EVALUATED" in event_types
        assert "ACTION_COMPLETED" in event_types
        assert "TASK_COMPLETED" in event_types

        # Verify monotonic event sequence
        sequences = [e.sequence for e in events]
        assert sequences == sorted(sequences)

        # Verify cost tracker aggregated token usage
        task_cost = router.cost_tracker.get_task_cost(task_id)
        assert task_cost > 0.0

    finally:
        await driver.disconnect()
        storage.close()


@pytest.mark.asyncio
async def test_autonomous_agent_firewall_denial_and_recovery(synthetic_server, tmp_path):
    """Verify Action Firewall blocks forbidden navigation and agent loop self-corrects."""
    db_file = tmp_path / "atlas_tasks_recovery.db"
    storage = SQLiteStorage(str(db_file))
    storage.initialize()

    # Step 1: Model proposes navigating to unauthorized domain
    r1 = ModelResponse(
        response_id="r1",
        request_id="req_1",
        model_name="staged-agent",
        tool_calls=[
            ToolCall(
                id="c1", name="browser_navigate", arguments={"url": "http://evil-unauthorized.com"}
            )
        ],
    )
    # Step 2: Model receives policy denial and recovers by navigating to permitted test server
    r2 = ModelResponse(
        response_id="r2",
        request_id="req_2",
        model_name="staged-agent",
        tool_calls=[
            ToolCall(id="c2", name="browser_navigate", arguments={"url": f"{synthetic_server}/"})
        ],
    )
    # Step 3: Model completes task
    r3 = ModelResponse(
        response_id="r3",
        request_id="req_3",
        model_name="staged-agent",
        content="Recovered from policy denial and loaded permitted portal successfully.",
    )

    model_adapter = StagedAgentModelAdapter([r1, r2, r3])
    router = ModelRouter()
    router.register_adapter(model_adapter)

    driver = PlaywrightBrowserDriver(BrowserConfig(headless=True))
    await driver.connect()

    firewall = ActionFirewall(allowed_domains=["127.0.0.1", "localhost"])
    verification = VerificationEngine()
    loop = AutonomousAgentLoop(
        model_router=router,
        action_firewall=firewall,
        driver=driver,
        verification_engine=verification,
        event_store=storage,
    )

    now = datetime.now(UTC)
    task_id = "task_recovery_002"
    task = Task(
        task_id=task_id,
        objective="Test policy denial and recovery",
        status=TaskStatus.READY,
        created_at=now,
        updated_at=now,
    )
    storage.save_task(task)
    session = Session(
        session_id="sess_rec_002",
        task_id=task_id,
        status=SessionStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )

    try:
        finished_task = await loop.run(task=task, session=session, budget=PlanBudget(max_steps=5))
        assert finished_task.status == TaskStatus.COMPLETED

        # Verify forbidden domain was never loaded into browser
        obs = await driver.observe()
        assert obs.metadata.get("url") != "http://evil-unauthorized.com"
        assert "Welcome to ATLAS Test Bench" in (obs.dom_snapshot or "")

        # Verify ACTION_FAILED event was recorded for the denied action
        events = storage.get_events(task_id)
        failed_events = [e for e in events if e.event_type == "ACTION_FAILED"]
        assert len(failed_events) >= 1
        assert "Policy DENY" in str(failed_events[0].payload)

    finally:
        await driver.disconnect()
        storage.close()
