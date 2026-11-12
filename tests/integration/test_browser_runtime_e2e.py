"""End-to-end integration test demonstrating the full ATLAS browser runtime lifecycle."""

from datetime import UTC, datetime

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
async def test_atlas_browser_runtime_e2e_workflow(synthetic_server, tmp_path):
    # 1. Initialize persistent SQLite storage
    db_file = tmp_path / "atlas_e2e.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    # 2. Ingest and save new Task
    now = datetime.now(UTC)
    task_id = "task_browser_e2e_001"
    task = Task(
        task_id=task_id,
        objective="Navigate to interactive portal and trigger secondary button action",
        status=TaskStatus.CREATED,
        priority=TaskPriority.HIGH,
        created_at=now,
        updated_at=now,
    )
    store.save_task(task)

    # 3. State machine lifecycle progression
    sm = TaskStateMachine()
    event_seq = 1

    for target_status in (
        TaskStatus.QUEUED,
        TaskStatus.PLANNING,
        TaskStatus.READY,
        TaskStatus.RUNNING,
    ):
        evt = sm.transition_task(
            task=task,
            target_status=target_status,
            sequence=event_seq,
            correlation_id=f"corr_{event_seq}",
        )
        store.append_event(evt)
        store.update_task_status(task.task_id, target_status)
        event_seq += 1

    assert task.status == TaskStatus.RUNNING

    # 4. Allocate isolated browser driver
    download_dir = tmp_path / "downloads"
    config = BrowserConfig(
        headless=True,
        allowed_domains=["127.0.0.1"],
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

    # 5. Capture pre-action observation
    obs_initial = await driver.observe()
    assert obs_initial.observation_id is not None
    assert obs_initial.screenshot_ref is not None

    # 6. Execute Navigation Action
    nav_action = ComputerAction(
        action_id="act_e2e_nav",
        task_id=task.task_id,
        session_id=driver._driver_id,
        action_type="browser.navigate",
        parameters={"url": f"{synthetic_server}/interactive"},
        expected_state=ExpectedState(condition="text_present", target="Controls Test Page"),
        idempotency_key="e2e_nav",
    )

    nav_result = await driver.execute(nav_action)
    assert nav_result.success

    # Log action event
    evt_nav = ExecutionEvent(
        event_id=f"evt_{event_seq}",
        task_id=task.task_id,
        session_id=driver._driver_id,
        sequence=event_seq,
        event_type=EventType.ACTION_COMPLETED,
        timestamp=datetime.now(UTC),
        payload={"action_id": nav_action.action_id, "output": nav_result.output},
        correlation_id=f"corr_{event_seq}",
    )
    store.append_event(evt_nav)
    event_seq += 1

    # 7. Execute Button Click with Post-Condition Verification
    click_action = ComputerAction(
        action_id="act_e2e_click",
        task_id=task.task_id,
        session_id=driver._driver_id,
        action_type="browser.click",
        target=ActionTarget(
            strategy="accessible_role", parameters={"role": "button", "name": "Secondary Button"}
        ),
        expected_state=ExpectedState(condition="text_present", target="Clicked Secondary"),
        idempotency_key="e2e_click",
    )

    click_result = await driver.execute(click_action)
    assert click_result.success
    assert click_result.evidence["verification"]["verified"]

    # Log action event
    evt_click = ExecutionEvent(
        event_id=f"evt_{event_seq}",
        task_id=task.task_id,
        session_id=driver._driver_id,
        sequence=event_seq,
        event_type=EventType.ACTION_COMPLETED,
        timestamp=datetime.now(UTC),
        payload={"action_id": click_action.action_id, "evidence": click_result.evidence},
        correlation_id=f"corr_{event_seq}",
    )
    store.append_event(evt_click)
    event_seq += 1

    # 8. Complete task in state machine via VERIFYING
    evt_verifying = sm.transition_task(
        task=task,
        target_status=TaskStatus.VERIFYING,
        sequence=event_seq,
        correlation_id=f"corr_{event_seq}",
        reason="Actions executed, verifying overall task outcome",
    )
    store.append_event(evt_verifying)
    store.update_task_status(task.task_id, TaskStatus.VERIFYING)
    event_seq += 1

    evt_complete = sm.transition_task(
        task=task,
        target_status=TaskStatus.COMPLETED,
        sequence=event_seq,
        correlation_id=f"corr_{event_seq}",
        reason="Browser actions completed and verified successfully",
    )
    store.append_event(evt_complete)
    store.update_task_status(task.task_id, TaskStatus.COMPLETED)

    # 9. Verify persistence and clean teardown
    final_task = store.get_task(task_id)
    assert final_task is not None
    assert final_task.status == TaskStatus.COMPLETED

    all_events = store.get_events(task_id)
    assert len(all_events) == event_seq
    assert all_events[-1].event_type == EventType.TASK_COMPLETED

    await driver.disconnect()
    store.close()
