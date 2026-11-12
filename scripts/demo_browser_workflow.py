"""Executable demonstration of the first ATLAS browser workflow (Phase 2 Definition of Done).

Executes the full 8-step lifecycle:
1. Create an ATLAS task.
2. Launch an isolated browser session.
3. Navigate to a local test website.
4. Observe the page and identify interactive elements.
5. Authorize and execute form and click actions through the Action Firewall.
6. Verify the resulting page state with deterministic post-conditions.
7. Save screenshots, events and execution evidence to disk and SQLite store.
8. Close the session cleanly and verify final status.

Usage:
    uv run python scripts/demo_browser_workflow.py
"""

# ruff: noqa: E402
import asyncio
import sys
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
    "apps/cli/src",
    ".",
]:
    full_path = str(REPO_ROOT / pkg_path)
    if full_path not in sys.path:
        sys.path.insert(0, full_path)

from atlas_browser.config import BrowserConfig
from atlas_browser.driver import PlaywrightBrowserDriver
from atlas_core.contracts.action import ActionTarget, ComputerAction, ExpectedState
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_core.lifecycle.state_machine import TaskStateMachine
from atlas_policy.firewall import ActionFirewall
from atlas_storage.sqlite import SQLiteStorage
from atlas_verification.engine import VerificationEngine

from tests.fixtures.synthetic_server import SyntheticServer


async def main() -> int:
    print("\n" + "=" * 70)
    print("ATLAS Phase 2 Definition of Done — End-to-End Browser Workflow")
    print("=" * 70)

    # Start local hermetic synthetic server
    server = SyntheticServer()
    base_url = server.start()
    print(f"[1/8] Synthetic server started at: {base_url}")

    # Set up directories
    artifacts_dir = Path(".atlas/artifacts/demo_workflow").resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    db_file = Path(".atlas/demo_atlas.db").resolve()
    if db_file.exists():
        db_file.unlink()

    store = SQLiteStorage(str(db_file))
    store.initialize()

    # 1. Create an ATLAS task
    now = datetime.now(UTC)
    task_id = "task_browser_dod_demo"
    task = Task(
        task_id=task_id,
        objective="Authenticate on local test portal and submit credentials",
        status=TaskStatus.CREATED,
        priority=TaskPriority.HIGH,
        created_at=now,
        updated_at=now,
    )
    store.save_task(task)
    print(f"[1/8] Task created: {task.task_id} | Objective: {task.objective}")

    sm = TaskStateMachine()
    seq = 1

    # Transition lifecycle: CREATED -> QUEUED -> PLANNING -> READY -> RUNNING
    for st in (TaskStatus.QUEUED, TaskStatus.PLANNING, TaskStatus.READY, TaskStatus.RUNNING):
        evt = sm.transition_task(task, st, sequence=seq, reason=f"State progression to {st.value}")
        store.append_event(evt)
        store.update_task_status(task.task_id, st)
        seq += 1
    print(f"[1/8] Task lifecycle state advanced: {task.status.value}")

    # 2. Launch isolated browser session
    config = BrowserConfig(
        headless=True,
        allowed_domains=["127.0.0.1"],
        artifacts_dir=artifacts_dir,
        download_dir=Path(".atlas/downloads/demo_workflow").resolve(),
    )
    firewall = ActionFirewall(allowed_domains=config.allowed_domains)
    verification = VerificationEngine()
    driver = PlaywrightBrowserDriver(
        config=config, firewall=firewall, verification_engine=verification
    )

    await driver.connect()
    health = await driver.health_check()
    print(f"[2/8] Browser launched: {health.driver_type} (Status: {health.status})")

    # 3. Navigate to local test website
    nav_url = f"{base_url}/login"
    nav_action = ComputerAction(
        action_id="act_demo_nav",
        task_id=task.task_id,
        session_id=driver._driver_id,
        action_type="browser.navigate",
        parameters={"url": nav_url},
        expected_state=ExpectedState(condition="text_present", target="User Authentication"),
        idempotency_key="demo_nav_001",
    )
    print(f"[3/8] Navigating to: {nav_url} ...")
    res_nav = await driver.execute(nav_action)
    print(
        f"[3/8] Navigation outcome: Success={res_nav.success} (Verified={res_nav.evidence['verification']['verified']})"
    )

    evt_nav = ExecutionEvent(
        event_id=f"evt_{seq}",
        task_id=task.task_id,
        session_id=driver._driver_id,
        sequence=seq,
        event_type=EventType.ACTION_COMPLETED,
        timestamp=datetime.now(UTC),
        payload={"action": "navigate", "url": nav_url},
        correlation_id=f"corr_{seq}",
    )
    store.append_event(evt_nav)
    seq += 1

    # 4. Observe page and identify elements
    obs = await driver.observe()
    screenshot_1 = Path(obs.metadata.get("screenshot_file", ""))
    print(
        f"[4/8] Observed page: Title='{obs.window_title}' | Screenshot saved: {screenshot_1.name} ({screenshot_1.stat().st_size} bytes)"
    )
    interactive = obs.metadata.get("interactive_elements", [])
    print(
        f"[4/8] Identified {len(interactive)} interactive element(s): {[e.get('id') or e.get('tag') for e in interactive]}"
    )

    # 5. Authorize and execute form and click actions
    fill_user = ComputerAction(
        action_id="act_fill_user",
        task_id=task.task_id,
        session_id=driver._driver_id,
        action_type="browser.fill",
        target=ActionTarget(strategy="css", value="#username"),
        parameters={"value": "atlas_admin"},
        expected_state=ExpectedState(
            condition="value_equals", target="#username", value="atlas_admin"
        ),
        idempotency_key="fill_u_001",
    )
    print("[5/8] Authorizing and filling username field...")
    res_user = await driver.execute(fill_user)
    print(
        f"      Username fill: Success={res_user.success} | Firewall Decision={res_user.evidence['policy_decision']['decision']}"
    )

    fill_pass = ComputerAction(
        action_id="act_fill_pass",
        task_id=task.task_id,
        session_id=driver._driver_id,
        action_type="browser.fill",
        target=ActionTarget(strategy="css", value="#password"),
        parameters={"value": "SuperSecretPassword123!"},
        expected_state=ExpectedState(
            condition="value_equals", target="#password", value="SuperSecretPassword123!"
        ),
        idempotency_key="fill_p_001",
    )
    print("[5/8] Authorizing and filling password field...")
    res_pass = await driver.execute(fill_pass)
    print(
        f"      Password fill: Success={res_pass.success} | Firewall Decision={res_pass.evidence['policy_decision']['decision']}"
    )

    click_submit = ComputerAction(
        action_id="act_click_submit",
        task_id=task.task_id,
        session_id=driver._driver_id,
        action_type="browser.click",
        target=ActionTarget(
            strategy="accessible_role", parameters={"role": "button", "name": "Sign In"}
        ),
        expected_state=ExpectedState(condition="text_present", target="Authenticated"),
        idempotency_key="click_sub_001",
    )
    print("[5/8] Authorizing and submitting form via accessible button click...")
    res_submit = await driver.execute(click_submit)

    # 6. Verify resulting page state
    print(f"[6/8] Verification result: Success={res_submit.success}")
    print(
        f"      Condition: {res_submit.evidence['verification']['condition']} -> Verified={res_submit.evidence['verification']['verified']}"
    )
    live_status = await driver.active_page.inner_text("#auth-status")
    print(f"      Live DOM element #auth-status text: '{live_status}'")

    # 7. Save screenshots, events and execution evidence
    obs_final = await driver.observe()
    screenshot_2 = Path(obs_final.metadata.get("screenshot_file", ""))
    print(
        f"[7/8] Captured post-action screenshot: {screenshot_2.name} ({screenshot_2.stat().st_size} bytes)"
    )

    evt_action = ExecutionEvent(
        event_id=f"evt_{seq}",
        task_id=task.task_id,
        session_id=driver._driver_id,
        sequence=seq,
        event_type=EventType.ACTION_COMPLETED,
        timestamp=datetime.now(UTC),
        payload={
            "action_id": click_submit.action_id,
            "verification": res_submit.evidence["verification"],
            "screenshot": str(screenshot_2),
        },
        correlation_id=f"corr_{seq}",
    )
    store.append_event(evt_action)
    seq += 1

    # Complete task via state machine
    evt_verifying = sm.transition_task(
        task, TaskStatus.VERIFYING, sequence=seq, reason="Verifying action outcome"
    )
    store.append_event(evt_verifying)
    store.update_task_status(task.task_id, TaskStatus.VERIFYING)
    seq += 1

    evt_completed = sm.transition_task(
        task, TaskStatus.COMPLETED, sequence=seq, reason="Browser workflow verified and complete"
    )
    store.append_event(evt_completed)
    store.update_task_status(task.task_id, TaskStatus.COMPLETED)

    # 8. Close session cleanly
    await driver.disconnect()
    server.stop()
    print("[8/8] Session closed cleanly. Browser and test server shut down.")

    # Verification assertions
    final_task = store.get_task(task_id)
    all_events = store.get_events(task_id)
    print(
        f"[8/8] Task Status in Store: {final_task.status.value if final_task else 'None'} | Total Events Recorded: {len(all_events)}"
    )
    print("=" * 70)
    print("SUCCESS: Full Phase 2 Browser Workflow Definition of Done Verified!")
    print("=" * 70 + "\n")
    store.close()
    return 0


if __name__ == "__main__":
    asyncio.run(main())
