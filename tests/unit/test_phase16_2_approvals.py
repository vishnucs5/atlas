"""Tests for HumanApprovalEngine terminal state locking and integrity in atlas_process."""

import time

import pytest
from atlas_process.approvals import (
    ApprovalDecision,
    ApprovalError,
    ApprovalExpiredError,
    HumanApprovalEngine,
    ParameterTamperedError,
    SeparationOfDutiesViolationError,
)


def test_rejection_permanently_locks_request():
    engine = HumanApprovalEngine()
    req = engine.create_approval_request(
        process_instance_id="p-200",
        task_def_id="task-prod-deploy",
        action_name="deploy",
        target_resource="k8s-cluster",
        parameters={"image": "atlas:v16.2"},
        requesting_identity="ci-agent",
        allowed_approver_ids=["sec-officer", "ops-lead", "dev-lead"],
        required_approvals=2,
    )

    # Security officer rejects
    engine.decide(req.approval_id, "sec-officer", ApprovalDecision.REJECTED, comments="CVE found")
    assert req.status == ApprovalDecision.REJECTED
    assert req.resolved_at is not None

    # Subsequent approval attempts by other approvers MUST raise ApprovalError
    with pytest.raises(ApprovalError, match="has already been resolved"):
        engine.decide(
            req.approval_id, "ops-lead", ApprovalDecision.APPROVED, comments="Looks fine to me"
        )

    assert req.status == ApprovalDecision.REJECTED


def test_approval_resolution_permanently_locks_request():
    engine = HumanApprovalEngine()
    req = engine.create_approval_request(
        process_instance_id="p-201",
        task_def_id="task-wire-transfer",
        action_name="transfer",
        target_resource="bank-api",
        parameters={"amount": 50000},
        requesting_identity="finance-bot",
        allowed_approver_ids=["cfo", "controller"],
        required_approvals=1,
    )

    engine.decide(req.approval_id, "cfo", ApprovalDecision.APPROVED, comments="Authorized")
    assert req.status == ApprovalDecision.APPROVED
    assert req.resolved_at is not None

    # Late rejection cannot reverse an approved request
    with pytest.raises(ApprovalError, match="has already been resolved"):
        engine.decide(req.approval_id, "controller", ApprovalDecision.REJECTED, comments="Wait")

    assert req.status == ApprovalDecision.APPROVED


def test_expired_approval_cannot_accept_decisions():
    engine = HumanApprovalEngine()
    req = engine.create_approval_request(
        process_instance_id="p-202",
        task_def_id="task-quick-action",
        action_name="restart",
        target_resource="node-1",
        parameters={},
        requesting_identity="admin",
        allowed_approver_ids=["lead"],
        duration_seconds=0.01,  # Expires immediately
    )
    time.sleep(0.05)

    with pytest.raises(ApprovalExpiredError):
        engine.decide(req.approval_id, "lead", ApprovalDecision.APPROVED)

    assert req.status == ApprovalDecision.EXPIRED


def test_separation_of_duties_and_parameter_tampering():
    engine = HumanApprovalEngine()
    req = engine.create_approval_request(
        process_instance_id="p-203",
        task_def_id="task-privileged",
        action_name="grant_role",
        target_resource="iam",
        parameters={"role": "ADMIN", "user": "alice"},
        requesting_identity="bob",
        allowed_approver_ids=["bob", "charlie"],
    )

    # Bob cannot approve his own request
    with pytest.raises(SeparationOfDutiesViolationError):
        engine.decide(req.approval_id, "bob", ApprovalDecision.APPROVED)

    # Parameter tampering detected
    with pytest.raises(ParameterTamperedError):
        engine.decide(
            req.approval_id,
            "charlie",
            ApprovalDecision.APPROVED,
            current_parameters={"role": "SUPER_ADMIN", "user": "alice"},
        )
