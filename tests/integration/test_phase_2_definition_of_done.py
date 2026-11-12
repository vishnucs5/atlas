"""Definitive acceptance verification suite for Phase 2: Browser Execution Runtime.

Directly validates the Definition of Done:
1. Create an ATLAS task.
2. Launch an isolated browser session.
3. Navigate to a local test website.
4. Observe the page and identify an element.
5. Authorize and execute a click or form action.
6. Verify the resulting page state.
7. Save screenshots, events and execution evidence.
8. Close the session cleanly.

And verifies that:
- Policy enforcement cannot be bypassed.
- Failures are detectable and recoverable.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
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


@pytest.fixture(scope="module")
def synthetic_server():
    server = SyntheticServer()
    base_url = server.start()
    yield base_url
    server.stop()


@pytest.mark.asyncio
async def test_first_browser_workflow_end_to_end(synthetic_server, tmp_path):
    """Verify the 8-step end-to-end browser workflow definition of done."""
    # -------------------------------------------------------------
    # 1. CREATE AN ATLAS TASK & PERSISTENCE
    # -------------------------------------------------------------
    db_file = tmp_path / "atlas_tasks.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    now = datetime.now(UTC)
    task_id = "task_e2e_dod_001"
    task = Task(
        task_id=task_id,
        objective="Authenticate on local test portal and submit user credentials",
        status=TaskStatus.CREATED,
        priority=TaskPriority.HIGH,
        created_at=now,
        updated_at=now,
    )
    store.save_task(task)

    sm = TaskStateMachine()
    event_seq = 1

    # Transition: CREATED -> QUEUED -> PLANNING -> READY -> RUNNING
    for target in (TaskStatus.QUEUED, TaskStatus.PLANNING, TaskStatus.READY, TaskStatus.RUNNING):
        evt = sm.transition_task(
            task=task,
            target_status=target,
            sequence=event_seq,
            correlation_id=f"corr_{event_seq}",
            reason=f"Transition to {target.value}",
        )
        store.append_event(evt)
        store.update_task_status(task.task_id, target)
        event_seq += 1

    assert task.status == TaskStatus.RUNNING

    # -------------------------------------------------------------
    # 2. LAUNCH ISOLATED BROWSER SESSION
    # -------------------------------------------------------------
    artifacts_dir = tmp_path / "artifacts" / task_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    download_dir = tmp_path / "downloads" / task_id
    download_dir.mkdir(parents=True, exist_ok=True)

    config = BrowserConfig(
        headless=True,
        allowed_domains=["127.0.0.1"],
        artifacts_dir=artifacts_dir,
        download_dir=download_dir,
    )
    firewall = ActionFirewall(allowed_domains=config.allowed_domains)
    verification = VerificationEngine()

    driver = PlaywrightBrowserDriver(
        config=config,
        firewall=firewall,
        verification_engine=verification,
    )
    await driver.connect()

    health = await driver.health_check()
    assert health.connected
    assert health.status == "ok"

    # -------------------------------------------------------------
    # 3. NAVIGATE TO LOCAL TEST WEBSITE
    # -------------------------------------------------------------
    nav_action = ComputerAction(
        action_id="act_nav_login",
        task_id=task.task_id,
        session_id=driver._driver_id,
        action_type="browser.navigate",
        parameters={"url": f"{synthetic_server}/login"},
        expected_state=ExpectedState(condition="text_present", target="User Authentication"),
        idempotency_key="nav_login_001",
    )

    nav_res = await driver.execute(nav_action)
    assert nav_res.success
    assert nav_res.evidence["verification"]["verified"]

    evt_nav = ExecutionEvent(
        event_id=f"evt_{event_seq}",
        task_id=task.task_id,
        session_id=driver._driver_id,
        sequence=event_seq,
        event_type=EventType.ACTION_COMPLETED,
        timestamp=datetime.now(UTC),
        payload={
            "action": "navigate",
            "url": f"{synthetic_server}/login",
            "result": nav_res.output,
        },
        correlation_id=f"corr_{event_seq}",
    )
    store.append_event(evt_nav)
    event_seq += 1

    # -------------------------------------------------------------
    # 4. OBSERVE THE PAGE & IDENTIFY ELEMENTS
    # -------------------------------------------------------------
    obs = await driver.observe()
    assert obs.window_title == "ATLAS Login"
    assert obs.dom_snapshot is not None
    assert "login-form" in obs.dom_snapshot
    assert obs.accessibility_tree is not None

    # Check screenshot saved to artifacts directory
    assert "screenshot_file" in obs.metadata
    initial_screenshot = Path(obs.metadata["screenshot_file"])
    assert initial_screenshot.exists()
    assert initial_screenshot.stat().st_size > 1000

    # Inspect interactive elements
    interactive_elements = obs.metadata.get("interactive_elements", [])
    assert len(interactive_elements) >= 3
    elem_ids = [e.get("id") for e in interactive_elements if "id" in e]
    assert "username" in elem_ids
    assert "password" in elem_ids
    assert "submit-btn" in elem_ids

    # -------------------------------------------------------------
    # 5. AUTHORIZE AND EXECUTE FORM ACTIONS (FILL USERNAME & PASSWORD)
    # -------------------------------------------------------------
    fill_user = ComputerAction(
        action_id="act_fill_user",
        task_id=task.task_id,
        session_id=driver._driver_id,
        action_type="browser.fill",
        target=ActionTarget(strategy="css", value="#username"),
        parameters={"value": "admin_user"},
        expected_state=ExpectedState(
            condition="value_equals", target="#username", value="admin_user"
        ),
        idempotency_key="fill_user_001",
    )
    res_user = await driver.execute(fill_user)
    assert res_user.success
    assert res_user.evidence["policy_decision"]["decision"] == "ALLOW"

    fill_pass = ComputerAction(
        action_id="act_fill_pass",
        task_id=task.task_id,
        session_id=driver._driver_id,
        action_type="browser.fill",
        target=ActionTarget(strategy="css", value="#password"),
        parameters={"value": "secure_secret_password"},
        expected_state=ExpectedState(
            condition="value_equals", target="#password", value="secure_secret_password"
        ),
        idempotency_key="fill_pass_001",
    )
    res_pass = await driver.execute(fill_pass)
    assert res_pass.success

    # Execute Click Submission
    click_submit = ComputerAction(
        action_id="act_click_submit",
        task_id=task.task_id,
        session_id=driver._driver_id,
        action_type="browser.click",
        target=ActionTarget(
            strategy="accessible_role", parameters={"role": "button", "name": "Sign In"}
        ),
        expected_state=ExpectedState(condition="text_present", target="Authenticated"),
        idempotency_key="click_submit_001",
    )
    res_submit = await driver.execute(click_submit)

    # -------------------------------------------------------------
    # 6. VERIFY RESULTING PAGE STATE
    # -------------------------------------------------------------
    assert res_submit.success
    assert res_submit.evidence["verification"]["verified"]
    assert res_submit.evidence["verification"]["condition"] == "text_present"

    # Confirm live DOM text via driver active page
    auth_status_text = await driver.active_page.inner_text("#auth-status")
    assert auth_status_text == "Authenticated"

    # -------------------------------------------------------------
    # 7. SAVE SCREENSHOTS, EVENTS, AND EXECUTION EVIDENCE
    # -------------------------------------------------------------
    obs_final = await driver.observe()
    final_screenshot = Path(obs_final.metadata["screenshot_file"])
    assert final_screenshot.exists()
    assert final_screenshot.stat().st_size > 1000

    evt_action = ExecutionEvent(
        event_id=f"evt_{event_seq}",
        task_id=task.task_id,
        session_id=driver._driver_id,
        sequence=event_seq,
        event_type=EventType.ACTION_COMPLETED,
        timestamp=datetime.now(UTC),
        payload={
            "action_id": click_submit.action_id,
            "evidence": res_submit.evidence,
            "final_screenshot": str(final_screenshot),
        },
        correlation_id=f"corr_{event_seq}",
    )
    store.append_event(evt_action)
    event_seq += 1

    # -------------------------------------------------------------
    # 8. CLOSE SESSION CLEANLY AND TRANSITION TO COMPLETED
    # -------------------------------------------------------------
    evt_verifying = sm.transition_task(
        task=task,
        target_status=TaskStatus.VERIFYING,
        sequence=event_seq,
        correlation_id=f"corr_{event_seq}",
        reason="All actions executed, completing final task verification",
    )
    store.append_event(evt_verifying)
    store.update_task_status(task.task_id, TaskStatus.VERIFYING)
    event_seq += 1

    evt_complete = sm.transition_task(
        task=task,
        target_status=TaskStatus.COMPLETED,
        sequence=event_seq,
        correlation_id=f"corr_{event_seq}",
        reason="Authentication workflow verified and completed successfully",
    )
    store.append_event(evt_complete)
    store.update_task_status(task.task_id, TaskStatus.COMPLETED)

    # Disconnect driver cleanly
    await driver.disconnect()
    health_final = await driver.health_check()
    assert not health_final.connected
    assert health_final.status == "disconnected"

    # Assert storage state
    persisted_task = store.get_task(task_id)
    assert persisted_task is not None
    assert persisted_task.status == TaskStatus.COMPLETED

    events = store.get_events(task_id)
    assert len(events) == event_seq
    assert events[-1].event_type == EventType.TASK_COMPLETED

    store.close()


@pytest.mark.asyncio
async def test_policy_enforcement_cannot_be_bypassed(synthetic_server):
    """Verify that Action Firewall cannot be bypassed via URL or forbidden commands."""
    config = BrowserConfig(
        headless=True,
        allowed_domains=["127.0.0.1"],
    )
    driver = PlaywrightBrowserDriver(config=config)
    await driver.connect()

    # 1. Attempt to navigate to unauthorized domain
    unauthorized_action = ComputerAction(
        action_id="act_unauth_domain",
        task_id="task_sec_001",
        session_id=driver._driver_id,
        action_type="browser.navigate",
        parameters={"url": "https://malicious-phishing.com/login"},
        idempotency_key="sec_unauth_001",
    )
    res_unauth = await driver.execute(unauthorized_action)
    assert not res_unauth.success
    assert "denied by policy firewall" in res_unauth.error
    assert "not in allowed domains list" in res_unauth.error
    assert res_unauth.evidence["policy_decision"]["decision"] == "DENY"

    # 2. Attempt to pass malformed URL
    malformed_action = ComputerAction(
        action_id="act_malformed_url",
        task_id="task_sec_001",
        session_id=driver._driver_id,
        action_type="browser.navigate",
        parameters={"url": "http://[invalid-ipv6-address"},
        idempotency_key="sec_malformed_001",
    )
    res_malformed = await driver.execute(malformed_action)
    assert not res_malformed.success
    assert "denied by policy firewall" in res_malformed.error
    assert res_malformed.evidence["policy_decision"]["decision"] == "DENY"

    # 3. Attempt destructive action without explicit approval
    destructive_action = ComputerAction(
        action_id="act_destructive",
        task_id="task_sec_001",
        session_id=driver._driver_id,
        action_type="terminal.execute",
        parameters={"command": "rm -rf /"},
        idempotency_key="sec_destructive_001",
    )
    res_destruct = await driver.execute(destructive_action)
    assert not res_destruct.success
    assert res_destruct.evidence["approval_required"]
    assert "requires explicit user approval" in res_destruct.error

    # 4. Attempt to navigate to explicitly blocked domain
    driver_with_block = PlaywrightBrowserDriver(
        config=BrowserConfig(
            headless=True,
            allowed_domains=["127.0.0.1", "blocked.com"],
            blocked_domains=["blocked.com"],
        )
    )
    await driver_with_block.connect()
    blocked_action = ComputerAction(
        action_id="act_blocked_domain",
        task_id="task_sec_001",
        session_id=driver_with_block._driver_id,
        action_type="browser.navigate",
        parameters={"url": "https://blocked.com"},
        idempotency_key="sec_blocked_001",
    )
    res_blocked = await driver_with_block.execute(blocked_action)
    assert not res_blocked.success
    assert res_blocked.evidence["policy_decision"]["decision"] == "DENY"
    await driver_with_block.disconnect()

    await driver.disconnect()


@pytest.mark.asyncio
async def test_failure_detection_and_recovery_flow(synthetic_server):
    """Verify that action failures trigger recovery state transitions and recover cleanly."""
    driver = PlaywrightBrowserDriver(
        BrowserConfig(headless=True, allowed_domains=["127.0.0.1"], timeout_ms=500)
    )
    await driver.connect()
    await driver.active_page.goto(f"{synthetic_server}/interactive")

    sm = TaskStateMachine()
    task = Task(
        task_id="task_recovery_demo",
        objective="Recover from missing element using fallback selector",
        status=TaskStatus.RUNNING,
        priority=TaskPriority.NORMAL,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    # 1. Attempt invalid action that fails
    faulty_action = ComputerAction(
        action_id="act_faulty_click",
        task_id=task.task_id,
        session_id=driver._driver_id,
        action_type="browser.click",
        target=ActionTarget(strategy="css", value="#non_existent_target_button"),
        idempotency_key="faulty_click_001",
    )
    result_faulty = await driver.execute(faulty_action)
    assert not result_faulty.success
    assert "not found" in result_faulty.error.lower()

    # 2. State machine detects failure and transitions to RECOVERING
    evt_recovering = sm.transition_task(
        task=task,
        target_status=TaskStatus.RECOVERING,
        reason=f"Action failed with error: {result_faulty.error}. Attempting fallback locator.",
    )
    assert task.status == TaskStatus.RECOVERING
    assert evt_recovering.event_type == EventType.RECOVERY_STARTED

    # 3. Observe environment to discover valid target
    obs = await driver.observe()
    interactive = obs.metadata.get("interactive_elements", [])
    valid_btn_id = None
    for elem in interactive:
        if elem.get("id") == "btn-primary":
            valid_btn_id = "#btn-primary"
            break
    assert valid_btn_id == "#btn-primary"

    # 4. Execute recovery action with discovered valid target
    recovery_action = ComputerAction(
        action_id="act_recovered_click",
        task_id=task.task_id,
        session_id=driver._driver_id,
        action_type="browser.click",
        target=ActionTarget(strategy="css", value=valid_btn_id),
        expected_state=ExpectedState(condition="text_present", target="Clicked Primary"),
        idempotency_key="recovery_click_001",
    )
    result_recovery = await driver.execute(recovery_action)
    assert result_recovery.success
    assert result_recovery.evidence["verification"]["verified"]

    # 5. Transition from RECOVERING back to RUNNING, then VERIFYING -> COMPLETED
    sm.transition_task(task, TaskStatus.RUNNING, reason="Recovery action succeeded")
    assert task.status == TaskStatus.RUNNING

    sm.transition_task(task, TaskStatus.VERIFYING, reason="Verifying recovery outcome")
    sm.transition_task(
        task, TaskStatus.COMPLETED, reason="Task completed following successful recovery"
    )
    assert task.status == TaskStatus.COMPLETED

    await driver.disconnect()
