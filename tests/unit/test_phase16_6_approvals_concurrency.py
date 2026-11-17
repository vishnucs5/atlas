"""Unit and concurrency tests for Phase 16.6 multi-node approval consistency."""

import pathlib
import tempfile
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
from atlas_process.storage import SqliteProcessStorage


@pytest.fixture
def sqlite_storage():
    with tempfile.TemporaryDirectory() as td:
        db_file = pathlib.Path(td) / "test_approvals.db"
        storage = SqliteProcessStorage(db_file)
        storage.initialize()
        yield storage


def test_approval_multi_node_cache_consistency(sqlite_storage):
    """Test that two independent engine nodes do not stall approvals due to local RAM caching."""
    node_a = HumanApprovalEngine(storage=sqlite_storage)
    node_b = HumanApprovalEngine(storage=sqlite_storage)

    # Node A creates approval request (required=2)
    req = node_a.create_approval_request(
        process_instance_id="inst_1",
        task_def_id="task_1",
        action_name="release_payment",
        target_resource="treasury",
        parameters={"amount": 1000},
        requesting_identity="requester_user",
        allowed_approver_ids=["approver_1", "approver_2", "approver_3"],
        required_approvals=2,
    )
    appr_id = req.approval_id

    # Node B fetches initial state before any votes are cast
    b_view = node_b.get_approval(appr_id)
    assert b_view is not None
    assert len(b_view.decisions) == 0

    # Approver 1 votes on Node A
    voted_a = node_a.decide(appr_id, "approver_1", ApprovalDecision.APPROVED)
    assert voted_a.status == ApprovalDecision.PENDING
    assert len(voted_a.decisions) == 1

    # Approver 2 votes on Node B (Node B must see Approver 1's vote from storage)
    voted_b = node_b.decide(appr_id, "approver_2", ApprovalDecision.APPROVED)
    assert voted_b.status == ApprovalDecision.APPROVED
    assert len(voted_b.decisions) == 2

    # Verification on Node A and fresh node
    node_c = HumanApprovalEngine(storage=sqlite_storage)
    c_view = node_c.get_approval(appr_id)
    assert c_view.status == ApprovalDecision.APPROVED
    assert len(c_view.decisions) == 2


def test_approval_terminal_rejection_preempts_across_nodes(sqlite_storage):
    """Test that a rejection on one node immediately terminates request and blocks further approvals."""
    node_a = HumanApprovalEngine(storage=sqlite_storage)
    node_b = HumanApprovalEngine(storage=sqlite_storage)

    req = node_a.create_approval_request(
        process_instance_id="inst_2",
        task_def_id="task_2",
        action_name="delete_account",
        target_resource="users",
        parameters={"user_id": 42},
        requesting_identity="admin_requester",
        allowed_approver_ids=["approver_1", "approver_2"],
        required_approvals=2,
    )
    appr_id = req.approval_id

    # Approver 1 rejects on Node A
    rejected = node_a.decide(appr_id, "approver_1", ApprovalDecision.REJECTED)
    assert rejected.status == ApprovalDecision.REJECTED

    # Approver 2 attempts to approve on Node B: must be rejected with ApprovalError
    with pytest.raises(ApprovalError, match="has already been resolved"):
        node_b.decide(appr_id, "approver_2", ApprovalDecision.APPROVED)


def test_approval_duplicate_vote_rejection_across_nodes(sqlite_storage):
    """Test that duplicate votes by same approver across nodes are rejected."""
    node_a = HumanApprovalEngine(storage=sqlite_storage)
    node_b = HumanApprovalEngine(storage=sqlite_storage)

    req = node_a.create_approval_request(
        process_instance_id="inst_3",
        task_def_id="task_3",
        action_name="promote_user",
        target_resource="rbac",
        parameters={"target": "alice"},
        requesting_identity="creator",
        allowed_approver_ids=["approver_1", "approver_2"],
        required_approvals=2,
    )
    appr_id = req.approval_id

    # Approver 1 votes on Node A
    node_a.decide(appr_id, "approver_1", ApprovalDecision.APPROVED)

    # Approver 1 attempts to vote again on Node B
    with pytest.raises(ApprovalError, match="already submitted a decision"):
        node_b.decide(appr_id, "approver_1", ApprovalDecision.APPROVED)


def test_approval_separation_of_duties_enforced(sqlite_storage):
    """Test that requester cannot approve their own action even across nodes."""
    node_a = HumanApprovalEngine(storage=sqlite_storage)
    node_b = HumanApprovalEngine(storage=sqlite_storage)

    req = node_a.create_approval_request(
        process_instance_id="inst_4",
        task_def_id="task_4",
        action_name="transfer",
        target_resource="bank",
        parameters={"amount": 500},
        requesting_identity="bob_requester",
        allowed_approver_ids=["bob_requester", "approver_1"],
        required_approvals=1,
    )
    with pytest.raises(SeparationOfDutiesViolationError):
        node_b.decide(req.approval_id, "bob_requester", ApprovalDecision.APPROVED)


def test_approval_parameter_tampering_rejected(sqlite_storage):
    """Test that modified parameters trigger ParameterTamperedError."""
    node_a = HumanApprovalEngine(storage=sqlite_storage)
    node_b = HumanApprovalEngine(storage=sqlite_storage)

    req = node_a.create_approval_request(
        process_instance_id="inst_5",
        task_def_id="task_5",
        action_name="payout",
        target_resource="bank",
        parameters={"amount": 500},
        requesting_identity="requester",
        allowed_approver_ids=["approver_1"],
        required_approvals=1,
    )
    with pytest.raises(ParameterTamperedError):
        node_b.decide(
            req.approval_id,
            "approver_1",
            ApprovalDecision.APPROVED,
            current_parameters={"amount": 999999},  # Tampered!
        )


def test_approval_expiration_handling(sqlite_storage):
    """Test that expired approval requests are rejected."""
    node = HumanApprovalEngine(storage=sqlite_storage)
    req = node.create_approval_request(
        process_instance_id="inst_6",
        task_def_id="task_6",
        action_name="action",
        target_resource="target",
        parameters={},
        requesting_identity="requester",
        allowed_approver_ids=["approver_1"],
        duration_seconds=0.01,
    )
    time.sleep(0.02)
    with pytest.raises(ApprovalExpiredError):
        node.decide(req.approval_id, "approver_1", ApprovalDecision.APPROVED)
