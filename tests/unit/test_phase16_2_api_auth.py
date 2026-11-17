"""Unit tests for Phase 16.2 API Authentication & Tenant Authorization (REM-16.1-03)."""

from __future__ import annotations

import pytest
from atlas_process.api import (
    router,
    set_api_approval_engine,
    set_api_engine,
)
from atlas_process.approvals import (
    HumanApprovalEngine,
)
from atlas_process.auth import (
    ProcessCallerIdentity,
    clear_api_keys,
    issue_process_token,
    register_api_key,
)
from atlas_process.definitions import (
    ProcessDefinition,
    ProcessTaskDefinition,
    TaskType,
)
from atlas_process.engine import ProcessExecutionEngine
from atlas_process.storage import InMemoryProcessStorage
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def api_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def setup_engines():
    storage = InMemoryProcessStorage()
    engine = ProcessExecutionEngine(storage=storage)
    approval_engine = HumanApprovalEngine(storage=storage)
    set_api_engine(engine)
    set_api_approval_engine(approval_engine)
    clear_api_keys()
    yield engine, approval_engine
    clear_api_keys()


def test_unauthenticated_requests_rejected(api_client: TestClient) -> None:
    """All endpoints must reject unauthenticated requests with 401."""
    # 1. create definition
    r1 = api_client.post("/api/v1/processes/definitions", json={"name": "test", "tasks": []})
    assert r1.status_code == 401
    assert "credentials required" in r1.json()["detail"].lower()

    # 2. start instance
    r2 = api_client.post(
        "/api/v1/processes/instances", json={"definition_id": "d1", "tenant_id": "t1"}
    )
    assert r2.status_code == 401

    # 3. get instance
    r3 = api_client.get("/api/v1/processes/instances/inst_123")
    assert r3.status_code == 401

    # 4. submit approval decision
    r4 = api_client.post(
        "/api/v1/processes/approvals/app_123/decide",
        json={"approver_id": "u1", "decision": "APPROVED"},
    )
    assert r4.status_code == 401

    # 5. get analytics
    r5 = api_client.get("/api/v1/processes/analytics/tenant_1")
    assert r5.status_code == 401


def test_invalid_bearer_token_rejected(api_client: TestClient) -> None:
    """Invalid, tampered, or expired tokens must be rejected with 401."""
    headers = {"Authorization": "Bearer not_a_valid_token"}
    resp = api_client.get("/api/v1/processes/instances/inst_123", headers=headers)
    assert resp.status_code == 401
    assert "invalid" in resp.json()["detail"].lower()


def test_authenticated_definition_and_instance_lifecycle(
    api_client: TestClient, setup_engines
) -> None:
    """Authenticated caller can create definitions and start instances in their tenant."""
    engine, _ = setup_engines
    token = issue_process_token(caller_id="alice", tenant_id="tenant_alpha")
    headers = {"Authorization": f"Bearer {token}"}

    # Register definition
    pdef_data = {
        "definition_id": "def_test_01",
        "name": "TestDef",
        "tenant_id": "tenant_alpha",
        "tasks": [
            {
                "task_def_id": "t1",
                "name": "Task 1",
                "task_type": "AGENT_EXECUTION",
            }
        ],
    }
    resp = api_client.post("/api/v1/processes/definitions", json=pdef_data, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["definition_id"] == "def_test_01"

    # Start instance
    start_data = {
        "definition_id": "def_test_01",
        "tenant_id": "tenant_alpha",
        "variables": {"init_val": 42},
    }
    resp2 = api_client.post("/api/v1/processes/instances", json=start_data, headers=headers)
    assert resp2.status_code == 201
    inst_id = resp2.json()["instance_id"]

    # Read instance details
    resp3 = api_client.get(f"/api/v1/processes/instances/{inst_id}", headers=headers)
    assert resp3.status_code == 200
    assert resp3.json()["instance_id"] == inst_id
    assert resp3.json()["tenant_id"] == "tenant_alpha"


def test_cross_tenant_isolation_enforced(api_client: TestClient, setup_engines) -> None:
    """A caller from tenant_alpha cannot access an instance belonging to tenant_beta."""
    engine, _ = setup_engines
    # Create definition and instance under tenant_beta
    pdef = ProcessDefinition(
        definition_id="def_beta",
        name="BetaDef",
        tenant_id="tenant_beta",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="tb1", name="Task Beta", task_type=TaskType.AGENT_EXECUTION
            )
        ],
    )
    engine.register_definition(pdef)
    inst = engine.start_process(definition_id="def_beta", tenant_id="tenant_beta")

    # Caller from tenant_alpha tries to read tenant_beta instance
    alpha_token = issue_process_token(caller_id="bob", tenant_id="tenant_alpha")
    headers = {"Authorization": f"Bearer {alpha_token}"}

    resp = api_client.get(f"/api/v1/processes/instances/{inst.instance_id}", headers=headers)
    assert resp.status_code == 403
    assert "cross-tenant access forbidden" in resp.json()["detail"].lower()


def test_cross_tenant_analytics_forbidden(api_client: TestClient) -> None:
    """A caller cannot view analytics of another tenant."""
    alpha_token = issue_process_token(caller_id="bob", tenant_id="tenant_alpha")
    headers = {"Authorization": f"Bearer {alpha_token}"}

    resp = api_client.get("/api/v1/processes/analytics/tenant_beta", headers=headers)
    assert resp.status_code == 403
    assert "cross-tenant" in resp.json()["detail"].lower()


def test_approval_impersonation_prevented(api_client: TestClient, setup_engines) -> None:
    """A user cannot submit an approval decision posing as another user unless they are admin."""
    _, approval_engine = setup_engines
    approval = approval_engine.create_approval_request(
        process_instance_id="pinst_01",
        task_def_id="ptask_01",
        action_name="Budget Review",
        target_resource="finance/budget",
        parameters={"amount": 50000},
        requesting_identity="requester_bob",
        allowed_approver_ids=["manager_carol"],
        tenant_id="tenant_finance",
    )

    # Eve tries to submit approval decision pretending to be manager_carol
    eve_token = issue_process_token(caller_id="eve", tenant_id="tenant_finance", roles=["USER"])
    headers = {"Authorization": f"Bearer {eve_token}"}

    req_data = {
        "approver_id": "manager_carol",
        "decision": "APPROVED",
        "comments": "Approved on your behalf",
    }
    resp = api_client.post(
        f"/api/v1/processes/approvals/{approval.approval_id}/decide",
        json=req_data,
        headers=headers,
    )
    assert resp.status_code == 403
    assert "cannot decide on behalf of" in resp.json()["detail"]


def test_api_key_authentication(api_client: TestClient, setup_engines) -> None:
    """API key passed via X-API-Key header works identically to bearer tokens."""
    api_key = "ak_live_securekey123456789"
    identity = ProcessCallerIdentity(
        caller_id="svc_automation",
        tenant_id="tenant_corp",
        roles=["SERVICE"],
        scopes=["process:read"],
        is_service=True,
    )
    register_api_key(api_key, identity)

    headers = {"X-API-Key": api_key}
    resp = api_client.get("/api/v1/processes/analytics/tenant_corp", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "tenant_corp"


def test_admin_cross_tenant_access_allowed(api_client: TestClient, setup_engines) -> None:
    """System administrator can inspect resources across tenants."""
    engine, _ = setup_engines
    pdef = ProcessDefinition(
        definition_id="def_gamma",
        name="GammaDef",
        tenant_id="tenant_gamma",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="tg1", name="Task Gamma", task_type=TaskType.AGENT_EXECUTION
            )
        ],
    )
    engine.register_definition(pdef)
    inst = engine.start_process(definition_id="def_gamma", tenant_id="tenant_gamma")

    admin_token = issue_process_token(
        caller_id="admin_user", tenant_id="system_tenant", roles=["ADMIN"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    resp = api_client.get(f"/api/v1/processes/instances/{inst.instance_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["instance_id"] == inst.instance_id
