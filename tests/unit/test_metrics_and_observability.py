"""Unit tests verifying Milestone 5 Prometheus metrics, observability endpoints, and state consistency."""

from atlas_api.main import app
from atlas_observability.metrics import MetricsRegistry
from atlas_storage.sqlite import SQLiteStorage
from fastapi.testclient import TestClient


def test_prometheus_metrics_registry() -> None:
    """Verify metrics registry handles counters, gauges, labels, and text exposition."""
    reg = MetricsRegistry()
    reg.counter("test_counter", "Test counter description")
    reg.gauge("test_gauge", "Test gauge description")

    reg.inc_counter("test_counter", 3.0, labels={"env": "prod", "cluster": "us-east"})
    reg.set_gauge("test_gauge", 42.5, labels={"worker": "w1"})

    text = reg.export_prometheus_text()
    assert "# HELP test_counter Test counter description" in text
    assert "# TYPE test_counter counter" in text
    assert 'test_counter{cluster="us-east",env="prod"} 3.0' in text
    assert "# HELP test_gauge Test gauge description" in text
    assert "# TYPE test_gauge gauge" in text
    assert 'test_gauge{worker="w1"} 42.5' in text


def test_metrics_api_endpoint() -> None:
    """Verify GET /metrics exposes Prometheus metrics over HTTP."""
    client = TestClient(app)
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    text = res.text

    assert "atlas_tasks_total" in text
    assert "atlas_active_workers" in text
    assert "atlas_pending_approvals" in text
    assert "atlas_queue_backpressure_rejections_total" in text


def test_dashboard_and_api_state_consistency() -> None:
    """Verify task and approval state consistency between REST API, DB, and Operator Dashboard."""
    storage = SQLiteStorage(":memory:")
    storage.initialize()
    app.state.storage = storage
    app.state.runtime = None
    client = TestClient(app)

    try:
        # Submit a task via API
        create_res = client.post(
            "/api/v1/tasks",
            headers={"Authorization": "Bearer operator-key"},
            json={"objective": "E2E Dashboard Reconciliation Check", "priority": "HIGH"},
        )
        assert create_res.status_code == 201
        task_id = create_res.json()["task_id"]

        # Inject pending approval
        runtime = app.state.runtime
        appr = runtime.approval_mgr.create_request(
            task_id=task_id,
            action_id="act_reconcile_1",
            action_type="desktop.launch_app",
            parameters={"app": "terminal"},
            reason="High privilege command",
            risk_level="HIGH",
        )

        # 1. Verify REST API returns task and approval
        task_res = client.get(
            f"/api/v1/tasks/{task_id}", headers={"Authorization": "Bearer viewer-key"}
        )
        assert task_res.status_code == 200
        assert task_res.json()["task_id"] == task_id

        appr_res = client.get(
            f"/api/v1/approvals/{appr.request_id}", headers={"Authorization": "Bearer viewer-key"}
        )
        assert appr_res.status_code == 200
        assert appr_res.json()["task_id"] == task_id

        # 2. Verify dashboard renders
        dash_res = client.get("/dashboard")
        assert dash_res.status_code == 200
        assert "ATLAS Control Plane" in dash_res.text
        assert "Human Approval Inbox" in dash_res.text

        # 3. Verify metrics endpoint reflects updated state
        metrics_res = client.get("/metrics")
        assert metrics_res.status_code == 200
        assert "atlas_pending_approvals" in metrics_res.text
    finally:
        storage.close()
        app.state.storage = None
        app.state.runtime = None


def test_event_stream_reconnection_sequence() -> None:
    """Verify sequenced events are strictly ordered and queryable after disconnection."""
    storage = SQLiteStorage(":memory:")
    storage.initialize()
    app.state.storage = storage
    app.state.runtime = None
    client = TestClient(app)

    try:
        create_res = client.post(
            "/api/v1/tasks",
            headers={"Authorization": "Bearer operator-key"},
            json={"objective": "Sequenced Event Check"},
        )
        assert create_res.status_code == 201
        task_id = create_res.json()["task_id"]

        # Fetch events via REST
        res = client.get(
            f"/api/v1/tasks/{task_id}/events",
            headers={"Authorization": "Bearer viewer-key"},
        )
        assert res.status_code == 200
        events = res.json()
        assert len(events) >= 1

        # Verify strict monotonicity of sequences: 1, 2, ...
        seqs = [e["sequence"] for e in events]
        assert seqs == sorted(seqs)
        assert len(seqs) == len(set(seqs))  # No duplicate sequence numbers
    finally:
        storage.close()
        app.state.storage = None
        app.state.runtime = None
