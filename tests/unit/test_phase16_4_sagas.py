"""Unit tests for Phase 16.4 Saga Durability, Crash-Recovery & Reconciliation."""

import pytest
from atlas_process.storage import (
    InMemoryProcessStorage,
    SqliteProcessStorage,
)
from atlas_process.transactions import (
    SagaCoordinator,
    SagaStatus,
    SagaStep,
    SagaStepStatus,
)


@pytest.fixture(params=["memory", "sqlite"])
def storage(request, tmp_path):
    if request.param == "memory":
        return InMemoryProcessStorage()
    db_path = str(tmp_path / "test_sagas.db")
    s = SqliteProcessStorage(db_path)
    s.initialize()
    return s


def test_saga_step_persistence_and_transitions(storage):
    """Verify that saga creation, step execution, and completion are persisted durably."""
    coord = SagaCoordinator(storage=storage)
    saga = coord.create_saga(
        process_instance_id="proc_inst_saga_01",
        metadata={"tenant_id": "tenant_finance", "description": "Payment Processing Saga"},
    )
    assert saga.status == SagaStatus.ACTIVE

    # Verify persisted in storage
    saved = storage.get_saga(saga.saga_id)
    assert saved is not None
    assert saved.status == SagaStatus.ACTIVE

    # Execute step 1
    step1 = SagaStep(name="step_charge_card")
    coord.execute_step(
        saga_id=saga.saga_id,
        step=step1,
        action_fn=lambda p: {"charge_id": "ch_123"},
        compensation_payload={"charge_id": "ch_123"},
    )
    persisted_saga = storage.get_saga(saga.saga_id)
    assert persisted_saga is not None
    assert len(persisted_saga.steps) == 1
    assert persisted_saga.steps[0].status == SagaStepStatus.COMPLETED

    # Execute step 2
    step2 = SagaStep(name="step_allocate_inventory")
    coord.execute_step(
        saga_id=saga.saga_id,
        step=step2,
        action_fn=lambda p: {"allocated": True},
        compensation_payload={"sku": "ITEM_99"},
    )
    persisted_saga2 = storage.get_saga(saga.saga_id)
    assert persisted_saga2 is not None
    assert len(persisted_saga2.steps) == 2
    assert persisted_saga2.steps[1].status == SagaStepStatus.COMPLETED


def test_saga_crash_recovery_across_instances(storage):
    """Verify a new SagaCoordinator instance can restore state from storage and compensate."""
    coord1 = SagaCoordinator(storage=storage)
    saga = coord1.create_saga("proc_inst_recover", metadata={"tenant_id": "tenant_ops"})

    step1 = SagaStep(name="s1_reserve")
    coord1.execute_step(
        saga.saga_id,
        step1,
        action_fn=lambda p: {"reserved": True},
        compensation_payload={"res_id": "r1"},
    )

    # Simulate crash before step 2 execution:
    # A fresh coordinator instance loads the saga from storage
    coord2 = SagaCoordinator(storage=storage)
    recovered = coord2.recover_saga(saga.saga_id)
    assert recovered is not None
    assert recovered.saga_id == saga.saga_id
    assert len(recovered.steps) == 1
    assert recovered.steps[0].status == SagaStepStatus.COMPLETED

    # Register compensation handler on recovered coordinator
    compensated_called = []
    coord2.register_compensation_handler(
        "s1_reserve",
        handler=lambda p: compensated_called.append(p) or True,
    )

    # Execute compensation on recovered coordinator
    res = coord2.compensate_saga(saga.saga_id)
    assert res is True
    assert len(compensated_called) == 1
    assert recovered.status == SagaStatus.COMPENSATED

    # Storage verifies terminal compensated state
    persisted = storage.get_saga(saga.saga_id)
    assert persisted is not None
    assert persisted.status == SagaStatus.COMPENSATED


def test_saga_compensation_failure_creates_reconciliation_record(storage):
    """Verify compensation failure creates durable record and manual resolve clears it."""
    coord = SagaCoordinator(storage=storage)
    saga = coord.create_saga("proc_inst_reconcile", metadata={"tenant_id": "tenant_sec"})

    step = SagaStep(name="transfer_funds")
    coord.execute_step(
        saga.saga_id,
        step,
        action_fn=lambda p: {"wire_id": "WIRE_999"},
        compensation_payload={"amount": 50000},
    )

    def failing_compensation(p):
        raise ConnectionResetError("Remote bank gateway down")

    coord.register_compensation_handler("transfer_funds", handler=failing_compensation)

    # Compensation should fail and return False
    res = coord.compensate_saga(saga.saga_id)
    assert res is False

    # Saga must have failed step and PARTIAL_FAILURE status
    assert saga.status == SagaStatus.PARTIAL_FAILURE
    persisted_saga = storage.get_saga(saga.saga_id)
    assert persisted_saga is not None
    failed_step = next(s for s in persisted_saga.steps if s.name == "transfer_funds")
    assert failed_step.status == SagaStepStatus.COMPENSATION_FAILED

    # A durable reconciliation record must exist in storage
    records = storage.list_reconciliations(status="PENDING")
    assert len(records) >= 1
    target = next((r for r in records if r["saga_id"] == saga.saga_id), None)
    assert target is not None
    assert target["step_id"] == failed_step.step_id
    assert "Remote bank gateway down" in target["notes"]

    # Manual resolution updates reconciliation record and saga
    coord.manual_resolve(
        saga.saga_id,
        resolved_by="sec_admin_01",
        notes="Manually refunded via banking portal",
    )

    resolved_records = storage.list_reconciliations(status="RESOLVED")
    assert any(r["saga_id"] == saga.saga_id for r in resolved_records)
    pending_records = storage.list_reconciliations(status="PENDING")
    assert not any(r["saga_id"] == saga.saga_id for r in pending_records)
