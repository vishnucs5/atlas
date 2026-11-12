"""Unit tests for ActionLedger: deduplication, UNKNOWN outcome handling, and commit fencing."""

from pathlib import Path

import pytest
from atlas_coordination.action_ledger import (
    ActionLedger,
    NonIdempotentActionUncertaintyError,
    compute_idempotency_key,
)
from atlas_coordination.lease_manager import WorkerLeaseManager
from atlas_coordination.worker_registry import WorkerRegistryManager
from atlas_core.contracts.ledger import ActionExecutionStatus
from atlas_storage.interfaces import StaleWorkerError
from atlas_storage.sqlite import SQLiteStorage


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStorage:
    db = tmp_path / "test_ledger.db"
    s = SQLiteStorage(str(db))
    s.initialize()
    return s


def test_idempotency_key_deterministic_and_redacted() -> None:
    p1 = {"selector": "#btn", "password": "super-secret-1"}
    p2 = {"selector": "#btn", "password": "super-secret-2"}

    # Passwords are both redacted to ***REDACTED***, so idempotency key matches
    k1 = compute_idempotency_key("t1", "click", p1, step_id="s1")
    k2 = compute_idempotency_key("t1", "click", p2, step_id="s1")
    assert k1 == k2

    # Different selector produces different key
    k3 = compute_idempotency_key("t1", "click", {"selector": "#other"}, step_id="s1")
    assert k1 != k3


def test_action_deduplication(store: SQLiteStorage) -> None:
    registry = WorkerRegistryManager(store)
    registry.register("w1", "h1", ["browser"])
    lease_mgr = WorkerLeaseManager(store)
    lease = lease_mgr.acquire_lease("t_dedup", "w1", ttl_seconds=30.0)

    ledger = ActionLedger(store=store, lease_manager=lease_mgr)

    # Start action
    rec1 = ledger.start_action(
        action_id="act_nav_1",
        task_id="t_dedup",
        action_type="navigate",
        parameters={"url": "https://example.com"},
        worker_id="w1",
        lease_generation=lease.generation,
    )
    assert rec1.status == ActionExecutionStatus.STARTED
    assert rec1.attempt == 1

    # Succeeded
    succeeded = ledger.mark_succeeded(
        task_id="t_dedup",
        idempotency_key=rec1.idempotency_key,
        attempt=1,
        output={"status": 200},
        lease_generation=lease.generation,
        worker_id="w1",
    )
    assert succeeded.status == ActionExecutionStatus.SUCCEEDED

    # Repeated call with same parameters returns existing succeeded record (deduplication)
    rec2 = ledger.start_action(
        action_id="act_nav_1",
        task_id="t_dedup",
        action_type="navigate",
        parameters={"url": "https://example.com"},
        worker_id="w1",
        lease_generation=lease.generation,
    )
    assert rec2.status == ActionExecutionStatus.SUCCEEDED
    assert rec2.attempt == 1
    assert rec2.output == {"status": 200}


def test_unknown_state_and_safe_vs_unsafe_retries(store: SQLiteStorage) -> None:
    registry = WorkerRegistryManager(store)
    registry.register("w1", "h1", ["browser"])
    lease_mgr = WorkerLeaseManager(store)
    lease = lease_mgr.acquire_lease("t_unknown", "w1", ttl_seconds=30.0)

    ledger = ActionLedger(store=store, lease_manager=lease_mgr)

    # 1. Non-idempotent action: "submit_payment"
    pay_rec = ledger.start_action(
        action_id="act_pay_1",
        task_id="t_unknown",
        action_type="submit_payment",
        parameters={"amount": 100},
        worker_id="w1",
        lease_generation=lease.generation,
    )
    # Simulate crash by marking UNKNOWN
    ledger.mark_unknown(
        "t_unknown", pay_rec.idempotency_key, attempt=1, reason="Worker died during post"
    )

    # Blind re-execution must raise NonIdempotentActionUncertaintyError
    with pytest.raises(NonIdempotentActionUncertaintyError) as exc_info:
        ledger.start_action(
            action_id="act_pay_1",
            task_id="t_unknown",
            action_type="submit_payment",
            parameters={"amount": 100},
            worker_id="w1",
            lease_generation=lease.generation,
        )
    assert (
        "Non-idempotent action cannot be re-executed without physical environment reconciliation"
        in str(exc_info.value)
    )

    # Force retry after reconciliation succeeds
    pay_retry = ledger.start_action(
        action_id="act_pay_1",
        task_id="t_unknown",
        action_type="submit_payment",
        parameters={"amount": 100},
        worker_id="w1",
        lease_generation=lease.generation,
        force_retry=True,
    )
    assert pay_retry.attempt == 2
    assert pay_retry.status == ActionExecutionStatus.STARTED

    # 2. Idempotent action: "navigate"
    nav_rec = ledger.start_action(
        action_id="act_nav_test",
        task_id="t_unknown",
        action_type="navigate",
        parameters={"url": "https://example.com/checkout"},
        worker_id="w1",
        lease_generation=lease.generation,
    )
    ledger.mark_unknown(
        "t_unknown", nav_rec.idempotency_key, attempt=1, reason="Browser disconnected"
    )

    # Idempotent action can be retried automatically without exception
    nav_retry = ledger.start_action(
        action_id="act_nav_test",
        task_id="t_unknown",
        action_type="navigate",
        parameters={"url": "https://example.com/checkout"},
        worker_id="w1",
        lease_generation=lease.generation,
    )
    assert nav_retry.attempt == 2
    assert nav_retry.status == ActionExecutionStatus.STARTED


def test_action_ledger_commit_fencing(store: SQLiteStorage) -> None:
    registry = WorkerRegistryManager(store)
    registry.register("w1", "h1", ["browser"])
    registry.register("w2", "h2", ["browser"])
    lease_mgr = WorkerLeaseManager(store)

    lease_mgr.acquire_lease("t_fence", "w1", ttl_seconds=0.01)

    import time

    time.sleep(0.02)

    # Worker 2 acquires lease -> generation 2
    lease2 = lease_mgr.acquire_lease("t_fence", "w2", ttl_seconds=30.0)
    assert lease2.generation == 2

    ledger = ActionLedger(store=store, lease_manager=lease_mgr)

    # Worker 1 attempts to record an action with generation 1 -> rejected with StaleWorkerError
    with pytest.raises(StaleWorkerError):
        ledger.start_action(
            action_id="act_stale",
            task_id="t_fence",
            action_type="navigate",
            parameters={"url": "https://example.com"},
            worker_id="w1",
            lease_generation=1,
        )

    # Worker 2 with generation 2 succeeds
    rec = ledger.start_action(
        action_id="act_fresh",
        task_id="t_fence",
        action_type="navigate",
        parameters={"url": "https://example.com"},
        worker_id="w2",
        lease_generation=2,
    )
    assert rec.status == ActionExecutionStatus.STARTED
    assert rec.worker_id == "w2"
