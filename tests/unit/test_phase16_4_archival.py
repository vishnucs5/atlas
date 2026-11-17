"""Unit tests for Phase 16.4 Reconciliation Retention & Archival Guardrails."""

import time

import pytest
from atlas_process.engine import ProcessInstance, ProcessStatus
from atlas_process.storage import (
    InMemoryProcessStorage,
    SqliteProcessStorage,
)
from atlas_process.transactions import (
    SagaStatus,
    SagaTransaction,
)


@pytest.fixture(params=["memory", "sqlite"])
def storage(request, tmp_path):
    if request.param == "memory":
        return InMemoryProcessStorage()
    db_path = str(tmp_path / "test_archival.db")
    s = SqliteProcessStorage(db_path)
    s.initialize()
    return s


def test_archival_retention_with_pending_reconciliations(storage):
    """Verify that instances with pending reconciliation records are never deleted during archival."""
    now = time.time()
    old_time = now - 1000.0

    # Instance A: Completed with NO pending reconciliations (eligible for archival)
    inst_a = ProcessInstance(
        instance_id="inst_clean_01",
        definition_id="def_proc_a",
        definition_version="1.0.0",
        definition_hash="hash_def_a",
        tenant_id="tenant_archival",
        status=ProcessStatus.COMPLETED,
        started_at=old_time,
        completed_at=old_time,
    )
    storage.save_instance(inst_a)

    # Instance B: Completed BUT has a PENDING reconciliation record (must be retained)
    inst_b = ProcessInstance(
        instance_id="inst_pending_reconcile_02",
        definition_id="def_proc_b",
        definition_version="1.0.0",
        definition_hash="hash_def_b",
        tenant_id="tenant_archival",
        status=ProcessStatus.COMPLETED,
        started_at=old_time,
        completed_at=old_time,
    )
    storage.save_instance(inst_b)

    # Associate saga with instance B
    saga_b = SagaTransaction(
        saga_id="saga_b_99",
        process_instance_id="inst_pending_reconcile_02",
        status=SagaStatus.ACTIVE,
    )
    storage.save_saga(saga_b)

    # Record pending reconciliation linked to saga B
    rec_id = storage.record_reconciliation(
        saga_id="saga_b_99",
        step_id="step_charge_failure",
        reason="Bank gateway timeout",
    )

    # Run archival for all instances completed before now
    archived_count = storage.archive_completed_instances(cutoff_timestamp=now)

    # Only instance A should be deleted; instance B must be preserved!
    assert archived_count == 1
    assert storage.get_instance("inst_clean_01") is None
    assert storage.get_instance("inst_pending_reconcile_02") is not None

    # Now resolve the reconciliation record
    storage.resolve_reconciliation(
        record_id=rec_id,
        resolved_by="admin_ops",
        notes="Reconciliation completed offline",
    )

    # Second archival run now cleanly archives instance B
    archived_count2 = storage.archive_completed_instances(cutoff_timestamp=now)
    assert archived_count2 == 1
    assert storage.get_instance("inst_pending_reconcile_02") is None
