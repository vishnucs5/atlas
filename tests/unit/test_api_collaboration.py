"""API endpoint tests for Phase 17 Collaboration, Steering & Compliance."""

from atlas_api.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_api_workspace_session_and_lease():
    """Verify POST /api/v1/workspaces/sessions and lease acquisition."""
    # 1. Create workspace session
    res = client.post(
        "/api/v1/workspaces/sessions",
        json={
            "tenant_id": "tenant_api_01",
            "workspace_name": "API Review",
            "owner_identity": "operator_alice",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert "session_id" in data
    sid = data["session_id"]

    # 2. Get snapshot
    snap_res = client.get(f"/api/v1/workspaces/sessions/{sid}")
    assert snap_res.status_code == 200
    assert snap_res.json()["collaborator_count"] == 1

    # 3. Acquire turn lease
    lease_res = client.post(
        f"/api/v1/workspaces/sessions/{sid}/lease",
        json={"identity": "operator_alice", "duration_seconds": 60.0},
    )
    assert lease_res.status_code == 200
    assert lease_res.json()["holder_identity"] == "operator_alice"
    assert lease_res.json()["fencing_token"] == 1


def test_api_steering_pause_and_resume():
    """Verify POST /api/v1/instances/{id}/steering/pause and resume."""
    # 1. Pause
    pause_res = client.post(
        "/api/v1/instances/pinst_api_99/steering/pause",
        json={
            "task_instance_id": "task_api_99",
            "operator_id": "operator_alice",
            "reason": "Auditing line item",
        },
    )
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "PAUSED_FOR_STEERING"

    # 2. Resume with parameter injection
    resume_res = client.post(
        "/api/v1/instances/pinst_api_99/steering/resume",
        json={
            "task_instance_id": "task_api_99",
            "operator_id": "operator_alice",
            "parent_operation_key": "op_parent_99",
            "original_parameters": {"qty": 10},
            "modified_parameters": {"qty": 5},
            "reason": "Halved requested quantity",
        },
    )
    assert resume_res.status_code == 200
    data = resume_res.json()
    assert data["status"] == "RESUMED"
    assert "child_operation_key" in data


def test_api_compliance_bundle_generation():
    """Verify POST /api/v1/governance/compliance/bundles."""
    res = client.post(
        "/api/v1/governance/compliance/bundles",
        json={
            "tenant_id": "tenant_api_01",
            "framework": "SOC2",
            "records": [{"event": "POLICY_CHECK", "status": "ALLOW"}],
        },
    )
    assert res.status_code == 200
    bundle = res.json()
    assert bundle["framework"] == "SOC2"
    assert bundle["record_count"] == 1
    assert bundle["signature"] != ""
