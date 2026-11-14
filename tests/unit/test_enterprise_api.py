"""Unit tests for Enterprise REST API endpoints (Milestone 6)."""

import hashlib
import hmac

from atlas_api.main import app
from fastapi.testclient import TestClient


def test_enterprise_api_organization_and_iam_flow() -> None:
    """Verify enterprise organization provisioning, department scoping, member enrollment, and login."""
    client = TestClient(app)

    # 1. Provision organization
    org_res = client.post(
        "/api/v1/enterprise/organizations",
        json={
            "name": "Nexus Dynamics",
            "slug": "nexus",
            "owner_email": "owner@nexus.com",
            "owner_name": "Nexus Owner",
        },
    )
    assert org_res.status_code == 200
    org_data = org_res.json()
    org_id = org_data["organization"]["org_id"]
    owner_id = org_data["owner"]["user_id"]
    assert org_data["organization"]["name"] == "Nexus Dynamics"

    # 2. Get organization
    get_res = client.get(f"/api/v1/enterprise/organizations/{org_id}")
    assert get_res.status_code == 200
    assert get_res.json()["slug"] == "nexus"

    # 3. Create Department
    dept_res = client.post(
        f"/api/v1/enterprise/organizations/{org_id}/departments",
        json={"name": "Engineering", "slug": "eng", "budget_usd": 25000.0},
    )
    assert dept_res.status_code == 200
    dept_id = dept_res.json()["department_id"]

    # 4. Enroll Member
    member_res = client.post(
        f"/api/v1/enterprise/organizations/{org_id}/members",
        json={
            "email": "dev1@nexus.com",
            "full_name": "Dev One",
            "role": "Developer",
            "department_id": dept_id,
        },
    )
    assert member_res.status_code == 200
    dev_user_id = member_res.json()["user"]["user_id"]

    # 5. Login / Create Session
    login_res = client.post(
        "/api/v1/enterprise/iam/login",
        json={"user_id": dev_user_id, "org_id": org_id},
    )
    assert login_res.status_code == 200
    token_id = login_res.json()["token_id"]
    assert token_id.startswith("atk_sess_")

    # 6. Revoke Session
    revoke_res = client.post(f"/api/v1/enterprise/iam/sessions/{token_id}/revoke")
    assert revoke_res.status_code == 200
    assert revoke_res.json()["status"] == "revoked"

    # 7. Create Service Identity
    svc_res = client.post(
        "/api/v1/enterprise/iam/service-identities",
        json={
            "org_id": org_id,
            "name": "CI-Daemon",
            "scopes": ["workflow:execute"],
        },
    )
    assert svc_res.status_code == 200
    assert svc_res.json()["api_key"].startswith("atk_live_")

    # 8. Register Agent
    ag_res = client.post(
        "/api/v1/enterprise/agents",
        json={
            "caller_user_id": owner_id,
            "org_id": org_id,
            "name": "AutoTester",
            "owner_user_id": dev_user_id,
            "allowed_tools": ["filesystem", "python_runner"],
            "department_id": dept_id,
        },
    )
    assert ag_res.status_code == 200
    ag_id = ag_res.json()["agent_id"]
    assert ag_id.startswith("ag_")

    # 9. Register Connector & Verify
    conn_res = client.post(
        "/api/v1/enterprise/connectors",
        json={
            "caller_user_id": owner_id,
            "org_id": org_id,
            "name": "SlackAlerts",
            "connector_type": "COMMUNICATION",
            "provider": "slack",
            "config": {"default_channel": "#alerts"},
            "secrets": {"bot_token": "xoxb-test-token-valid"},
        },
    )
    assert conn_res.status_code == 200
    conn_id = conn_res.json()["connector_id"]

    verify_res = client.post(
        f"/api/v1/enterprise/connectors/{conn_id}/verify?caller_user_id={owner_id}"
    )
    assert verify_res.status_code == 200
    assert verify_res.json()["success"] is True
    assert verify_res.json()["status"] == "ACTIVE"

    # 10. Webhook Ingestion with HMAC
    wh_conn_res = client.post(
        "/api/v1/enterprise/connectors",
        json={
            "caller_user_id": owner_id,
            "org_id": org_id,
            "name": "GitHubHooks",
            "connector_type": "WEBHOOK",
            "provider": "generic_webhook",
            "config": {"url": "https://github.com"},
            "secrets": {"signing_secret": "github_secret_key_123"},
        },
    )
    wh_conn_id = wh_conn_res.json()["connector_id"]

    raw_body = b'{"action":"ping"}'
    valid_sig = hmac.new(b"github_secret_key_123", raw_body, hashlib.sha256).hexdigest()

    wh_res = client.post(
        f"/api/v1/enterprise/webhooks/{wh_conn_id}",
        content=raw_body,
        headers={"x-hub-signature-256": f"sha256={valid_sig}"},
    )
    assert wh_res.status_code == 200
    assert wh_res.json()["status"] == "accepted"

    # 11. Cost Recording & Budget Envelope
    bgt_res = client.post(
        "/api/v1/enterprise/cost/budgets",
        json={
            "caller_user_id": owner_id,
            "org_id": org_id,
            "department_id": dept_id,
            "allocated_usd": 100.0,
            "alert_threshold_pct": 80.0,
        },
    )
    assert bgt_res.status_code == 200

    cost_res = client.post(
        "/api/v1/enterprise/cost/usage",
        json={
            "org_id": org_id,
            "department_id": dept_id,
            "task_id": "task_api_test",
            "model_name": "gemini-1.5-flash",
            "prompt_tokens": 10000,
            "completion_tokens": 2000,
            "compute_duration_ms": 1500,
        },
    )
    assert cost_res.status_code == 200
    assert cost_res.json()["record"]["total_cost_usd"] > 0.0

    # 12. Verify Audit Chain
    audit_res = client.get(f"/api/v1/enterprise/audit/verify?org_id={org_id}")
    assert audit_res.status_code == 200
    assert audit_res.json()["is_intact"] is True

    # 13. Operational Analytics
    analytics_res = client.get(
        f"/api/v1/enterprise/analytics?caller_user_id={owner_id}&org_id={org_id}"
    )
    assert analytics_res.status_code == 200
    assert analytics_res.json()["compliance_score"] == 100.0
    assert analytics_res.json()["total_audit_events"] > 0
