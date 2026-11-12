"""End-to-end integration tests for ATLAS Phase 5 Production Runtime."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from atlas_agent.runtime import ProductionRuntime
from atlas_browser.desktop import DesktopDriver
from atlas_browser.registry import DriverRegistry
from atlas_core.contracts.action import ActionResult, ComputerAction, ExpectedState
from atlas_core.contracts.event import EventType
from atlas_core.contracts.model import ModelRequest, ModelResponse, ToolCall
from atlas_core.contracts.observation import Observation
from atlas_core.contracts.policy import PolicyDecisionType, RiskLevel
from atlas_core.contracts.task import TaskPriority, TaskRequest, TaskStatus
from atlas_core.runtime.driver import ComputerDriver, DriverHealth
from atlas_policy.firewall import ActionFirewall, PolicyRule
from atlas_storage.sqlite import SQLiteStorage
from atlas_verification.engine import VerificationEngine


class ScriptedE2ERouter:
    """Scripted model router guiding the agent through an elevated action workflow."""

    def __init__(self) -> None:
        self.step = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.step += 1
        if self.step == 1:
            # Propose elevated action requiring approval
            return ModelResponse(
                response_id="res_step_1",
                request_id=request.request_id,
                model_name="scripted-e2e",
                tool_calls=[
                    ToolCall(
                        id="call_elevated_1",
                        name="desktop_launch_app",
                        arguments={"app_name": "database_admin.exe"},
                    )
                ],
            )
        elif self.step == 2:
            # Resumed after approval: propose browser navigation with expected state
            return ModelResponse(
                response_id="res_step_2",
                request_id=request.request_id,
                model_name="scripted-e2e",
                tool_calls=[
                    ToolCall(
                        id="call_browser_1",
                        name="browser_navigate",
                        arguments={"url": "https://internal.service/dashboard"},
                    )
                ],
            )
        else:
            # Objective accomplished
            return ModelResponse(
                response_id="res_step_final",
                request_id=request.request_id,
                model_name="scripted-e2e",
                content="System initialized, database configured, and service verified.",
            )


class E2EBrowserDriver(ComputerDriver):
    """Stub browser driver capturing navigation actions for integration verification."""

    def __init__(self) -> None:
        self.connected = False
        self.history: list[str] = []

    async def connect(self, config: dict | None = None) -> dict:
        self.connected = True
        return {"status": "connected"}

    async def observe(self) -> Observation:
        return Observation(
            observation_id="obs_e2e_browser",
            task_id="active_task",
            session_id="e2e_session",
            timestamp=datetime.now(UTC),
            window_title="Internal Dashboard",
            metadata={"url": self.history[-1] if self.history else "about:blank"},
        )

    async def execute(self, action: ComputerAction) -> ActionResult:
        url = str(action.parameters.get("url", ""))
        self.history.append(url)
        return ActionResult(
            action_id=action.action_id,
            success=True,
            output={"navigated_to": url},
            duration_ms=25,
            evidence={"final_url": url},
        )

    async def health_check(self) -> DriverHealth:
        return DriverHealth(status="ok", driver_type="browser", connected=self.connected)

    async def disconnect(self) -> None:
        self.connected = False


class E2EVerificationEngine(VerificationEngine):
    """Deterministic post-condition verifier for integration testing."""

    async def verify(self, expected_state: ExpectedState | None, **kwargs) -> Any:
        return type("VerificationResult", (), {"verified": True, "evidence": {"verified": True}})()


@pytest.mark.asyncio
async def test_full_production_runtime_e2e_workflow(tmp_path: Path) -> None:
    """End-to-end integration test exercising:
    1. Multi-driver setup (desktop + browser).
    2. Policy firewall requiring approval for high-risk action.
    3. Task submission through CREATED -> QUEUED -> PLANNING -> READY -> RUNNING.
    4. Action proposal -> ActionFirewall REQUIRE_APPROVAL -> WAITING_APPROVAL suspension.
    5. Checkpoint generated during approval suspension.
    6. Operator granting approval with audit justification.
    7. Task resumption -> Action execution on DesktopDriver -> BrowserDriver navigation.
    8. Post-condition verification -> VERIFYING -> COMPLETED.
    9. Artifact containment and secret scrubbing verification.
    10. Monotonic event sequence integrity.
    """
    db_file = tmp_path / "production_e2e.db"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True)

    storage = SQLiteStorage(str(db_file))
    storage.initialize()

    # Multi-driver registry
    registry = DriverRegistry()
    desktop = DesktopDriver(screen_size=(1920, 1080))
    browser = E2EBrowserDriver()
    registry.register("desktop", desktop, is_default=True)
    registry.register("browser", browser)

    # Policy firewall with high-risk rule
    firewall = ActionFirewall(
        rules=[
            PolicyRule(
                rule_id="rule_gate_executables",
                name="Gate administrative executable execution",
                action_prefix="desktop.launch_app",
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.HIGH,
                description="Database admin utilities require explicit operator approval",
            )
        ]
    )

    router = ScriptedE2ERouter()
    verifier = E2EVerificationEngine()

    runtime = ProductionRuntime(
        storage=storage,
        driver=registry,
        model_router=router,  # type: ignore
        action_firewall=firewall,
        verification_engine=verifier,
        artifacts_dir=artifacts_dir,
    )
    await runtime.initialize()

    # Phase 1: Submit Task
    request = TaskRequest(
        objective="Deploy database administrator and verify web service dashboard",
        priority=TaskPriority.HIGH,
        metadata={"initiator": "ci_pipeline", "target_env": "staging"},
    )
    task = await runtime.submit_task(request, wait_until_complete=True)

    # Must be suspended in WAITING_APPROVAL
    assert task.status == TaskStatus.WAITING_APPROVAL
    assert "pending_approval_action" in task.metadata

    # Verify checkpoint created at approval suspension point
    checkpoints = storage.list_checkpoints(task.task_id)
    assert len(checkpoints) >= 1

    # Verify pending approval request
    pending_approvals = runtime.approval_mgr.list_requests(task_id=task.task_id)
    assert len(pending_approvals) == 1
    appr_req = pending_approvals[0]
    assert appr_req.action_type == "desktop.launch_app"
    assert appr_req.parameters["app_name"] == "database_admin.exe"
    assert appr_req.risk_level == "HIGH"

    # Save a task execution artifact containing credentials to test redaction
    artifact_uri = runtime.artifact_mgr.save_artifact(
        task_id=task.task_id,
        name="deployment_credentials.json",
        data={"database_password": "super-secret-password-123", "status": "deployed"},
    )
    assert artifact_uri.startswith("artifacts://")

    # Read artifact back and confirm secrets were scrubbed
    art_bytes, art_ctype = runtime.artifact_mgr.read_artifact(
        task.task_id, "deployment_credentials.json"
    )
    art_content = art_bytes.decode("utf-8")
    assert "super-secret-password-123" not in art_content
    assert "***REDACTED***" in art_content

    # Phase 2: Operator Grants Approval
    resumed_task = await runtime.grant_approval(
        request_id=appr_req.request_id,
        operator_id="secops_lead",
        reason="Security assessment completed and approved for staging",
        wait_until_complete=True,
    )

    # Task must now be COMPLETED
    assert resumed_task.status == TaskStatus.COMPLETED

    # Phase 3: Verify Cross-Driver Actions Actually Executed
    # 1. Desktop driver launched the app
    assert "database_admin.exe" in desktop.open_windows

    # 2. Browser driver navigated to the target URL
    assert "https://internal.service/dashboard" in browser.history

    # Phase 4: Event Store Audit
    events = storage.get_events(task.task_id)
    event_types = [e.event_type for e in events]

    assert EventType.TASK_CREATED in event_types
    assert EventType.TASK_QUEUED in event_types
    assert EventType.PLAN_GENERATED in event_types
    assert EventType.APPROVAL_REQUESTED in event_types
    assert EventType.ACTION_STARTED in event_types
    assert EventType.ACTION_COMPLETED in event_types
    assert EventType.VERIFICATION_COMPLETED in event_types
    assert EventType.TASK_COMPLETED in event_types

    # Strict monotonicity of sequence numbers
    sequences = [e.sequence for e in events]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences)), (
        "Sequence numbers must be strictly unique and increasing"
    )

    await runtime.shutdown()
