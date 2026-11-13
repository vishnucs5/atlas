"""Comprehensive acceptance audit integration tests verifying:
1. Complete end-to-end task lifecycle (including approval denial and cancellation).
2. Worker crash recovery, lease fencing token validation, and duplicate-action prevention.
3. RBAC authorization and approval enforcement boundaries across roles.
4. Dashboard and API integration.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from atlas_agent.runtime import ProductionRuntime
from atlas_api.main import app
from atlas_browser.registry import DriverRegistry
from atlas_coordination.action_ledger import ActionLedger
from atlas_coordination.approval_manager import ApprovalStatus
from atlas_coordination.lease_manager import WorkerLeaseManager
from atlas_coordination.worker_registry import WorkerRegistryManager
from atlas_core.contracts.action import ActionResult, ComputerAction
from atlas_core.contracts.ledger import ActionExecutionStatus
from atlas_core.contracts.model import ModelRequest, ModelResponse, ToolCall
from atlas_core.contracts.observation import Observation
from atlas_core.contracts.policy import PolicyDecisionType, RiskLevel
from atlas_core.contracts.task import Task, TaskPriority, TaskRequest, TaskStatus
from atlas_core.runtime.driver import ComputerDriver, DriverHealth
from atlas_policy import ActionFirewall, PolicyRule
from atlas_storage.interfaces import StaleWorkerError
from atlas_storage.sqlite import SQLiteStorage
from fastapi.testclient import TestClient


class ScriptedAuditRouter:
    """Scripted model router that proposes an elevated action on turn 1."""

    def __init__(self) -> None:
        self.step = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.step += 1
        if self.step == 1:
            return ModelResponse(
                response_id="res_audit_1",
                request_id=request.request_id,
                model_name="scripted-audit",
                tool_calls=[
                    ToolCall(
                        id="call_elevated_audit",
                        name="desktop_launch_app",
                        arguments={"app_name": "critical_sys_tool.exe"},
                    )
                ],
            )
        return ModelResponse(
            response_id="res_audit_2",
            request_id=request.request_id,
            model_name="scripted-audit",
            content="Task finished.",
        )


class AuditStubDriver(ComputerDriver):
    def __init__(self) -> None:
        self.connected = False
        self.executed_actions: list[ComputerAction] = []

    async def connect(self, config: dict | None = None) -> dict:
        self.connected = True
        return {"status": "connected"}

    async def observe(self) -> Observation:
        return Observation(
            observation_id="obs_audit_1",
            task_id="task_audit",
            session_id="sess_audit",
            timestamp=datetime.now(UTC),
            window_title="Audit Environment",
        )

    async def execute(self, action: ComputerAction) -> ActionResult:
        self.executed_actions.append(action)
        return ActionResult(
            action_id=action.action_id,
            success=True,
            output={"executed": action.action_type},
            duration_ms=5,
        )

    async def health_check(self) -> DriverHealth:
        return DriverHealth(status="ok", driver_type="audit", connected=self.connected)

    async def disconnect(self) -> None:
        self.connected = False


@pytest.mark.asyncio
async def test_lifecycle_approval_denial_cancellation(tmp_path: Path) -> None:
    """Verify task lifecycle when an elevated action is denied: task pauses, operator denies, action never runs."""
    db_path = tmp_path / "denial_lifecycle.db"
    storage = SQLiteStorage(str(db_path))
    storage.initialize()

    firewall = ActionFirewall(
        rules=[
            PolicyRule(
                rule_id="gate_sys_tool",
                name="Gate critical tools",
                action_prefix="desktop.launch_app",
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=RiskLevel.CRITICAL,
                description="Administrative tools require operator approval",
            )
        ]
    )

    driver = AuditStubDriver()
    registry = DriverRegistry()
    registry.register("desktop", driver, is_default=True)

    runtime = ProductionRuntime(
        storage=storage,
        driver=registry,
        model_router=ScriptedAuditRouter(),  # type: ignore
        action_firewall=firewall,
        artifacts_dir=str(tmp_path / "artifacts"),
    )

    # 1. Submit task -> Transitions through CREATED -> QUEUED -> PLANNING -> READY -> RUNNING -> WAITING_APPROVAL
    paused_task = await runtime.submit_task(
        TaskRequest(
            objective="Run system maintenance tool",
            priority=TaskPriority.HIGH,
        )
    )
    assert paused_task.status == TaskStatus.WAITING_APPROVAL

    pending_approvals = runtime.approval_mgr.list_requests(
        task_id=paused_task.task_id, status=ApprovalStatus.PENDING
    )
    assert len(pending_approvals) == 1
    appr_req = pending_approvals[0]
    assert appr_req.action_type == "desktop.launch_app"
    assert appr_req.parameters["app_name"] == "critical_sys_tool.exe"

    # Crucial security assertion: Driver must NOT have executed the action
    assert len(driver.executed_actions) == 0

    # 2. Operator denies approval request
    cancelled_task = await runtime.deny_approval(
        request_id=appr_req.request_id,
        operator_id="security_officer_alice",
        reason="Action denied due to maintenance window restrictions",
    )
    assert cancelled_task.status == TaskStatus.FAILED

    # Check approval request is marked DENIED
    updated_req = runtime.approval_mgr.get_request(appr_req.request_id)
    assert updated_req is not None
    assert updated_req.status == ApprovalStatus.DENIED
    assert updated_req.operator_id == "security_officer_alice"

    # Action must STILL not be executed
    assert len(driver.executed_actions) == 0

    # Verify event store records
    events = storage.get_events(paused_task.task_id)
    event_types = [e.event_type.value for e in events]
    assert "TASK_CREATED" in event_types
    assert "TASK_QUEUED" in event_types
    assert "APPROVAL_REQUESTED" in event_types
    assert "TASK_FAILED" in event_types

    storage.close()


def test_worker_crash_fencing_and_duplicate_prevention(tmp_path: Path) -> None:
    """Verify worker crash scenario: lease fencing tokens reject stale commits and deduplicate actions."""
    db_path = tmp_path / "fencing_audit.db"
    storage = SQLiteStorage(str(db_path))
    storage.initialize()

    registry_mgr = WorkerRegistryManager(storage)
    registry_mgr.register("worker_alpha", "host_1", ["browser", "desktop"])
    registry_mgr.register("worker_beta", "host_2", ["browser", "desktop"])

    lease_mgr = WorkerLeaseManager(storage)
    ledger = ActionLedger(store=storage, lease_manager=lease_mgr)

    task_id = "task_fencing_test"

    # 1. Worker Alpha acquires lease (Generation 1)
    lease_alpha = lease_mgr.acquire_lease(task_id, "worker_alpha", ttl_seconds=30.0)
    assert lease_alpha.generation == 1

    # Worker Alpha starts and executes action
    rec_alpha = ledger.start_action(
        action_id="act_click_submit",
        task_id=task_id,
        action_type="browser.click",
        parameters={"selector": "#submit_order_btn"},
        worker_id="worker_alpha",
        lease_generation=lease_alpha.generation,
    )
    assert rec_alpha.status == ActionExecutionStatus.STARTED

    ledger.mark_succeeded(
        task_id=task_id,
        idempotency_key=rec_alpha.idempotency_key,
        attempt=1,
        output={"order_id": "ORD-9912", "status": "confirmed"},
        lease_generation=lease_alpha.generation,
        worker_id="worker_alpha",
    )

    # 2. Worker Alpha crashes (lease released/revoked and reassigned to Worker Beta -> Generation 2)
    lease_mgr.release_lease(lease_alpha.lease_id, "worker_alpha")
    lease_beta = lease_mgr.acquire_lease(task_id, "worker_beta", ttl_seconds=30.0)
    assert lease_beta.generation == 2

    # 3. Stale Worker Alpha wakes up and tries to record a new action with old Generation 1 -> Fails with StaleWorkerError
    with pytest.raises(StaleWorkerError, match="Fencing token validation failed"):
        ledger.start_action(
            action_id="act_stale_1",
            task_id=task_id,
            action_type="browser.navigate",
            parameters={"url": "https://attacker.site"},
            worker_id="worker_alpha",
            lease_generation=1,
        )

    # 4. Worker Beta resumes the task and re-attempts the submit action -> Deduplicated, returns confirmed order without re-executing
    rec_beta = ledger.start_action(
        action_id="act_click_submit",
        task_id=task_id,
        action_type="browser.click",
        parameters={"selector": "#submit_order_btn"},
        worker_id="worker_beta",
        lease_generation=lease_beta.generation,
    )
    assert rec_beta.status == ActionExecutionStatus.SUCCEEDED
    assert rec_beta.output == {"order_id": "ORD-9912", "status": "confirmed"}

    storage.close()


def test_api_auth_and_approval_rbac_boundaries() -> None:
    """Verify that worker and viewer roles cannot grant or deny approvals, while operators can."""
    storage = SQLiteStorage(":memory:")
    storage.initialize()
    app.state.storage = storage
    app.state.runtime = None

    client = TestClient(app)

    try:
        # Trigger runtime initialization
        client.get("/api/v1/tasks", headers={"Authorization": "Bearer admin-key"})
        runtime: ProductionRuntime = app.state.runtime

        # Create task in WAITING_APPROVAL state in storage
        task = Task(
            task_id="task_rbac_audit",
            objective="Run administrative maintenance",
            status=TaskStatus.WAITING_APPROVAL,
            priority=TaskPriority.NORMAL,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        runtime.storage.save_task(task)

        # Create a pending approval
        req = runtime.approval_mgr.create_request(
            task_id="task_rbac_audit",
            action_id="act_rbac_1",
            action_type="desktop.launch_app",
            parameters={"app_name": "cmd.exe"},
            reason="Command line execution",
            risk_level="HIGH",
        )
        req_id = req.request_id

        # 1. Unauthenticated request -> 401
        res_no_auth = client.post(f"/api/v1/approvals/{req_id}/grant")
        assert res_no_auth.status_code == 401

        # 2. Worker role attempts to grant approval -> 403 Forbidden
        res_worker = client.post(
            f"/api/v1/approvals/{req_id}/grant",
            headers={"Authorization": "Bearer worker-key"},
            json={"reason": "Worker self-approving"},
        )
        assert res_worker.status_code == 403

        # 3. Viewer role attempts to grant approval -> 403 Forbidden
        res_viewer = client.post(
            f"/api/v1/approvals/{req_id}/grant",
            headers={"Authorization": "Bearer viewer-key"},
            json={"reason": "Viewer approving"},
        )
        assert res_viewer.status_code == 403

        # 4. Operator role grants approval -> 200 OK
        res_operator = client.post(
            f"/api/v1/approvals/{req_id}/grant",
            headers={"Authorization": "Bearer operator-key"},
            json={"reason": "Operator verified and approved"},
        )
        assert res_operator.status_code == 200
        assert res_operator.json()["status"] == "granted"

        # 5. Verify Operator Dashboard HTML endpoint
        res_dash = client.get("/dashboard", headers={"Authorization": "Bearer viewer-key"})
        assert res_dash.status_code == 200
        assert "ATLAS Control Plane" in res_dash.text
        assert "Active Tasks" in res_dash.text
        assert "Human Approval Inbox" in res_dash.text

        # 6. Verify System Health and Status endpoints
        res_health = client.get("/health")
        assert res_health.status_code == 200
        health_data = res_health.json()
        assert health_data["status"] == "healthy"
        assert "version" in health_data

        res_status = client.get("/api/v1/status")
        assert res_status.status_code == 200
        status_data = res_status.json()
        assert status_data["status"] == "ok"
        assert "version" in status_data

    finally:
        storage.close()
        app.state.storage = None
        app.state.runtime = None
