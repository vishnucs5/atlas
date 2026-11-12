"""Executable demonstration of ATLAS Phase 3 Autonomous Planning & Agent Loop.

Demonstrates the 11-step autonomous execution cycle:
1. Initialize local SQLite event store, browser driver, and Action Firewall.
2. Formulate task and initial session context.
3. Observe live web environment and summarize interactive elements into context.
4. Model decision making via capability-aware ModelRouter and adapter.
5. Validate proposed tool calls against typed schema contracts.
6. Action Firewall pre-execution security check (fails closed on unauthorized operations).
7. Execute authorized action via low-level Playwright driver.
8. Deterministically verify post-conditions.
9. Record immutable append-only execution events to SQLite store.
10. Accumulate token usage and estimated USD costs in CostTracker.
11. Complete task through VERIFYING state to COMPLETED state and clean shutdown.

Usage:
    uv run python scripts/demo_autonomous_agent.py
"""

# ruff: noqa: E402
import asyncio
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

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
    "apps/cli/src",
    ".",
]:
    full_path = str(REPO_ROOT / pkg_path)
    if full_path not in sys.path:
        sys.path.insert(0, full_path)

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


class DemoAgentModelAdapter(ModelAdapter):
    """Deterministic model adapter demonstrating autonomous tool calling across multi-turn workflows."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._turn = 0

    @property
    def name(self) -> str:
        return "demo:autonomous-planner"

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            model_name="autonomous-planner",
            provider="demo",
            vision=True,
            tool_calling=True,
            context_window=128000,
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self._turn += 1

        if self._turn == 1:
            return ModelResponse(
                response_id=f"resp_{self._turn}",
                request_id=request.request_id,
                model_name="autonomous-planner",
                tool_calls=[
                    ToolCall(
                        id="call_nav",
                        name="browser_navigate",
                        arguments={"url": f"{self._base_url}/login"},
                    )
                ],
                usage=TokenUsage(
                    prompt_tokens=120,
                    completion_tokens=25,
                    total_tokens=145,
                    estimated_cost_usd=0.0005,
                ),
            )
        elif self._turn == 2:
            return ModelResponse(
                response_id=f"resp_{self._turn}",
                request_id=request.request_id,
                model_name="autonomous-planner",
                tool_calls=[
                    ToolCall(
                        id="call_user",
                        name="browser_type",
                        arguments={"selector": "#username", "text": "agent_alpha"},
                    )
                ],
                usage=TokenUsage(
                    prompt_tokens=180,
                    completion_tokens=25,
                    total_tokens=205,
                    estimated_cost_usd=0.0007,
                ),
            )
        elif self._turn == 3:
            return ModelResponse(
                response_id=f"resp_{self._turn}",
                request_id=request.request_id,
                model_name="autonomous-planner",
                tool_calls=[
                    ToolCall(
                        id="call_pass",
                        name="browser_type",
                        arguments={"selector": "#password", "text": "super_secret_456"},
                    )
                ],
                usage=TokenUsage(
                    prompt_tokens=210,
                    completion_tokens=25,
                    total_tokens=235,
                    estimated_cost_usd=0.0008,
                ),
            )
        elif self._turn == 4:
            return ModelResponse(
                response_id=f"resp_{self._turn}",
                request_id=request.request_id,
                model_name="autonomous-planner",
                tool_calls=[
                    ToolCall(
                        id="call_click",
                        name="browser_click",
                        arguments={"selector": "#submit-btn"},
                    )
                ],
                usage=TokenUsage(
                    prompt_tokens=240,
                    completion_tokens=20,
                    total_tokens=260,
                    estimated_cost_usd=0.0009,
                ),
            )
        else:
            return ModelResponse(
                response_id=f"resp_{self._turn}",
                request_id=request.request_id,
                model_name="autonomous-planner",
                content="Authentication successfully completed. The portal welcome page is verified active.",
                usage=TokenUsage(
                    prompt_tokens=260,
                    completion_tokens=30,
                    total_tokens=290,
                    estimated_cost_usd=0.0010,
                ),
            )

    def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        async def _gen():
            yield "Demo streaming completed."

        return _gen()

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(status="HEALTHY", provider_id="demo")


async def main() -> int:
    print("\n" + "=" * 76)
    print("  ATLAS Phase 3 — Autonomous Planning & Agent Loop Demonstration")
    print("=" * 76)

    # 1. Start Hermetic Synthetic Server
    server = SyntheticServer()
    base_url = server.start()
    print(f"[*] Synthetic web server started at: {base_url}")

    # Set up local demo workspace and database
    demo_dir = Path(".atlas/demo_agent").resolve()
    demo_dir.mkdir(parents=True, exist_ok=True)
    db_file = demo_dir / "atlas_agent_demo.db"
    if db_file.exists():
        db_file.unlink()

    storage = SQLiteStorage(str(db_file))
    storage.initialize()
    print(f"[*] SQLite event store initialized at: {db_file}")

    # 2. Initialize Model Adapter, Router, and Cost Tracker
    adapter = DemoAgentModelAdapter(base_url)
    router = ModelRouter()
    router.register_adapter(adapter, priority=100)
    print(f"[*] ModelRouter registered adapter: {adapter.name} (capabilities: vision, tools)")

    # 3. Initialize Browser Driver, Firewall, Verification, and Safety Harness
    driver = PlaywrightBrowserDriver(
        BrowserConfig(headless=True, downloads_path=str(demo_dir / "downloads"))
    )
    await driver.connect()
    print("[*] Playwright Chromium headless driver launched.")

    firewall = ActionFirewall(allowed_domains=["127.0.0.1", "localhost"])
    verification = VerificationEngine()
    state_machine = TaskStateMachine()
    context_mgr = ContextManager()
    safety = SafetyEngine(consecutive_duplicate_threshold=3)

    loop = AutonomousAgentLoop(
        model_router=router,
        action_firewall=firewall,
        driver=driver,
        verification_engine=verification,
        event_store=storage,
        task_state_machine=state_machine,
        context_manager=context_mgr,
        safety_engine=safety,
    )
    print("[*] AutonomousAgentLoop configured with 11-step execution architecture.")

    # 4. Formulate Task & Session
    now = datetime.now(UTC)
    task_id = "task_agent_demo_001"
    task = Task(
        task_id=task_id,
        objective="Autonomously navigate to login portal, enter credentials, and verify login",
        priority=TaskPriority.HIGH,
        status=TaskStatus.READY,
        created_at=now,
        updated_at=now,
    )
    storage.save_task(task)

    session_id = "sess_agent_demo_001"
    session = Session(
        session_id=session_id,
        task_id=task_id,
        status=SessionStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    print(f"\n[Task Formulation] Task ID: {task.task_id} | Objective: {task.objective}")

    try:
        print("\n--- Starting Autonomous Agent Loop Execution ---")
        budget = PlanBudget(max_steps=10, max_tokens=10000, max_cost_usd=0.05, timeout_seconds=30)
        completed_task = await loop.run(task=task, session=session, budget=budget)

        print(f"\n[Task Finalized] Status: {completed_task.status.value}")
        assert completed_task.status == TaskStatus.COMPLETED

        # 5. Verify Post-Conditions in Live Browser
        obs = await driver.observe()
        assert "Authenticated" in (obs.dom_snapshot or "")
        print(
            f"[Verification] Live DOM verified: Welcome message visible on page ({obs.metadata.get('url')})"
        )

        # 6. Audit Event Stream Integrity in SQLite
        events = storage.get_events(task_id)
        print(f"\n--- Immutable Event Stream Audit ({len(events)} events recorded) ---")
        for evt in events:
            print(f"  Seq {evt.sequence:02d} | [{evt.event_type.value:<22}] {evt.payload}")

        # 7. Audit Cost and Token Accounting
        task_cost = router.cost_tracker.get_task_cost(task_id)
        total_cost = router.cost_tracker.get_total_cost()
        cb = router.get_circuit_breaker(adapter.name)
        cb_state = cb.state.value if cb else "CLOSED"
        print("\n--- Cost & Token Accounting ---")
        print(f"  Task Estimated Cost: ${task_cost:.5f} USD")
        print(f"  Total Session Cost:  ${total_cost:.5f} USD")
        print(f"  Circuit Breaker:     {cb_state} (0 failures)")

        print("\n" + "=" * 76)
        print("  DEMO EXECUTION SUCCESS: All 11 agent loop steps executed deterministically!")
        print("=" * 76 + "\n")
        return 0

    finally:
        await driver.disconnect()
        storage.close()
        server.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
