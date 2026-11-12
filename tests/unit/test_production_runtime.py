"""Unit tests for ProductionRuntime end-to-end lifecycle and orchestration."""

from datetime import UTC, datetime

import pytest
from atlas_agent.runtime import ProductionRuntime
from atlas_browser.desktop import DesktopDriver
from atlas_browser.registry import DriverRegistry
from atlas_core.contracts.action import ActionResult, ComputerAction
from atlas_core.contracts.model import ModelRequest, ModelResponse, ToolCall
from atlas_core.contracts.observation import Observation
from atlas_core.contracts.policy import PolicyDecisionType, RiskLevel
from atlas_core.contracts.task import TaskPriority, TaskRequest, TaskStatus
from atlas_core.runtime.driver import ComputerDriver, DriverHealth
from atlas_policy.firewall import ActionFirewall, PolicyRule


class ScriptedModelRouter:
    """Mock router that serves a scripted sequence of responses."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return ModelResponse(
            response_id="res_done",
            request_id=request.request_id,
            model_name="scripted",
            content="Task completed successfully.",
        )


class StubBrowserDriver(ComputerDriver):
    """Stub browser driver for testing multi-driver orchestration."""

    def __init__(self) -> None:
        self.connected = False
        self.executed: list[ComputerAction] = []

    async def connect(self, config: dict | None = None) -> dict:
        self.connected = True
        return {"status": "ok"}

    async def observe(self) -> Observation:
        return Observation(
            observation_id="obs_browser",
            task_id="active_task",
            session_id="browser_sess",
            timestamp=datetime.now(UTC),
            window_title="Test Browser",
        )

    async def execute(self, action: ComputerAction) -> ActionResult:
        self.executed.append(action)
        return ActionResult(
            action_id=action.action_id,
            success=True,
            output={"navigated": True},
            duration_ms=15,
        )

    async def health_check(self) -> DriverHealth:
        return DriverHealth(status="ok", driver_type="browser", connected=self.connected)

    async def disconnect(self) -> None:
        self.connected = False


@pytest.mark.asyncio
async def test_production_runtime_full_completion_lifecycle() -> None:
    """Verify standard task flows through all 14-state machine stages to COMPLETED."""
    r1 = ModelResponse(
        response_id="r1",
        request_id="req_1",
        model_name="mock",
        tool_calls=[
            ToolCall(
                id="c1",
                name="desktop_click",
                arguments={"x": 150, "y": 250},
            )
        ],
    )
    r2 = ModelResponse(
        response_id="r2",
        request_id="req_2",
        model_name="mock",
        content="Clicked icon, goal completed",
    )

    router = ScriptedModelRouter([r1, r2])
    runtime = ProductionRuntime(model_router=router)
    await runtime.initialize()

    # Submit task
    req = TaskRequest(
        objective="Click desktop shortcut icon",
        priority=TaskPriority.HIGH,
        metadata={"user": "admin"},
    )
    completed_task = await runtime.submit_task(req, wait_until_complete=True)

    # Invariants
    assert completed_task.status == TaskStatus.COMPLETED
    assert completed_task.objective == req.objective

    # Verify task in storage
    stored_task = await runtime.get_task(completed_task.task_id)
    assert stored_task is not None
    assert stored_task.status == TaskStatus.COMPLETED

    # Verify task listing
    all_tasks = await runtime.list_tasks()
    assert len(all_tasks) >= 1
    assert any(t.task_id == completed_task.task_id for t in all_tasks)

    # Verify monotonically sequenced event emission
    events = runtime.storage.get_events(completed_task.task_id)
    assert len(events) >= 5
    # Sequences must be strictly increasing
    sequences = [e.sequence for e in events]
    assert sequences == sorted(sequences)

    await runtime.shutdown()


@pytest.mark.asyncio
async def test_production_runtime_human_approval_pause_and_grant() -> None:
    """Verify elevated action pauses in WAITING_APPROVAL and completes when operator grants."""
    # Policy rule: require approval for desktop.launch_app
    firewall = ActionFirewall(
        rules=[
            PolicyRule(
                rule_id="rule_require_app",
                name="Require approval to launch apps",
                action_prefix="desktop.launch_app",
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.HIGH,
                description="Launching executables requires human sign-off",
            )
        ]
    )

    # Staged responses:
    # 1. Proposes launch_app (triggers WAITING_APPROVAL)
    # 2. Resumed after approval -> completes task
    r1 = ModelResponse(
        response_id="r1",
        request_id="req_1",
        model_name="mock",
        tool_calls=[
            ToolCall(
                id="c1",
                name="desktop_launch_app",
                arguments={"app_name": "calc.exe"},
            )
        ],
    )
    r2 = ModelResponse(
        response_id="r2",
        request_id="req_2",
        model_name="mock",
        content="App launched successfully and confirmed.",
    )

    router = ScriptedModelRouter([r1, r2])
    runtime = ProductionRuntime(
        model_router=router,
        action_firewall=firewall,
    )
    await runtime.initialize()

    # 1. Submit task
    req = TaskRequest(objective="Launch calculator")
    task = await runtime.submit_task(req, wait_until_complete=True)

    # Must be paused in WAITING_APPROVAL
    assert task.status == TaskStatus.WAITING_APPROVAL

    # Check approval request in ApprovalManager
    pending_approvals = runtime.approval_mgr.list_requests(task_id=task.task_id)
    assert len(pending_approvals) == 1
    appr_req = pending_approvals[0]
    assert appr_req.action_type == "desktop.launch_app"
    assert appr_req.parameters["app_name"] == "calc.exe"

    # 2. Operator grants approval
    resumed_task = await runtime.grant_approval(
        request_id=appr_req.request_id,
        operator_id="operator_bob",
        reason="Calculator verified safe",
        wait_until_complete=True,
    )

    # Must successfully transition to COMPLETED
    assert resumed_task.status == TaskStatus.COMPLETED

    # Verify desktop driver actually launched the app
    desktop_drv: DesktopDriver = runtime.driver.resolve_driver("desktop.launch_app")  # type: ignore
    assert "calc.exe" in desktop_drv.open_windows

    await runtime.shutdown()


@pytest.mark.asyncio
async def test_production_runtime_human_approval_denial() -> None:
    """Verify denying approval transitions task to FAILED cleanly."""
    firewall = ActionFirewall(
        rules=[
            PolicyRule(
                rule_id="rule_require_app",
                name="Require approval to launch apps",
                action_prefix="desktop.launch_app",
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.HIGH,
            )
        ]
    )

    r1 = ModelResponse(
        response_id="r1",
        request_id="req_1",
        model_name="mock",
        tool_calls=[
            ToolCall(
                id="c1",
                name="desktop_launch_app",
                arguments={"app_name": "malicious.exe"},
            )
        ],
    )

    router = ScriptedModelRouter([r1])
    runtime = ProductionRuntime(
        model_router=router,
        action_firewall=firewall,
    )
    await runtime.initialize()

    task = await runtime.submit_task(TaskRequest(objective="Launch tool"), wait_until_complete=True)
    assert task.status == TaskStatus.WAITING_APPROVAL

    pending = runtime.approval_mgr.list_requests(task_id=task.task_id)
    assert len(pending) == 1

    denied_task = await runtime.deny_approval(
        request_id=pending[0].request_id,
        operator_id="security_officer",
        reason="Suspicious binary rejected",
    )
    assert denied_task.status == TaskStatus.FAILED

    await runtime.shutdown()


@pytest.mark.asyncio
async def test_production_runtime_cancellation() -> None:
    """Verify task cancellation from non-terminal states."""
    runtime = ProductionRuntime()
    await runtime.initialize()

    # Pre-populate a task in QUEUED state
    task = await runtime.submit_task(
        TaskRequest(objective="Test cancel"), wait_until_complete=False
    )

    cancelled = await runtime.cancel_task(task.task_id, reason="User cancelled task")
    assert cancelled.status == TaskStatus.CANCELLED

    # Stored state reflects cancellation
    stored = await runtime.get_task(task.task_id)
    assert stored is not None
    assert stored.status == TaskStatus.CANCELLED

    await runtime.shutdown()


@pytest.mark.asyncio
async def test_production_runtime_multi_driver_routing() -> None:
    """Verify multi-driver registry routing through ProductionRuntime."""
    registry = DriverRegistry()
    desktop = DesktopDriver()
    browser = StubBrowserDriver()

    registry.register("desktop", desktop, is_default=True)
    registry.register("browser", browser)

    r1 = ModelResponse(
        response_id="r1",
        request_id="req_1",
        model_name="mock",
        tool_calls=[
            ToolCall(
                id="c1",
                name="browser_navigate",
                arguments={"url": "https://example.org"},
            ),
            ToolCall(
                id="c2",
                name="desktop_type",
                arguments={"text": "atlas"},
            ),
        ],
    )
    r2 = ModelResponse(
        response_id="r2",
        request_id="req_2",
        model_name="mock",
        content="Multi-driver workflow completed.",
    )

    router = ScriptedModelRouter([r1, r2])
    runtime = ProductionRuntime(
        driver=registry,
        model_router=router,
    )
    await runtime.initialize()

    task = await runtime.submit_task(
        TaskRequest(objective="Cross-driver navigation and typing"),
        wait_until_complete=True,
    )
    assert task.status == TaskStatus.COMPLETED

    # Verify browser driver was called for browser_navigate
    assert len(browser.executed) == 1
    assert browser.executed[0].action_type == "browser.navigate"

    # Verify health check
    health = await runtime.driver.health_check()
    assert health.status == "ok"

    await runtime.shutdown()
