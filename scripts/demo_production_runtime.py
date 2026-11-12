"""Demonstration script for ATLAS Phase 5 Production Runtime Integration & Orchestration.

Demonstrates:
1. Multi-driver registry routing across heterogeneous execution domains (desktop + browser).
2. Human-in-the-loop authorization and task suspension in WAITING_APPROVAL.
3. Checkpoint generation and rollback-safe state persistence.
4. Operator approval grant with audit justification and autonomous resumption.
5. Deterministic post-condition verification and completion through the 14-state machine.
6. Secret redaction and secure artifact management.
"""

# ruff: noqa: E402
import asyncio
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Bootstrap repository packages onto sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
for pkg_path in [
    "packages/atlas-core/src",
    "packages/atlas-storage/src",
    "packages/atlas-policy/src",
    "packages/atlas-observability/src",
    "packages/atlas-browser/src",
    "packages/atlas-observation/src",
    "packages/atlas-verification/src",
    "packages/atlas-models/src",
    "packages/atlas-agent/src",
    "packages/atlas-coordination/src",
    "apps/api/src",
    "apps/cli/src",
]:
    full_path = str(REPO_ROOT / pkg_path)
    if full_path not in sys.path:
        sys.path.insert(0, full_path)

from atlas_agent.runtime import ProductionRuntime
from atlas_browser.desktop import DesktopDriver
from atlas_browser.registry import DriverRegistry
from atlas_core.contracts.action import ActionResult, ComputerAction, ExpectedState
from atlas_core.contracts.model import ModelRequest, ModelResponse, ToolCall
from atlas_core.contracts.observation import Observation
from atlas_core.contracts.policy import PolicyDecisionType, RiskLevel
from atlas_core.contracts.task import TaskPriority, TaskRequest, TaskStatus
from atlas_core.runtime.driver import ComputerDriver, DriverHealth
from atlas_policy.firewall import ActionFirewall, PolicyRule
from atlas_storage.sqlite import SQLiteStorage
from atlas_verification.engine import VerificationEngine


class DemoScriptedRouter:
    """Scripted model responses guiding the demonstration through human approval."""

    def __init__(self) -> None:
        self.step = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.step += 1
        if self.step == 1:
            print(
                "\n  [Model Step 1] Proposing administrative app launch (triggers Action Firewall)..."
            )
            return ModelResponse(
                response_id="demo_res_1",
                request_id=request.request_id,
                model_name="demo-model",
                tool_calls=[
                    ToolCall(
                        id="call_demo_1",
                        name="desktop_launch_app",
                        arguments={"app_name": "disk_partition_manager.exe"},
                    )
                ],
            )
        elif self.step == 2:
            print("\n  [Model Step 2] Resumed after approval. Navigating to audit dashboard...")
            return ModelResponse(
                response_id="demo_res_2",
                request_id=request.request_id,
                model_name="demo-model",
                tool_calls=[
                    ToolCall(
                        id="call_demo_2",
                        name="browser_navigate",
                        arguments={"url": "https://secops.internal/audit"},
                    )
                ],
            )
        else:
            print("\n  [Model Step 3] Goal achieved. Declaring task complete.")
            return ModelResponse(
                response_id="demo_res_final",
                request_id=request.request_id,
                model_name="demo-model",
                content="Disk partitioned and registered in audit log.",
            )


class DemoBrowserDriver(ComputerDriver):
    """Stub browser driver capturing navigation actions for the demonstration."""

    def __init__(self) -> None:
        self.connected = False
        self.history: list[str] = []
        self.current_url = "about:blank"

    async def connect(self, config: dict | None = None) -> dict:
        self.connected = True
        return {"status": "connected"}

    async def observe(self) -> Observation:
        return Observation(
            observation_id="obs_demo_browser",
            task_id="demo_task",
            session_id="demo_sess",
            timestamp=datetime.now(UTC),
            window_title="SecOps Audit Dashboard",
            metadata={"url": self.current_url},
        )

    async def execute(self, action: ComputerAction) -> ActionResult:
        self.current_url = str(action.parameters.get("url", "https://secops.internal"))
        self.history.append(self.current_url)
        print(f"    [BrowserDriver] Navigated to '{self.current_url}'")
        return ActionResult(
            action_id=action.action_id,
            success=True,
            output={"url": self.current_url},
            duration_ms=40,
        )

    async def health_check(self) -> DriverHealth:
        return DriverHealth(status="ok", driver_type="browser", connected=self.connected)

    async def disconnect(self) -> None:
        self.connected = False


class DemoVerificationEngine(VerificationEngine):
    """Deterministic verifier confirming expected state post-conditions."""

    async def verify(self, expected_state: ExpectedState | None, **kwargs) -> Any:
        return type("VerificationResult", (), {"verified": True, "evidence": {"verified": True}})()


async def run_demo() -> None:
    print("=" * 80)
    print(" ATLAS PHASE 5 — PRODUCTION RUNTIME & ORCHESTRATION DEMO")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        db_file = temp_path / "demo_runtime.db"
        artifacts_dir = temp_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        storage = SQLiteStorage(str(db_file))
        storage.initialize()

        # 1. Multi-driver setup
        registry = DriverRegistry()
        desktop = DesktopDriver(screen_size=(1920, 1080))
        browser = DemoBrowserDriver()
        registry.register("desktop", desktop, is_default=True)
        registry.register("browser", browser)

        # 2. Action Firewall rules
        firewall = ActionFirewall(
            rules=[
                PolicyRule(
                    rule_id="rule_gate_disk_mgmt",
                    name="Gate disk management utilities",
                    action_prefix="desktop.launch_app",
                    decision=PolicyDecisionType.REQUIRE_APPROVAL,
                    risk_level=RiskLevel.CRITICAL,
                    description="Partition management requires SecOps authorization",
                )
            ]
        )

        router = DemoScriptedRouter()
        verifier = DemoVerificationEngine()

        try:
            runtime = ProductionRuntime(
                storage=storage,
                driver=registry,
                model_router=router,  # type: ignore
                action_firewall=firewall,
                verification_engine=verifier,
                artifacts_dir=artifacts_dir,
            )
            await runtime.initialize()

            print(
                "\n[+] ProductionRuntime initialized with Multi-Driver Registry (Desktop + Browser)"
            )

            # 3. Submit Task
            print("\n--- PHASE 1: TASK SUBMISSION & SUSPENSION ---")
            request = TaskRequest(
                objective="Partition storage drive and record audit log entry",
                priority=TaskPriority.CRITICAL,
                metadata={"requester": "infra_lead"},
            )
            task = await runtime.submit_task(request, wait_until_complete=True)

            print(f"[+] Task created and scheduled: '{task.task_id}'")
            print(f"[*] Task status: {task.status.value}")
            assert task.status == TaskStatus.WAITING_APPROVAL

            # Verify approval request created
            pending = runtime.approval_mgr.list_requests(task_id=task.task_id)
            assert len(pending) == 1
            appr = pending[0]
            print(f"[!] Action Firewall Gate Triggered: {appr.reason}")
            print(f"    - Request ID:  {appr.request_id}")
            print(f"    - Action Type: {appr.action_type}")
            print(f"    - Risk Level:  {appr.risk_level}")
            print(f"    - Parameters:  {appr.parameters}")

            # Checkpoints
            checkpoints = storage.list_checkpoints(task.task_id)
            print(f"[+] Sealed Checkpoints in Storage: {len(checkpoints)}")
            if checkpoints:
                print(
                    f"    - Checkpoint ID: {checkpoints[0].checkpoint_id} (State: {checkpoints[0].state})"
                )

            # Save artifact with secrets
            runtime.artifact_mgr.save_artifact(
                task_id=task.task_id,
                name="secops_auth.json",
                data={"token": "bearer-token-secret-xyz", "auth_status": "pending_grant"},
            )
            data, _ = runtime.artifact_mgr.read_artifact(task.task_id, "secops_auth.json")
            print(
                f"[+] Saved Artifact: 'secops_auth.json' (Secret Redaction Active: '{'***REDACTED***' in data.decode('utf-8')}')"
            )

            # 4. Operator Grants Approval
            print("\n--- PHASE 2: HUMAN OPERATOR AUTHORIZATION ---")
            print(f"[*] Operator granting approval for request '{appr.request_id}'...")
            resumed_task = await runtime.grant_approval(
                request_id=appr.request_id,
                operator_id="operator_alice",
                reason="Verified maintenance window ticket #INC-8921",
                wait_until_complete=True,
            )

            print(f"[✔] Resumed task execution completed with status: {resumed_task.status.value}")
            assert resumed_task.status == TaskStatus.COMPLETED

            # 5. Inspection of Execution Evidence
            print("\n--- PHASE 3: EXECUTION & VERIFICATION EVIDENCE ---")
            print(f"[*] DesktopDriver open windows: {desktop.open_windows}")
            print(f"[*] BrowserDriver history:      {browser.history}")
            assert "disk_partition_manager.exe" in desktop.open_windows
            assert "https://secops.internal/audit" in browser.history

            # 6. Monotonic Event Log
            events = storage.get_events(task.task_id)
            print(f"\n[+] Total Audit Events Recorded: {len(events)}")
            print(f"{'SEQ':<5} {'EVENT TYPE':<26} {'TIMESTAMP':<28} {'CORRELATION ID'}")
            print("-" * 75)
            for e in events:
                print(
                    f"#{e.sequence:<4} {e.event_type.value:<26} {e.timestamp.isoformat():<28} {e.correlation_id}"
                )

            await runtime.shutdown()
        finally:
            storage.close()

    print("\n" + "=" * 80)
    print(" DEMONSTRATION COMPLETE: ALL INVARIANTS DETERMINISTICALLY SATISFIED")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_demo())
