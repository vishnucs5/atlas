"""Unit tests for Phase 16.6 Durable Task Idempotency & Irreversible Operation Safety."""

import pathlib
import tempfile

import pytest
from atlas_process.definitions import (
    ProcessDefinition,
    ProcessTaskDefinition,
    TaskType,
)
from atlas_process.engine import (
    ProcessExecutionEngine,
    ProcessInstance,
    ProcessTaskInstance,
)
from atlas_process.idempotency import (
    ConcurrentOperationInProgressError,
    DurableOperationIdempotencyManager,
    IdempotencyKeyReuseError,
    OperationPreviouslyFailedError,
    OperationStatus,
    ReconciliationRequiredError,
    compute_request_fingerprint,
)
from atlas_process.state_machine import ProcessStatus, ProcessTaskStatus
from atlas_process.storage import InMemoryProcessStorage, SqliteProcessStorage


@pytest.fixture(params=["in_memory", "sqlite"])
def storage(request):
    if request.param == "in_memory":
        storage = InMemoryProcessStorage()
        storage.initialize()
        yield storage
    else:
        with tempfile.TemporaryDirectory() as td:
            db_path = pathlib.Path(td) / "test_idempotency.db"
            storage = SqliteProcessStorage(db_path)
            storage.initialize()
            yield storage


def test_request_fingerprint_deterministic():
    payload_a = {"amount": 100, "currency": "USD", "recipient": "alice"}
    payload_b = {"recipient": "alice", "amount": 100, "currency": "USD"}
    payload_c = {"amount": 200, "currency": "USD", "recipient": "alice"}

    fp_a = compute_request_fingerprint(payload_a)
    fp_b = compute_request_fingerprint(payload_b)
    fp_c = compute_request_fingerprint(payload_c)

    assert fp_a == fp_b
    assert fp_a != fp_c


def test_idempotency_lifecycle_success(storage):
    mgr = DurableOperationIdempotencyManager(storage)
    tenant_id = "tenant_1"
    key = "tx_001"
    payload = {"account": "acc_123", "amount": 500}

    # 1. Start operation -> CREATED / IN_PROGRESS
    status, cached = mgr.start_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        process_instance_id="inst_1",
        task_def_id="task_payout",
        operation_name="wire_transfer",
        request_payload=payload,
    )
    assert status == OperationStatus.IN_PROGRESS
    assert cached is None

    # 2. Complete operation
    response = {"transaction_id": "tx_bank_999", "status": "CONFIRMED"}
    mgr.complete_operation(tenant_id=tenant_id, idempotency_key=key, response_payload=response)

    # 3. Subsequent call returns cached SUCCEEDED result without re-executing
    status2, cached2 = mgr.start_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        process_instance_id="inst_1",
        task_def_id="task_payout",
        operation_name="wire_transfer",
        request_payload=payload,
    )
    assert status2 == OperationStatus.SUCCEEDED
    assert cached2 == response


def test_concurrent_in_progress_rejection(storage):
    mgr = DurableOperationIdempotencyManager(storage)
    tenant_id = "tenant_1"
    key = "tx_002"
    payload = {"account": "acc_456", "amount": 1000}

    # First worker starts operation
    status, _ = mgr.start_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        process_instance_id="inst_2",
        task_def_id="task_payout",
        operation_name="wire_transfer",
        request_payload=payload,
    )
    assert status == OperationStatus.IN_PROGRESS

    # Second worker attempts same operation concurrently -> ConcurrentOperationInProgressError
    with pytest.raises(ConcurrentOperationInProgressError):
        mgr.start_operation(
            tenant_id=tenant_id,
            idempotency_key=key,
            process_instance_id="inst_2",
            task_def_id="task_payout",
            operation_name="wire_transfer",
            request_payload=payload,
        )


def test_key_reuse_differing_fingerprint_rejected(storage):
    mgr = DurableOperationIdempotencyManager(storage)
    tenant_id = "tenant_1"
    key = "tx_003"
    payload_a = {"amount": 100}
    payload_b = {"amount": 200}  # Conflicting payload!

    mgr.start_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        process_instance_id="inst_3",
        task_def_id="task_payout",
        operation_name="wire_transfer",
        request_payload=payload_a,
    )

    with pytest.raises(IdempotencyKeyReuseError):
        mgr.start_operation(
            tenant_id=tenant_id,
            idempotency_key=key,
            process_instance_id="inst_3",
            task_def_id="task_payout",
            operation_name="wire_transfer",
            request_payload=payload_b,
        )


def test_retryable_failure_permits_retry(storage):
    mgr = DurableOperationIdempotencyManager(storage)
    tenant_id = "tenant_1"
    key = "tx_004"
    payload = {"amount": 50}

    # Worker starts and encounters network glitch
    mgr.start_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        process_instance_id="inst_4",
        task_def_id="task_api",
        operation_name="call_gateway",
        request_payload=payload,
    )
    mgr.fail_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        error_message="Gateway timeout 504",
        retryable=True,
    )

    # Retry should succeed and transition back to IN_PROGRESS
    status, _ = mgr.start_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        process_instance_id="inst_4",
        task_def_id="task_api",
        operation_name="call_gateway",
        request_payload=payload,
    )
    assert status == OperationStatus.IN_PROGRESS


def test_final_failure_blocks_retry(storage):
    mgr = DurableOperationIdempotencyManager(storage)
    tenant_id = "tenant_1"
    key = "tx_005"
    payload = {"amount": 50}

    mgr.start_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        process_instance_id="inst_5",
        task_def_id="task_api",
        operation_name="call_gateway",
        request_payload=payload,
    )
    mgr.fail_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        error_message="Account invalid 400",
        retryable=False,
    )

    # Attempted retry must be blocked
    with pytest.raises(OperationPreviouslyFailedError):
        mgr.start_operation(
            tenant_id=tenant_id,
            idempotency_key=key,
            process_instance_id="inst_5",
            task_def_id="task_api",
            operation_name="call_gateway",
            request_payload=payload,
        )


def test_unknown_outcome_and_reconciliation(storage):
    mgr = DurableOperationIdempotencyManager(storage)
    tenant_id = "tenant_1"
    key = "tx_006"
    payload = {"account": "treasury_99", "amount": 1000000}

    # Start operation
    mgr.start_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        process_instance_id="inst_6",
        task_def_id="task_large_transfer",
        operation_name="wire_transfer",
        request_payload=payload,
    )

    # Host crash / socket dropped mid-flight
    mgr.mark_unknown_outcome(
        tenant_id=tenant_id,
        idempotency_key=key,
        reason="TCP connection dropped during commit phase",
    )

    # Retrying immediately must raise ReconciliationRequiredError
    with pytest.raises(ReconciliationRequiredError):
        mgr.start_operation(
            tenant_id=tenant_id,
            idempotency_key=key,
            process_instance_id="inst_6",
            task_def_id="task_large_transfer",
            operation_name="wire_transfer",
            request_payload=payload,
        )

    # Manual reconciliation resolves that bank indeed processed it
    mgr.reconcile_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        resolution_status=OperationStatus.SUCCEEDED,
        resolved_by="auditor_jane",
        notes="Bank statement confirmed wire settled at 14:02 UTC",
        response_payload={"bank_ref": "SETTLED_001"},
    )

    # Subsequent start_operation sees it as successfully completed!
    status, cached = mgr.start_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        process_instance_id="inst_6",
        task_def_id="task_large_transfer",
        operation_name="wire_transfer",
        request_payload=payload,
    )
    assert status == OperationStatus.SUCCEEDED
    assert cached == {"bank_ref": "SETTLED_001"}


def test_restart_recovery_suspends_interrupted_operation(storage):
    """FINDING-16.5-02 regression test:
    Verify that an engine restart marks interrupted operations UNKNOWN_OUTCOME
    and suspends the task rather than resetting it to READY for blind duplicate replay.
    """
    engine = ProcessExecutionEngine(storage=storage)

    # Setup definition
    definition = ProcessDefinition(
        definition_id="def_payout",
        name="Payout Workflow",
        version="1.0.0",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="task_pay",
                name="Execute Payout",
                task_type=TaskType.AGENT_EXECUTION,
                is_idempotent=False,  # Critical: non-idempotent operation!
            )
        ],
    )
    storage.save_definition(definition)

    # Create instance and task
    inst = ProcessInstance(
        instance_id="inst_payout_1",
        definition_id="def_payout",
        definition_version="1.0.0",
        definition_hash=definition.definition_hash,
        status=ProcessStatus.RUNNING,
        tenant_id="tenant_finance",
    )
    task_inst = ProcessTaskInstance(
        task_instance_id="task_inst_pay_1",
        process_instance_id="inst_payout_1",
        task_def_id="task_pay",
        name="Execute Payout",
        task_type=TaskType.AGENT_EXECUTION,
        status=ProcessTaskStatus.RUNNING,
    )
    inst.task_instances["task_pay"] = task_inst
    storage.save_instance(inst)

    # Operation started in storage before simulated crash
    storage.start_operation(
        tenant_id="tenant_finance",
        idempotency_key="pay_key_123",
        process_instance_id="inst_payout_1",
        task_def_id="task_pay",
        operation_name="charge_card",
        request_fingerprint="abc123hash",
        request_payload={"amount": 9900},
    )

    # Host crashes and restarts!
    recovered_count = engine.recover_after_restart()
    # Interrupted task suspended due to ambiguous in-flight operation
    assert recovered_count == 0

    # Inspect recovered task state in storage
    reloaded_inst = storage.get_instance("inst_payout_1")
    assert reloaded_inst is not None
    recovered_task = reloaded_inst.task_instances["task_pay"]

    # Must be SUSPENDED with unknown outcome flag, NOT reset to READY!
    assert recovered_task.status == ProcessTaskStatus.SUSPENDED
    assert "Reconciliation required" in str(recovered_task.error)

    # Check operation record status in storage
    op = storage.get_operation("tenant_finance", "pay_key_123")
    assert op is not None
    assert op.status == OperationStatus.UNKNOWN_OUTCOME
