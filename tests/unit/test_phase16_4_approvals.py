"""Unit tests for Phase 16.4 Human Approval Concurrency, Quorum & Persistence."""

import concurrent.futures

import pytest
from atlas_process.approvals import (
    ApprovalDecision,
    ApprovalError,
    HumanApprovalEngine,
)
from atlas_process.storage import (
    InMemoryProcessStorage,
    SqliteProcessStorage,
)


@pytest.fixture(params=["memory", "sqlite"])
def storage(request, tmp_path):
    if request.param == "memory":
        return InMemoryProcessStorage()
    db_path = str(tmp_path / "test_approvals.db")
    s = SqliteProcessStorage(db_path)
    s.initialize()
    return s


def test_quorum_persistence_across_engine_restarts(storage):
    """Verify that multi-approver quorum progress survives process engine restarts."""
    engine1 = HumanApprovalEngine(storage=storage)
    req = engine1.create_approval_request(
        process_instance_id="proc_payroll_01",
        task_def_id="task_payroll_01",
        action_name="execute_bonus_payout",
        target_resource="bank_account_primary",
        parameters={"total_usd": 150000},
        requesting_identity="agent_hr_worker",
        allowed_approver_ids=["manager_alice", "vp_bob", "cfo_carol"],
        required_approvals=2,
    )
    assert req.status == ApprovalDecision.PENDING
    assert len(req.decisions) == 0

    # Approver 1 submits approval
    engine1.decide(
        approval_id=req.approval_id,
        approver_id="manager_alice",
        decision=ApprovalDecision.APPROVED,
        comments="Manager approval granted",
    )

    # Status must still be PENDING (1/2 approvals)
    req1 = engine1.get_approval(req.approval_id)
    assert req1 is not None
    assert req1.status == ApprovalDecision.PENDING
    assert len(req1.decisions) == 1

    # SIMULATE ENGINE RESTART: Fresh engine instance with only storage
    engine2 = HumanApprovalEngine(storage=storage)
    recovered = engine2.get_approval(req.approval_id)
    assert recovered is not None
    assert recovered.status == ApprovalDecision.PENDING
    assert len(recovered.decisions) == 1
    assert recovered.decisions[0].approver_id == "manager_alice"

    # Approver 2 submits approval on new engine instance
    updated = engine2.decide(
        approval_id=req.approval_id,
        approver_id="vp_bob",
        decision=ApprovalDecision.APPROVED,
        comments="VP approval granted",
    )

    # Quorum (2/2) reached! Status must be APPROVED
    assert updated.status == ApprovalDecision.APPROVED
    assert len(updated.decisions) == 2

    # Storage verifies terminal APPROVED state with both decisions persisted
    saved = storage.get_approval(req.approval_id)
    assert saved is not None
    assert saved.status == ApprovalDecision.APPROVED
    assert len(saved.decisions) == 2


def test_duplicate_approver_rejection(storage):
    """Verify an approver cannot cast multiple votes on the same approval request."""
    engine = HumanApprovalEngine(storage=storage)
    req = engine.create_approval_request(
        process_instance_id="proc_deploy_01",
        task_def_id="task_deploy_01",
        action_name="deploy_to_prod",
        target_resource="k8s_cluster_prod",
        parameters={"service": "auth"},
        requesting_identity="ci_bot",
        allowed_approver_ids=["alice", "bob"],
        required_approvals=2,
    )

    # Alice votes once
    engine.decide(req.approval_id, "alice", ApprovalDecision.APPROVED)

    # Alice tries to vote a second time
    with pytest.raises(ApprovalError, match="already submitted a decision"):
        engine.decide(req.approval_id, "alice", ApprovalDecision.APPROVED)


def test_terminal_state_immutability(storage):
    """Verify that once an approval is approved or rejected, no further votes are accepted."""
    engine = HumanApprovalEngine(storage=storage)
    req = engine.create_approval_request(
        process_instance_id="proc_db_01",
        task_def_id="task_delete_db",
        action_name="drop_database",
        target_resource="db_legacy",
        parameters={"db": "legacy"},
        requesting_identity="dba_bot",
        allowed_approver_ids=["alice", "bob"],
        required_approvals=1,
    )

    # Alice rejects
    engine.decide(req.approval_id, "alice", ApprovalDecision.REJECTED, comments="Too risky")
    res = engine.get_approval(req.approval_id)
    assert res is not None
    assert res.status == ApprovalDecision.REJECTED

    # Bob attempts to approve after rejection
    with pytest.raises(ApprovalError, match="cannot accept further decisions"):
        engine.decide(req.approval_id, "bob", ApprovalDecision.APPROVED)


def test_concurrent_approver_decisions(storage):
    """Verify thread-safety when multiple approvers decide concurrently."""
    engine = HumanApprovalEngine(storage=storage)
    approvers = [f"approver_{i}" for i in range(10)]
    req = engine.create_approval_request(
        process_instance_id="proc_multi",
        task_def_id="task_multivote",
        action_name="concurrency_test",
        target_resource="resource_pool",
        parameters={},
        requesting_identity="test_agent",
        allowed_approver_ids=approvers,
        required_approvals=5,
    )

    def submit_vote(approver):
        try:
            return engine.decide(req.approval_id, approver, ApprovalDecision.APPROVED)
        except Exception as e:
            return e

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        _ = list(pool.map(submit_vote, approvers[:6]))

    final_req = engine.get_approval(req.approval_id)
    assert final_req is not None
    # 5 approvals reached terminal status
    assert final_req.status == ApprovalDecision.APPROVED
    assert len(final_req.decisions) >= 5
