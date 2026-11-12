from datetime import UTC, datetime

import pytest
from atlas_core.contracts.action import ActionResult, ActionTarget, ComputerAction, ExpectedState
from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.model import ModelCapabilities, ModelRequest, ModelResponse
from atlas_core.contracts.observation import Observation
from atlas_core.contracts.policy import (
    ApprovalRequest,
    PolicyDecision,
    PolicyDecisionType,
    RiskLevel,
)
from atlas_core.contracts.session import Session
from atlas_core.contracts.task import Task, TaskPriority, TaskRequest, TaskStatus
from pydantic import ValidationError


def test_task_contract_serialization():
    req = TaskRequest(objective="Research cloud providers", priority=TaskPriority.HIGH)
    assert req.objective == "Research cloud providers"
    assert req.priority == TaskPriority.HIGH

    now = datetime.now(UTC)
    task = Task(
        task_id="task_123",
        objective=req.objective,
        status=TaskStatus.CREATED,
        priority=req.priority,
        created_at=now,
        updated_at=now,
    )
    json_data = task.model_dump_json()
    deserialized = Task.model_validate_json(json_data)
    assert deserialized.task_id == "task_123"
    assert deserialized.status == TaskStatus.CREATED


def test_computer_action_contract():
    action = ComputerAction(
        action_id="act_001",
        task_id="task_123",
        session_id="sess_456",
        action_type="browser.click",
        target=ActionTarget(
            strategy="accessible_role", parameters={"role": "button", "name": "Search"}
        ),
        expected_state=ExpectedState(condition="element_visible", target="Search results"),
        idempotency_key="task_123_act_001",
    )
    assert action.action_type == "browser.click"
    assert action.schema_version == "1.0"
    assert action.target.parameters["role"] == "button"


def test_action_result_contract():
    res = ActionResult(
        action_id="act_001",
        success=True,
        output={"url": "https://example.com"},
        duration_ms=120,
        evidence={"dom_mutation": True},
    )
    assert res.success is True
    assert res.error is None
    assert res.duration_ms == 120


def test_execution_event_contract():
    now = datetime.now(UTC)
    event = ExecutionEvent(
        event_id="evt_001",
        task_id="task_123",
        sequence=1,
        event_type=EventType.TASK_CREATED,
        timestamp=now,
        payload={"objective": "Test"},
        correlation_id="corr_999",
    )
    assert event.sequence == 1
    assert event.event_type == EventType.TASK_CREATED
    assert event.schema_version == "1.0"


def test_observation_contract():
    now = datetime.now(UTC)
    obs = Observation(
        observation_id="obs_001",
        task_id="task_123",
        session_id="sess_456",
        timestamp=now,
        dom_snapshot="<html><body>Hello</body></html>",
        focused_element="input#search",
        window_title="Atlas Workspace",
    )
    assert obs.observation_id == "obs_001"
    assert obs.screenshot_ref is None
    assert obs.accessibility_tree is None
    assert obs.dom_snapshot == "<html><body>Hello</body></html>"


def test_policy_and_approval_contracts():
    decision = PolicyDecision(
        decision=PolicyDecisionType.ALLOW,
        risk_level=RiskLevel.LOW,
        reason="Read-only operation allowed",
        rules_evaluated=["allow_dom_read"],
    )
    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.risk_level == RiskLevel.LOW

    approval = ApprovalRequest(
        approval_id="appr_001",
        task_id="task_123",
        action_id="act_001",
        action_hash="hash_abc123",
        risk_level=RiskLevel.CRITICAL,
        reason="Privileged terminal execution",
    )
    assert approval.approval_id == "appr_001"
    assert approval.status == "PENDING"
    assert approval.risk_level == RiskLevel.CRITICAL


def test_session_contract():
    now = datetime.now(UTC)
    sess = Session(
        session_id="sess_456",
        task_id="task_123",
        session_type="browser",
        status="active",
        created_at=now,
        updated_at=now,
    )
    assert sess.session_id == "sess_456"
    assert sess.schema_version == "1.0"


def test_checkpoint_contract():
    now = datetime.now(UTC)
    chk = Checkpoint(
        checkpoint_id="chk_001",
        task_id="task_123",
        sequence=5,
        state=TaskStatus.RUNNING,
        timestamp=now,
        state_snapshot={"step": 2},
    )
    assert chk.checkpoint_id == "chk_001"
    assert chk.sequence == 5
    assert chk.state == TaskStatus.RUNNING


def test_model_contracts():
    caps = ModelCapabilities(
        vision=True,
        tool_calling=True,
        streaming=True,
        context_window=200000,
    )
    assert caps.vision is True
    assert caps.context_window == 200000

    req = ModelRequest(
        request_id="req_001",
        task_id="task_123",
        model_name="claude-3-5-sonnet",
        messages=[{"role": "user", "content": "Click the button"}],
    )
    assert req.request_id == "req_001"
    assert req.model_name == "claude-3-5-sonnet"

    resp = ModelResponse(
        response_id="resp_001",
        request_id="req_001",
        model_name="claude-3-5-sonnet",
        content="Clicked button",
        latency_ms=350,
    )
    assert resp.response_id == "resp_001"
    assert resp.content == "Clicked button"
    assert resp.latency_ms == 350


def test_execution_event_immutability():
    now = datetime.now(UTC)
    event = ExecutionEvent(
        event_id="evt_002",
        task_id="task_123",
        sequence=2,
        event_type=EventType.ACTION_PROPOSED,
        timestamp=now,
        payload={"action_id": "act_001"},
        correlation_id="corr_100",
    )
    with pytest.raises(ValidationError):
        event.sequence = 999


def test_package_re_exports():
    import atlas_core.contracts as contracts

    assert hasattr(contracts, "Task")
    assert hasattr(contracts, "TaskRequest")
    assert hasattr(contracts, "TaskStatus")
    assert hasattr(contracts, "TaskPriority")
    assert hasattr(contracts, "ComputerAction")
    assert hasattr(contracts, "ActionTarget")
    assert hasattr(contracts, "ActionResult")
    assert hasattr(contracts, "ExpectedState")
    assert hasattr(contracts, "Observation")
    assert hasattr(contracts, "ExecutionEvent")
    assert hasattr(contracts, "EventType")
    assert hasattr(contracts, "PolicyDecision")
    assert hasattr(contracts, "PolicyDecisionType")
    assert hasattr(contracts, "RiskLevel")
    assert hasattr(contracts, "ApprovalRequest")
    assert hasattr(contracts, "Session")
    assert hasattr(contracts, "Checkpoint")
    assert hasattr(contracts, "ModelRequest")
    assert hasattr(contracts, "ModelResponse")
    assert hasattr(contracts, "ModelCapabilities")
