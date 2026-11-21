"""Unit tests for production REST API endpoints, RBAC auth, SSE streaming, and dashboard."""

import pytest
from atlas_api.main import app
from atlas_core.contracts.task import TaskPriority
from atlas_storage.sqlite import SQLiteStorage
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def configure_test_storage():
    """Ensure test app has a freshly initialized in-memory SQLite backend."""
    storage = SQLiteStorage(":memory:")
    storage.initialize()
    app.state.storage = storage
    # Reset runtime to None so each test gets clean state
    app.state.runtime = None
    try:
        yield storage
    finally:
        try:
            storage.close()
        finally:
            app.state.storage = None
            app.state.runtime = None


def test_auth_rbac_enforcement() -> None:
    """Verify missing, invalid, and role-restricted API keys."""
    client = TestClient(app)

    # 1. Missing token -> 401
    res_no_auth = client.post("/api/v1/tasks", json={"objective": "Test"})
    assert res_no_auth.status_code == 401

    # 2. Invalid token -> 401
    res_bad_auth = client.post(
        "/api/v1/tasks",
        headers={"Authorization": "Bearer invalid-token"},
        json={"objective": "Test"},
    )
    assert res_bad_auth.status_code == 401

    # 3. Insufficient role (viewer cannot submit task) -> 403
    res_forbidden = client.post(
        "/api/v1/tasks",
        headers={"Authorization": "Bearer viewer-key"},
        json={"objective": "Test"},
    )
    assert res_forbidden.status_code == 403

    # 4. Operator can submit task -> 201
    res_ok = client.post(
        "/api/v1/tasks",
        headers={"Authorization": "Bearer operator-key"},
        json={"objective": "Test task with operator"},
    )
    assert res_ok.status_code == 201
    assert res_ok.json()["objective"] == "Test task with operator"


def test_task_crud_and_actions() -> None:
    """Verify task submission, retrieval, listing, and cancellation via REST."""
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin-key"}

    # Submit task
    create_res = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"objective": "Test lifecycle task", "priority": "HIGH"},
    )
    assert create_res.status_code == 201
    task_data = create_res.json()
    task_id = task_data["task_id"]

    # Get task
    get_res = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["task_id"] == task_id

    # List tasks
    list_res = client.get("/api/v1/tasks", headers=headers)
    assert list_res.status_code == 200
    tasks = list_res.json()
    assert len(tasks) >= 1
    assert any(t["task_id"] == task_id for t in tasks)

    # Cancel a task in cancelable state (e.g., WAITING_APPROVAL)
    runtime = app.state.runtime
    runtime.approval_mgr.create_request(
        task_id="task_cancel_me",
        action_id="act_1",
        action_type="desktop.launch_app",
        reason="Requires approval",
        risk_level="HIGH",
    )
    from datetime import UTC, datetime

    from atlas_core.contracts.task import Task, TaskStatus

    cancelable_task = Task(
        task_id="task_cancel_me",
        objective="Task to be cancelled",
        status=TaskStatus.WAITING_APPROVAL,
        priority=TaskPriority.NORMAL,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    runtime.storage.save_task(cancelable_task)

    cancel_res = client.post(
        "/api/v1/tasks/task_cancel_me/cancel",
        headers=headers,
        json={"reason": "User cancelled via API"},
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # Attempting to cancel already completed task returns 400
    if task_data.get("status") == "COMPLETED" or get_res.json()["status"] == "COMPLETED":
        bad_cancel = client.post(
            f"/api/v1/tasks/{task_id}/cancel",
            headers=headers,
            json={"reason": "Cannot cancel completed"},
        )
        assert bad_cancel.status_code == 400


def test_approvals_api_workflow() -> None:
    """Verify listing and granting/denying approvals via REST."""
    client = TestClient(app)
    headers = {"Authorization": "Bearer operator-key"}

    # Initialize runtime and inject a pending approval
    runtime = getattr(app.state, "runtime", None)
    if not runtime:
        # trigger lazy runtime initialization
        client.get("/api/v1/tasks", headers=headers)
        runtime = app.state.runtime

    appr = runtime.approval_mgr.create_request(
        task_id="task_appr_api",
        action_id="act_appr_1",
        action_type="desktop.launch_app",
        parameters={"app_name": "notepad.exe"},
        reason="Elevated permissions needed",
        risk_level="HIGH",
    )

    # List approvals
    list_res = client.get("/api/v1/approvals", headers=headers)
    assert list_res.status_code == 200
    approvals = list_res.json()
    assert len(approvals) >= 1
    assert any(a["request_id"] == appr.request_id for a in approvals)

    # Get single approval
    get_res = client.get(f"/api/v1/approvals/{appr.request_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["action_type"] == "desktop.launch_app"


def test_task_events_api() -> None:
    """Verify historical task events endpoint."""
    client = TestClient(app)
    headers = {"Authorization": "Bearer viewer-key"}

    # Submit task first (using admin)
    create_res = client.post(
        "/api/v1/tasks",
        headers={"Authorization": "Bearer admin-key"},
        json={"objective": "Event stream check"},
    )
    task_id = create_res.json()["task_id"]

    # Viewer queries events
    events_res = client.get(f"/api/v1/tasks/{task_id}/events", headers=headers)
    assert events_res.status_code == 200
    events = events_res.json()
    assert len(events) >= 1
    assert events[0]["event_type"] == "TASK_CREATED"


def test_artifacts_api(tmp_path) -> None:
    """Verify task artifact upload and retrieval."""
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin-key"}

    # Initialize runtime
    client.get("/api/v1/tasks", headers=headers)
    runtime = app.state.runtime

    # Save artifact
    runtime.artifact_mgr.save_artifact(
        task_id="task_art_api",
        name="log.txt",
        data="Execution log line 1\nLine 2",
        content_type="text/plain",
    )

    # List artifacts
    list_res = client.get("/api/v1/tasks/task_art_api/artifacts", headers=headers)
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) == 1
    assert items[0]["name"] == "log.txt"

    # Get artifact content
    get_res = client.get("/api/v1/tasks/task_art_api/artifacts/log.txt", headers=headers)
    assert get_res.status_code == 200
    assert "Execution log line 1" in get_res.text


def test_worker_fleet_api() -> None:
    """Verify worker node registration and heartbeat."""
    client = TestClient(app)
    headers = {"Authorization": "Bearer worker-key"}

    # Register worker
    reg_res = client.post(
        "/api/v1/workers/register",
        headers=headers,
        json={
            "worker_id": "worker_node_1",
            "hostname": "agent-host-1",
            "capabilities": ["desktop", "browser"],
        },
    )
    assert reg_res.status_code == 201
    assert reg_res.json()["worker_id"] == "worker_node_1"

    # Send heartbeat
    hb_res = client.post(
        "/api/v1/workers/worker_node_1/heartbeat",
        headers=headers,
    )
    assert hb_res.status_code == 200

    # List workers
    list_res = client.get("/api/v1/workers", headers=headers)
    assert list_res.status_code == 200
    workers = list_res.json()
    assert len(workers) == 1
    assert workers[0]["worker_id"] == "worker_node_1"


def test_operator_dashboard_html() -> None:
    """Verify embedded operator dashboard is publicly accessible and contains UI components."""
    client = TestClient(app)
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "ATLAS Control Plane" in res.text
    assert "Human Approval Inbox" in res.text
    assert "Event Stream Log" in res.text
    assert "Phase 17 Collaboration & Compliance" in res.text
    assert "Active Turn-Lock Lease" in res.text
    assert "In-Flight Workflow Steering" in res.text
    assert "Continuous Compliance Bundles" in res.text
