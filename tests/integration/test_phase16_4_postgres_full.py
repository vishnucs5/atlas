"""Full integration test suite verifying Phase 16.4 critical remediations against a live PostgreSQL instance."""

import pathlib
import tempfile
import time

import pytest
from atlas_process.approvals import (
    ApprovalDecision,
    HumanApprovalEngine,
)
from atlas_process.definitions import (
    ProcessDefinition,
    ProcessTaskDefinition,
    TaskType,
)
from atlas_process.engine import (
    ProcessExecutionEngine,
    ProcessInstance,
    ProcessStatus,
    ProcessTaskStatus,
    StaleWorkerFencingError,
)
from atlas_process.storage import PostgresProcessStorage
from atlas_process.transactions import (
    SagaCoordinator,
    SagaStatus,
    SagaStep,
    SagaStepStatus,
    SagaTransaction,
)
from embedded_postgres import PostgresServer


@pytest.fixture(scope="module")
def pg_server():
    """Start an actual native PostgreSQL server for Phase 16.4 full verification."""
    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="atlas_p16_4_pg_"))
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


def test_pg_16_4_01_migrations_and_schema_integrity(pg_storage):
    """Verify that all migrations including 017_process_lease_integrity are applied cleanly."""
    pool = pg_storage._ensure_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Verify columns on process_worker_leases
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'process_worker_leases' AND column_name = 'lease_token'
                """
            )
            assert cur.fetchone() is not None, (
                "lease_token column missing from process_worker_leases"
            )

            # Verify process_approval_decisions table exists
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'process_approval_decisions'
                """
            )
            assert cur.fetchone() is not None, "process_approval_decisions table missing"

            # Verify process_reconciliation_records table exists
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'process_reconciliation_records'
                """
            )
            assert cur.fetchone() is not None, "process_reconciliation_records table missing"

            # Verify process_event_inbox table exists
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'process_event_inbox'
                """
            )
            assert cur.fetchone() is not None, "process_event_inbox table missing"


def test_pg_16_4_02_task_lease_and_completion_lifecycle(pg_storage):
    """Verify worker task lease acquisition, verification, and deterministic completion in PostgreSQL."""
    engine = ProcessExecutionEngine(storage=pg_storage)

    task_def = ProcessTaskDefinition(
        task_def_id="step_pg_lease",
        name="Postgres Lease Step",
        task_type=TaskType.AGENT_EXECUTION,
        dependencies=[],
    )
    p_def = ProcessDefinition(
        definition_id="def_pg_lease_test",
        name="PG Lease Process",
        version="1.0.0",
        tenant_id="tenant_pg",
        tasks=[task_def],
    )
    engine.register_definition(p_def)

    instance = engine.start_process(p_def.definition_id, tenant_id="tenant_pg")
    task_inst_id = instance.task_instances["step_pg_lease"].task_instance_id

    # Worker acquires lease
    lease_token, fencing_token = engine.acquire_task_lease(
        instance.instance_id,
        "step_pg_lease",
        worker_id="worker_pg_01",
        lease_duration_seconds=30.0,
    )
    assert lease_token is not None
    assert fencing_token == 1

    # Deterministic verification in database using task_instance_id
    assert (
        pg_storage.verify_lease(
            task_inst_id,
            lease_token,
            fencing_token,
        )
        is True
    )

    # Complete task with matching lease token and fencing token
    engine.complete_task(
        instance.instance_id,
        "step_pg_lease",
        outputs={"db_processed": True},
        fencing_token=fencing_token,
    )

    completed_inst = engine.get_instance(instance.instance_id)
    assert completed_inst is not None
    t_inst = completed_inst.task_instances["step_pg_lease"]
    assert t_inst.status == ProcessTaskStatus.COMPLETED
    assert t_inst.outputs == {"db_processed": True}
    assert completed_inst.status == ProcessStatus.COMPLETED


def test_pg_16_4_03_fencing_token_staleness_rejection(pg_storage):
    """Verify that a stale worker with an expired fencing token is rejected on completion in PostgreSQL."""
    engine = ProcessExecutionEngine(storage=pg_storage)

    task_def = ProcessTaskDefinition(
        task_def_id="step_fencing",
        name="Fencing Step",
        task_type=TaskType.AGENT_EXECUTION,
        dependencies=[],
    )
    p_def = ProcessDefinition(
        definition_id="def_pg_fencing_test",
        name="PG Fencing Process",
        version="1.0.0",
        tenant_id="tenant_pg",
        tasks=[task_def],
    )
    engine.register_definition(p_def)

    instance = engine.start_process(p_def.definition_id, tenant_id="tenant_pg")

    # Worker 1 acquires short lease
    token1, fence1 = engine.acquire_task_lease(
        instance.instance_id,
        "step_fencing",
        worker_id="worker_pg_01",
        lease_duration_seconds=0.5,
    )
    assert fence1 == 1

    # Wait for expiry
    time.sleep(0.55)

    # Worker 2 acquires new lease with higher fencing token
    token2, fence2 = engine.acquire_task_lease(
        instance.instance_id,
        "step_fencing",
        worker_id="worker_pg_02",
        lease_duration_seconds=30.0,
    )
    assert fence2 == 2
    assert token2 != token1

    # Stale Worker 1 attempts completion with token1 and fence1 -> REJECTED
    with pytest.raises(StaleWorkerFencingError):
        engine.complete_task(
            instance.instance_id,
            "step_fencing",
            outputs={"bad": True},
            fencing_token=fence1,
        )

    # Active Worker 2 completes task -> ACCEPTED
    engine.complete_task(
        instance.instance_id,
        "step_fencing",
        outputs={"good": True},
        fencing_token=fence2,
    )
    res = engine.get_instance(instance.instance_id)
    assert res is not None
    assert res.task_instances["step_fencing"].status == ProcessTaskStatus.COMPLETED


def test_pg_16_4_04_saga_persistence_and_recovery(pg_storage):
    """Verify durable saga persistence and multi-instance crash recovery on PostgreSQL."""
    engine = ProcessExecutionEngine(storage=pg_storage)
    p_def = ProcessDefinition(
        definition_id="def_pg_saga",
        name="PG Saga Def",
        version="1.0.0",
        tenant_id="tenant_pg",
        tasks=[],
    )
    engine.register_definition(p_def)
    instance = engine.start_process(p_def.definition_id, tenant_id="tenant_pg")

    coord1 = SagaCoordinator(storage=pg_storage)
    saga = coord1.create_saga(instance.instance_id, metadata={"tenant_id": "tenant_pg"})

    step = SagaStep(name="pg_charge_card")
    coord1.execute_step(
        saga.saga_id,
        step,
        action_fn=lambda p: {"charge_id": "ch_pg_101"},
        compensation_payload={"charge_id": "ch_pg_101"},
    )

    # SIMULATE CRASH: New coordinator loads saga from live PostgreSQL
    coord2 = SagaCoordinator(storage=pg_storage)
    recovered = coord2.recover_saga(saga.saga_id)
    assert recovered is not None
    assert recovered.saga_id == saga.saga_id
    assert len(recovered.steps) == 1
    assert recovered.steps[0].status == SagaStepStatus.COMPLETED

    # Execute compensation
    compensated_called = []
    coord2.register_compensation_handler(
        "pg_charge_card",
        handler=lambda p: compensated_called.append(p) or True,
    )
    res = coord2.compensate_saga(saga.saga_id)
    assert res is True
    assert len(compensated_called) == 1
    assert recovered.status == SagaStatus.COMPENSATED

    # Verify PostgreSQL row matches COMPENSATED
    persisted = pg_storage.get_saga(saga.saga_id)
    assert persisted is not None
    assert persisted.status == SagaStatus.COMPENSATED


def test_pg_16_4_05_approval_quorum_persistence(pg_storage):
    """Verify human approval voting and quorum decisions persist across restarts in PostgreSQL."""
    engine_proc = ProcessExecutionEngine(storage=pg_storage)
    p_def = ProcessDefinition(
        definition_id="def_pg_approval",
        name="PG Appr Def",
        version="1.0.0",
        tenant_id="tenant_pg",
        tasks=[],
    )
    engine_proc.register_definition(p_def)
    instance = engine_proc.start_process(p_def.definition_id, tenant_id="tenant_pg")

    engine1 = HumanApprovalEngine(storage=pg_storage)
    req = engine1.create_approval_request(
        process_instance_id=instance.instance_id,
        task_def_id="task_payout",
        action_name="release_funds",
        target_resource="treasury_vault",
        parameters={"amount_usd": 250000},
        requesting_identity="payment_worker",
        allowed_approver_ids=["approver_alice", "approver_bob"],
        required_approvals=2,
        tenant_id="tenant_pg",
    )
    assert req.status == ApprovalDecision.PENDING

    # Approver Alice votes
    engine1.decide(
        req.approval_id, "approver_alice", ApprovalDecision.APPROVED, comments="Alice OK"
    )

    # SIMULATE RESTART: Fresh engine instance
    engine2 = HumanApprovalEngine(storage=pg_storage)
    recovered = engine2.get_approval(req.approval_id)
    assert recovered is not None
    assert recovered.status == ApprovalDecision.PENDING
    assert len(recovered.decisions) == 1
    assert recovered.decisions[0].approver_id == "approver_alice"

    # Approver Bob votes on recovered engine -> Quorum reached
    final_req = engine2.decide(
        req.approval_id, "approver_bob", ApprovalDecision.APPROVED, comments="Bob OK"
    )
    assert final_req.status == ApprovalDecision.APPROVED
    assert len(final_req.decisions) == 2

    # Storage direct check
    saved = pg_storage.get_approval(req.approval_id)
    assert saved is not None
    assert saved.status == ApprovalDecision.APPROVED
    assert len(saved.decisions) == 2


def test_pg_16_4_06_archival_retention_and_event_inbox(pg_storage):
    """Verify archival preserves instances with pending reconciliations and inbox dedupes in PostgreSQL."""
    engine = ProcessExecutionEngine(storage=pg_storage)
    now = time.time()
    old_time = now - 1000.0

    p_def = ProcessDefinition(
        definition_id="def_pg_archival",
        name="Archival Def",
        version="1.0.0",
        tenant_id="tenant_pg",
        tasks=[],
    )
    engine.register_definition(p_def)

    # Instance A: Completed with no reconciliations
    inst_a = ProcessInstance(
        instance_id="inst_pg_clean_01",
        definition_id=p_def.definition_id,
        definition_version="1.0.0",
        definition_hash=p_def.definition_hash,
        tenant_id="tenant_pg",
        status=ProcessStatus.COMPLETED,
        started_at=old_time,
        completed_at=old_time,
    )
    pg_storage.save_instance(inst_a)

    # Instance B: Completed with pending reconciliation
    inst_b = ProcessInstance(
        instance_id="inst_pg_reconcile_02",
        definition_id=p_def.definition_id,
        definition_version="1.0.0",
        definition_hash=p_def.definition_hash,
        tenant_id="tenant_pg",
        status=ProcessStatus.COMPLETED,
        started_at=old_time,
        completed_at=old_time,
    )
    pg_storage.save_instance(inst_b)

    step_b = SagaStep(step_id="step_fail_pg", name="step_fail_pg")
    saga_b = SagaTransaction(
        saga_id="saga_pg_rec_b",
        process_instance_id="inst_pg_reconcile_02",
        status=SagaStatus.ACTIVE,
        steps=[step_b],
    )
    pg_storage.save_saga(saga_b)

    rec_id = pg_storage.record_reconciliation(
        saga_id="saga_pg_rec_b",
        step_id="step_fail_pg",
        reason="PostgreSQL external failure",
    )

    # Run archival
    archived = pg_storage.archive_completed_instances(cutoff_timestamp=now)
    assert archived >= 1
    assert pg_storage.get_instance("inst_pg_clean_01") is None
    assert pg_storage.get_instance("inst_pg_reconcile_02") is not None

    # Resolve reconciliation
    pg_storage.resolve_reconciliation(rec_id, resolved_by="admin_pg", notes="Resolved in PG")
    archived2 = pg_storage.archive_completed_instances(cutoff_timestamp=now)
    assert archived2 >= 1
    assert pg_storage.get_instance("inst_pg_reconcile_02") is None

    # Event inbox deduplication in PostgreSQL
    assert pg_storage.has_event_inbox("tenant_pg", "evt_pg_01") is False
    rec1 = pg_storage.record_event_inbox("evt_pg_01", "tenant_pg", "stripe", "charge", {"amt": 10})
    assert rec1 is True
    assert pg_storage.has_event_inbox("tenant_pg", "evt_pg_01") is True
    # Duplicate insert returns False
    rec2 = pg_storage.record_event_inbox("evt_pg_01", "tenant_pg", "stripe", "charge", {"amt": 10})
    assert rec2 is False
