"""Full integration test suite verifying Phase 16.6 hardening against live PostgreSQL."""

import concurrent.futures
import pathlib
import tempfile

import pytest
from atlas_process.approvals import (
    ApprovalDecision,
    ApprovalError,
    HumanApprovalEngine,
)
from atlas_process.definitions import (
    ProcessDefinition,
    ProcessTaskDefinition,
    TaskType,
)
from atlas_process.engine import (
    ProcessExecutionEngine,
)
from atlas_process.idempotency import (
    DurableOperationIdempotencyManager,
    IdempotencyKeyReuseError,
    OperationStatus,
    ReconciliationRequiredError,
)
from atlas_process.state_machine import ProcessStatus, ProcessTaskStatus
from atlas_process.storage import PostgresProcessStorage
from embedded_postgres import PostgresServer


@pytest.fixture(scope="module")
def pg_server():
    """Start an actual native PostgreSQL server for Phase 16.6 hardening tests."""
    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="atlas_p16_6_pg_"))
    server = PostgresServer(temp_dir)
    server.ensure_pgdata_inited()
    server.ensure_postgres_running()
    yield server
    server.cleanup()


@pytest.fixture
def pg_storage(pg_server):
    """Provide an initialized PostgresProcessStorage with all migrations applied."""
    uri = pg_server.get_uri()
    storage = PostgresProcessStorage(uri)
    storage.initialize()
    yield storage
    storage.close()


def test_pg_16_6_01_migration_018_schema_verification(pg_storage):
    """Verify that Migration 018 schema objects and indexes exist in PostgreSQL."""
    pool = pg_storage._ensure_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Verify process_operation_idempotency table exists
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'process_operation_idempotency'
                """
            )
            assert cur.fetchone() is not None, "process_operation_idempotency table missing"

            # Verify unique conflict target index on process_worker_leases(task_instance_id, fencing_token)
            cur.execute(
                """
                SELECT indexname FROM pg_indexes
                WHERE tablename = 'process_worker_leases' AND indexname = 'idx_worker_leases_conflict_target'
                """
            )
            assert cur.fetchone() is not None, "idx_worker_leases_conflict_target index missing"

            # Verify idempotency table columns
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'process_operation_idempotency'
                ORDER BY ordinal_position
                """
            )
            cols = {row[0] for row in cur.fetchall()}
            assert "tenant_id" in cols
            assert "idempotency_key" in cols
            assert "process_instance_id" in cols
            assert "task_def_id" in cols
            assert "operation_name" in cols
            assert "request_fingerprint" in cols
            assert "status" in cols
            assert "request_payload" in cols
            assert "response_payload" in cols


def test_pg_16_6_02_approval_concurrency_row_locking(pg_storage):
    """FINDING-16.5-01: Verify multi-node approval consistency with PostgreSQL row locks."""
    engine_proc = ProcessExecutionEngine(storage=pg_storage)
    p_def = ProcessDefinition(
        definition_id="def_pg_appr_concurrent",
        name="PG Appr Concurrent",
        version="1.0.0",
        tenant_id="tenant_finance",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="task_payout",
                name="Execute Payout",
                task_type=TaskType.HUMAN_APPROVAL,
            )
        ],
    )
    engine_proc.register_definition(p_def)
    instance = engine_proc.start_process(p_def.definition_id, tenant_id="tenant_finance")

    # Node 1 and Node 2 represent two independent application instances
    node_1 = HumanApprovalEngine(storage=pg_storage)
    node_2 = HumanApprovalEngine(storage=pg_storage)

    req = node_1.create_approval_request(
        process_instance_id=instance.instance_id,
        task_def_id="task_payout",
        action_name="execute_wire",
        target_resource="treasury",
        parameters={"amount": 500000},
        requesting_identity="finance_officer",
        allowed_approver_ids=["approver_alice", "approver_bob", "approver_carol"],
        required_approvals=2,
        tenant_id="tenant_finance",
    )
    appr_id = req.approval_id

    # Node 2 initially checks approval
    view_2 = node_2.get_approval(appr_id)
    assert view_2 is not None
    assert len(view_2.decisions) == 0

    # Approver Alice votes on Node 1
    voted_1 = node_1.decide(appr_id, "approver_alice", ApprovalDecision.APPROVED)
    assert voted_1.status == ApprovalDecision.PENDING
    assert len(voted_1.decisions) == 1

    # Duplicate vote on Node 2 by Alice while still PENDING is rejected
    with pytest.raises(ApprovalError, match="already submitted a decision"):
        node_2.decide(appr_id, "approver_alice", ApprovalDecision.APPROVED)

    # Approver Bob votes on Node 2
    # Node 2 must fetch authoritative state via SELECT ... FOR UPDATE, see Alice's vote,
    # evaluate 2 >= 2 approvals, and transition atomically to APPROVED
    voted_2 = node_2.decide(appr_id, "approver_bob", ApprovalDecision.APPROVED)
    assert voted_2.status == ApprovalDecision.APPROVED
    assert len(voted_2.decisions) == 2

    # Node 1 gets approval again: must see APPROVED with 2 decisions
    view_1_after = node_1.get_approval(appr_id)
    assert view_1_after.status == ApprovalDecision.APPROVED
    assert len(view_1_after.decisions) == 2

    # Vote on already resolved approval is rejected
    with pytest.raises(ApprovalError, match="has already been resolved"):
        node_2.decide(appr_id, "approver_carol", ApprovalDecision.APPROVED)


def test_pg_16_6_03_concurrent_initial_worker_leases_in_postgres(pg_storage):
    """FINDING-16.5-03: Verify atomic initial lease race across 10 concurrent PostgreSQL clients."""
    engine_proc = ProcessExecutionEngine(storage=pg_storage)
    p_def = ProcessDefinition(
        definition_id="def_pg_race_lease",
        name="PG Race Lease Def",
        version="1.0.0",
        tenant_id="tenant_race",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="step_race",
                name="Concurrent Lease Step",
                task_type=TaskType.AGENT_EXECUTION,
            )
        ],
    )
    engine_proc.register_definition(p_def)
    instance = engine_proc.start_process(p_def.definition_id, tenant_id="tenant_race")
    task_id = instance.task_instances["step_race"].task_instance_id
    proc_id = instance.instance_id
    num_workers = 10

    results = []

    def worker_acquire(worker_idx: int):
        worker_id = f"pg_worker_{worker_idx}"
        l_tok, f_tok = pg_storage.acquire_lease(
            task_instance_id=task_id,
            process_instance_id=proc_id,
            worker_id=worker_id,
            lease_duration_seconds=60.0,
        )
        return worker_id, l_tok, f_tok

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_acquire, i) for i in range(num_workers)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    assert len(results) == num_workers
    fencing_tokens = [r[2] for r in results]
    lease_tokens = [r[1] for r in results]

    # Every single concurrent worker received a distinct fencing token
    assert len(set(fencing_tokens)) == num_workers
    # Fencing tokens must form the exact sequence 1..10
    assert sorted(fencing_tokens) == list(range(1, num_workers + 1))
    # Every worker received a unique lease token
    assert len(set(lease_tokens)) == num_workers

    # Highest fencing token is active and valid
    max_fencing = max(fencing_tokens)
    winner = next(r for r in results if r[2] == max_fencing)
    assert pg_storage.verify_lease(task_id, winner[1], max_fencing) is True

    # Any earlier worker is rejected
    for r in results:
        if r[2] < max_fencing:
            assert pg_storage.verify_lease(task_id, r[1], r[2]) is False


def test_pg_16_6_04_durable_idempotency_and_crash_recovery_in_postgres(pg_storage):
    """FINDING-16.5-02: Verify durable task idempotency and crash recovery in PostgreSQL."""
    engine = ProcessExecutionEngine(storage=pg_storage)
    tenant_id = "tenant_pg_corp"
    key = "tx_pg_101"
    payload = {"account_id": "acc_pg_999", "amount": 25000}

    # Setup definition and start process so instance and tasks exist in PostgreSQL
    definition = ProcessDefinition(
        definition_id="def_pg_payout",
        name="Postgres Payout Process",
        version="1.0.0",
        tenant_id=tenant_id,
        tasks=[
            ProcessTaskDefinition(
                task_def_id="task_payout",
                name="Bank Wire Task",
                task_type=TaskType.AGENT_EXECUTION,
                is_idempotent=False,
            )
        ],
    )
    engine.register_definition(definition)
    instance = engine.start_process(definition.definition_id, tenant_id=tenant_id)
    proc_id = instance.instance_id

    # Mark task as RUNNING
    instance.task_instances["task_payout"].status = ProcessTaskStatus.RUNNING
    pg_storage.save_instance(instance)

    idemp_mgr = DurableOperationIdempotencyManager(pg_storage)

    # 1. Start operation
    status, cached = idemp_mgr.start_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        process_instance_id=proc_id,
        task_def_id="task_payout",
        operation_name="bank_wire",
        request_payload=payload,
    )
    assert status == OperationStatus.IN_PROGRESS
    assert cached is None

    # 2. Conflicting key reuse detection
    with pytest.raises(IdempotencyKeyReuseError):
        idemp_mgr.start_operation(
            tenant_id=tenant_id,
            idempotency_key=key,
            process_instance_id=proc_id,
            task_def_id="task_payout",
            operation_name="bank_wire",
            request_payload={"account_id": "acc_pg_999", "amount": 999999},  # Differing payload!
        )

    # 3. Simulate engine restart crash recovery:
    # A new engine instance restarts from DB
    engine_restarted = ProcessExecutionEngine(storage=pg_storage)
    recovered_count = engine_restarted.recover_after_restart()
    assert recovered_count == 0  # Interrupted task suspended rather than reset to READY!

    # Verify task was SUSPENDED and operation marked UNKNOWN_OUTCOME
    reloaded_inst = pg_storage.get_instance(proc_id)
    assert reloaded_inst is not None
    assert reloaded_inst.status == ProcessStatus.SUSPENDED
    assert reloaded_inst.task_instances["task_payout"].status == ProcessTaskStatus.SUSPENDED

    # Operation must now be UNKNOWN_OUTCOME
    op_record = pg_storage.get_operation(tenant_id, key)
    assert op_record is not None
    assert op_record.status == OperationStatus.UNKNOWN_OUTCOME

    # Immediate retry attempt raises ReconciliationRequiredError
    with pytest.raises(ReconciliationRequiredError):
        idemp_mgr.start_operation(
            tenant_id=tenant_id,
            idempotency_key=key,
            process_instance_id=proc_id,
            task_def_id="task_payout",
            operation_name="bank_wire",
            request_payload=payload,
        )

    # Manual reconciliation settles the operation as SUCCEEDED
    idemp_mgr.reconcile_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        resolution_status=OperationStatus.SUCCEEDED,
        resolved_by="lead_auditor",
        notes="Bank confirmed payment settled via Swift MT103",
        response_payload={"wire_ref": "SWIFT_SETTLED_999"},
    )

    # Subsequent invocation gets cached response cleanly!
    status2, cached2 = idemp_mgr.start_operation(
        tenant_id=tenant_id,
        idempotency_key=key,
        process_instance_id=proc_id,
        task_def_id="task_payout",
        operation_name="bank_wire",
        request_payload=payload,
    )
    assert status2 == OperationStatus.SUCCEEDED
    assert cached2 == {"wire_ref": "SWIFT_SETTLED_999"}
