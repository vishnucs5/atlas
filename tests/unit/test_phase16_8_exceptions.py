"""ATLAS Phase 16.8 — Canonical Exception Architecture & Contract Verification.

Tests canonical exception identity, dual inheritance (IdempotencyError + SagaError),
cross-module import consistency, SagaCoordinator and Idempotency raising behavior,
circular-import resilience, and exception chaining.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import atlas_process
import pytest
from atlas_process import (
    IdempotencyError,
    ReconciliationRequiredError,
    SagaCoordinator,
    SagaError,
    SagaStep,
)
from atlas_process.idempotency import (
    IdempotencyError as ModIdempotencyError,
)
from atlas_process.idempotency import (
    ReconciliationRequiredError as ModIdemReconciliationError,
)
from atlas_process.idempotency import (
    SagaError as ModIdemSagaError,
)
from atlas_process.storage import SqliteProcessStorage
from atlas_process.transactions import (
    ReconciliationRequiredError as ModTransReconciliationError,
)
from atlas_process.transactions import (
    SagaError as ModTransSagaError,
)


def test_exception_identity_across_imports() -> None:
    """Requirement 16.8.1: Eliminate duplicate exception identities."""
    assert ReconciliationRequiredError is ModIdemReconciliationError
    assert ReconciliationRequiredError is ModTransReconciliationError
    assert ModIdemReconciliationError is ModTransReconciliationError

    assert SagaError is ModIdemSagaError
    assert SagaError is ModTransSagaError
    assert ModIdemSagaError is ModTransSagaError


def test_exception_inheritance_hierarchy() -> None:
    """Requirement 16.8.1: Dual inheritance preserving compatibility."""
    # Class hierarchy
    assert issubclass(ReconciliationRequiredError, IdempotencyError)
    assert issubclass(ReconciliationRequiredError, SagaError)
    assert issubclass(ReconciliationRequiredError, ModIdempotencyError)
    assert issubclass(ReconciliationRequiredError, ModTransSagaError)

    # Instance typing
    err = ReconciliationRequiredError("External wire transfer outcome unknown")
    assert isinstance(err, IdempotencyError)
    assert isinstance(err, SagaError)
    assert isinstance(err, Exception)


def test_saga_coordinator_raises_canonical_exception() -> None:
    """Requirement 16.8.1: SagaCoordinator raises canonical exception catchable by root import."""
    coordinator = SagaCoordinator()
    saga = coordinator.create_saga("pinst_banking_1")
    step = SagaStep(name="external_wire_transfer", is_idempotent=False)

    def timing_out_call(p: dict) -> dict:
        raise TimeoutError("Socket timeout waiting for payment gateway")

    # Verify catchable via root ReconciliationRequiredError
    with pytest.raises(ReconciliationRequiredError) as exc_info:
        coordinator.execute_step(saga.saga_id, step, timing_out_call)

    assert "RECONCILIATION_REQUIRED" in str(exc_info.value)
    assert isinstance(exc_info.value, SagaError)
    assert isinstance(exc_info.value, IdempotencyError)


def test_idempotency_storage_raises_canonical_exception(tmp_path: Path) -> None:
    """Requirement 16.8.1: Idempotency storage raises canonical exception on reconciliation status."""
    db_path = str(tmp_path / "test_idempotency.db")
    storage = SqliteProcessStorage(db_path=db_path)

    tenant_id = "tenant_audit_idem"
    idempotency_key = "key_reconcile_001"

    # Start operation and mark as unknown outcome
    storage.start_operation(
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        process_instance_id="inst_123",
        task_def_id="task_charge",
        operation_name="charge_card",
        request_fingerprint="fp_test_123",
        request_payload={"amount": 100},
    )
    storage.mark_operation_unknown_outcome(
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        reason="Host crashed during payment charge",
    )

    # Verify catchable by root ReconciliationRequiredError
    with pytest.raises(ReconciliationRequiredError) as exc_info:
        storage.start_operation(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            process_instance_id="inst_123",
            task_def_id="task_charge",
            operation_name="charge_card",
            request_fingerprint="fp_test_123",
            request_payload={"amount": 100},
        )

    assert "reconciliation required" in str(exc_info.value).lower()
    assert isinstance(exc_info.value, IdempotencyError)
    assert isinstance(exc_info.value, SagaError)
    assert isinstance(exc_info.value, IdempotencyError)
    assert isinstance(exc_info.value, SagaError)


def test_root_package_exports() -> None:
    """Requirement 16.8.1: Package-root exports point to identical object with unique __all__."""
    assert "ReconciliationRequiredError" in atlas_process.__all__
    assert "SagaError" in atlas_process.__all__
    assert atlas_process.ReconciliationRequiredError is ReconciliationRequiredError

    # Assert strict uniqueness in __all__
    assert len(atlas_process.__all__) == len(set(atlas_process.__all__))


@pytest.mark.parametrize(
    "import_code",
    [
        "import atlas_process; import atlas_process.idempotency; import atlas_process.transactions",
        "import atlas_process.transactions; import atlas_process.idempotency; import atlas_process",
        "import atlas_process.idempotency; import atlas_process.transactions; import atlas_process",
        "from atlas_process.transactions import ReconciliationRequiredError; from atlas_process.idempotency import ReconciliationRequiredError",
        "from atlas_process import ReconciliationRequiredError; from atlas_process.transactions import SagaCoordinator",
    ],
)
def test_circular_import_prevention(import_code: str) -> None:
    """Requirement 16.8.1: Prevent circular imports regardless of import order."""
    cmd = [sys.executable, "-c", import_code]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Import order failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"


def test_exception_chaining_and_diagnostics() -> None:
    """Requirement 16.8.1: Preserve exception chaining and diagnostics."""
    cause = ConnectionResetError("Remote server closed socket before ACK")
    try:
        try:
            raise cause
        except ConnectionResetError as e:
            raise ReconciliationRequiredError(
                "Task operation 'post_settlement' reached unknown outcome"
            ) from e
    except ReconciliationRequiredError as exc:
        assert exc.__cause__ is cause
        assert "post_settlement" in str(exc)
        assert isinstance(exc, SagaError)
        assert isinstance(exc, IdempotencyError)
