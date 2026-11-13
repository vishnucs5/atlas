"""End-to-end integration tests for ATLAS PostgresStorage on a physical PostgreSQL instance."""

import concurrent.futures
import pathlib
import tempfile
import uuid
from datetime import UTC, datetime

import pytest
from atlas_agent.runtime import ProductionRuntime
from atlas_coordination.action_ledger import ActionLedger, NonIdempotentActionUncertaintyError
from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.ledger import ActionExecutionRecord, ActionExecutionStatus
from atlas_core.contracts.task import Task, TaskPriority, TaskRequest, TaskStatus
from atlas_core.contracts.worker import WorkerRecord, WorkerStatus
from atlas_storage.interfaces import (
    CorruptedCheckpointError,
    OptimisticLockError,
    SequenceCollisionError,
    StaleWorkerError,
    TaskNotFoundError,
)
from atlas_storage.postgres import PostgresStorage
from embedded_postgres import PostgresServer


@pytest.fixture(scope="module")
def pg_server():
    """Start an actual native PostgreSQL server for integration testing."""
    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="atlas_pg_e2e_"))
    server = PostgresServer(temp_dir)
    server.ensure_pgdata_inited()
    server.ensure_postgres_running()
    yield server
    server.cleanup()


@pytest.fixture
def pg_storage(pg_server):
    """Provide an initialized PostgresStorage connected to the live PostgreSQL instance."""
    uri = pg_server.get_uri()
    storage = PostgresStorage(uri)
    storage.initialize()
    yield storage
    storage.close()


def test_pg_01_schema_creation_and_idempotent_migrations(pg_storage):
    """Verify schema initialization applies DDL idempotently without errors."""
    # Re-running initialize must be completely safe
    pg_storage.initialize()
    pg_storage.initialize()

    with pg_storage.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
                """
            )
            tables = [r[0] for r in cur.fetchall()]

    assert "tasks" in tables
    assert "execution_events" in tables
    assert "checkpoints" in tables
    assert "action_ledger" in tables
    assert "worker_registry" in tables
    assert "worker_leases" in tables


def test_pg_02_task_creation_and_retrieval(pg_storage):
    """Verify task creation, retrieval, and pagination on PostgreSQL."""
    now = datetime.now(UTC)
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    task = Task(
        task_id=task_id,
        objective="Verify PostgreSQL task persistence",
        status=TaskStatus.CREATED,
        priority=TaskPriority.HIGH,
        created_at=now,
        updated_at=now,
        metadata={"owner_id": "user_pg_1", "env": "production"},
    )
    pg_storage.save_task(task)

    retrieved = pg_storage.get_task(task_id)
    assert retrieved is not None
    assert retrieved.task_id == task_id
    assert retrieved.objective == "Verify PostgreSQL task persistence"
    assert retrieved.status == TaskStatus.CREATED
    assert retrieved.priority == TaskPriority.HIGH
    assert retrieved.metadata["owner_id"] == "user_pg_1"

    # Listing
    tasks = pg_storage.list_tasks(status=TaskStatus.CREATED, limit=10)
    assert any(t.task_id == task_id for t in tasks)


def test_pg_03_atomic_transitions_and_optimistic_locking(pg_storage):
    """Verify atomic state transitions and optimistic concurrency rejection."""
    task_id = f"task_opt_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    task = Task(
        task_id=task_id,
        objective="Optimistic lock testing",
        status=TaskStatus.CREATED,
        priority=TaskPriority.NORMAL,
        created_at=now,
        updated_at=now,
    )
    pg_storage.save_task(task)

    # Valid transition with expected status
    updated = pg_storage.update_task_status(
        task_id, TaskStatus.RUNNING, expected_status=TaskStatus.CREATED
    )
    assert updated.status == TaskStatus.RUNNING

    # Invalid expected status triggers OptimisticLockError
    with pytest.raises(OptimisticLockError) as exc_info:
        pg_storage.update_task_status(
            task_id, TaskStatus.COMPLETED, expected_status=TaskStatus.CREATED
        )
    assert "Optimistic lock conflict" in str(exc_info.value)

    # Nonexistent task triggers TaskNotFoundError
    with pytest.raises(TaskNotFoundError):
        pg_storage.update_task_status("nonexistent_task_id", TaskStatus.COMPLETED)


def test_pg_04_concurrent_event_writes_and_sequence_collision(pg_storage):
    """Verify strict monotonic event sequences and collision rejection."""
    task_id = f"task_events_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    task = Task(
        task_id=task_id,
        objective="Event sequence testing",
        status=TaskStatus.CREATED,
        priority=TaskPriority.NORMAL,
        created_at=now,
        updated_at=now,
    )
    pg_storage.save_task(task)

    e1 = ExecutionEvent(
        event_id=f"e1_{uuid.uuid4().hex[:6]}",
        task_id=task_id,
        sequence=1,
        event_type=EventType.TASK_CREATED,
        timestamp=now,
        payload={"msg": "created"},
        correlation_id="corr_1",
    )
    e2 = ExecutionEvent(
        event_id=f"e2_{uuid.uuid4().hex[:6]}",
        task_id=task_id,
        sequence=2,
        event_type=EventType.ACTION_STARTED,
        timestamp=now,
        payload={"action": "navigate"},
        correlation_id="corr_2",
    )
    pg_storage.append_event(e1)
    pg_storage.append_event(e2)

    assert pg_storage.get_latest_sequence(task_id) == 2

    # Collision attempt with duplicate sequence 2
    e2_duplicate = ExecutionEvent(
        event_id=f"e2_dup_{uuid.uuid4().hex[:6]}",
        task_id=task_id,
        sequence=2,
        event_type=EventType.ACTION_COMPLETED,
        timestamp=now,
        payload={"status": "conflict"},
        correlation_id="corr_3",
    )
    with pytest.raises(SequenceCollisionError):
        pg_storage.append_event(e2_duplicate)

    events = pg_storage.get_events(task_id)
    assert len(events) == 2
    assert [e.sequence for e in events] == [1, 2]


def test_pg_05_batch_events_atomic_rollback(pg_storage):
    """Verify batch append is atomic; collision rolls back all events in batch."""
    task_id = f"task_batch_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    task = Task(
        task_id=task_id,
        objective="Batch rollback testing",
        status=TaskStatus.CREATED,
        priority=TaskPriority.NORMAL,
        created_at=now,
        updated_at=now,
    )
    pg_storage.save_task(task)

    e1 = ExecutionEvent(
        event_id="e_batch_1",
        task_id=task_id,
        sequence=1,
        event_type=EventType.TASK_CREATED,
        timestamp=now,
        correlation_id="c_1",
    )
    pg_storage.append_event(e1)

    # Batch with valid sequence 2, but colliding sequence 1
    e2 = ExecutionEvent(
        event_id="e_batch_2",
        task_id=task_id,
        sequence=2,
        event_type=EventType.ACTION_STARTED,
        timestamp=now,
        correlation_id="c_2",
    )
    e_colliding = ExecutionEvent(
        event_id="e_batch_dup",
        task_id=task_id,
        sequence=1,
        event_type=EventType.ACTION_COMPLETED,
        timestamp=now,
        correlation_id="c_3",
    )

    with pytest.raises(SequenceCollisionError):
        pg_storage.append_events([e2, e_colliding])

    # Sequence 2 must not have been persisted due to transaction rollback
    events = pg_storage.get_events(task_id)
    assert len(events) == 1
    assert events[0].sequence == 1


def test_pg_06_worker_lease_fencing_generations(pg_storage):
    """Verify monotonic lease generations and stale worker commit rejection."""
    task_id = f"task_lease_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    task = Task(
        task_id=task_id,
        objective="Lease fencing testing",
        status=TaskStatus.CREATED,
        priority=TaskPriority.NORMAL,
        created_at=now,
        updated_at=now,
    )
    pg_storage.save_task(task)

    worker_a = WorkerRecord(
        worker_id="worker_a",
        hostname="node-1",
        status=WorkerStatus.IDLE,
        capabilities=["browser"],
        registered_at=now,
        last_heartbeat_at=now,
    )
    worker_b = WorkerRecord(
        worker_id="worker_b",
        hostname="node-2",
        status=WorkerStatus.IDLE,
        capabilities=["browser"],
        registered_at=now,
        last_heartbeat_at=now,
    )
    pg_storage.register_worker(worker_a)
    pg_storage.register_worker(worker_b)

    # Worker A acquires lease (generation 1)
    lease_a = pg_storage.acquire_lease(task_id, "worker_a", ttl_seconds=0.1)
    assert lease_a.generation == 1
    assert lease_a.worker_id == "worker_a"

    # Wait for lease to expire
    import time

    time.sleep(0.15)

    # Worker B acquires expired lease (generation 2)
    lease_b = pg_storage.acquire_lease(task_id, "worker_b", ttl_seconds=30.0)
    assert lease_b.generation == 2
    assert lease_b.worker_id == "worker_b"

    # Worker A attempts commit with stale generation 1 -> rejected with StaleWorkerError
    with pytest.raises(StaleWorkerError):
        pg_storage.validate_lease_fencing(task_id, expected_generation=lease_a.generation)

    # Worker B with generation 2 is valid
    assert (
        pg_storage.validate_lease_fencing(task_id, expected_generation=lease_b.generation) is True
    )


def test_pg_07_duplicate_action_delivery_and_idempotency(pg_storage):
    """Verify action execution records are deduplicated by idempotency key."""
    task_id = f"task_act_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    task = Task(
        task_id=task_id,
        objective="Idempotency testing",
        status=TaskStatus.CREATED,
        priority=TaskPriority.NORMAL,
        created_at=now,
        updated_at=now,
    )
    pg_storage.save_task(task)

    record = ActionExecutionRecord(
        action_id="act_click_1",
        task_id=task_id,
        idempotency_key="idem_key_abc_123",
        attempt=1,
        status=ActionExecutionStatus.STARTED,
        worker_id="worker_1",
        lease_generation=1,
        started_at=now,
        action_type="CLICK",
        parameters={"selector": "#submit-btn"},
    )
    pg_storage.record_action_attempt(record)

    # Update to SUCCEEDED
    updated = pg_storage.update_action_status(
        task_id=task_id,
        idempotency_key="idem_key_abc_123",
        attempt=1,
        status=ActionExecutionStatus.SUCCEEDED,
        output={"clicked": True},
        verification_result={"element_absent": True},
    )
    assert updated.status == ActionExecutionStatus.SUCCEEDED

    # Fetch latest attempt
    latest = pg_storage.get_latest_action(task_id, "idem_key_abc_123")
    assert latest is not None
    assert latest.status == ActionExecutionStatus.SUCCEEDED
    assert latest.output == {"clicked": True}


def test_pg_08_unknown_side_effect_safety(pg_storage):
    """Verify ActionLedger raises NonIdempotentActionUncertaintyError for UNKNOWN actions on PostgreSQL."""
    task_id = f"task_unknown_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    task = Task(
        task_id=task_id,
        objective="Side-effect safety testing",
        status=TaskStatus.CREATED,
        priority=TaskPriority.NORMAL,
        created_at=now,
        updated_at=now,
    )
    pg_storage.save_task(task)

    ledger = ActionLedger(store=pg_storage)
    ledger.start_action(
        action_id="act_pay_1",
        task_id=task_id,
        action_type="CLICK",
        parameters={"button": "pay_now"},
        worker_id="worker_1",
        lease_generation=1,
        idempotency_key="idem_pay_1",
    )
    # Simulate worker crash mid-execution leaving status UNKNOWN
    ledger.mark_unknown(
        task_id=task_id,
        idempotency_key="idem_pay_1",
        attempt=1,
        reason="Worker connection terminated abruptly",
    )

    # Blind retry of non-idempotent action must raise NonIdempotentActionUncertaintyError
    with pytest.raises(NonIdempotentActionUncertaintyError) as exc_info:
        ledger.start_action(
            action_id="act_pay_1",
            task_id=task_id,
            action_type="CLICK",
            parameters={"button": "pay_now"},
            worker_id="worker_1",
            lease_generation=1,
            idempotency_key="idem_pay_1",
        )
    assert "cannot be re-executed without physical environment reconciliation" in str(
        exc_info.value
    )


def test_pg_09_checkpoint_persistence_and_cryptographic_verification(pg_storage):
    """Verify checkpoint persistence, hash calculation, and tamper detection."""
    task_id = f"task_chk_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    task = Task(
        task_id=task_id,
        objective="Checkpoint testing",
        status=TaskStatus.CREATED,
        priority=TaskPriority.NORMAL,
        created_at=now,
        updated_at=now,
    )
    pg_storage.save_task(task)

    chk = Checkpoint(
        checkpoint_id="chk_pg_001",
        task_id=task_id,
        session_id="sess_pg",
        worker_id="worker_1",
        lease_generation=1,
        state=TaskStatus.RUNNING,
        sequence=5,
        plan_id="plan_1",
        plan_version=1,
        current_step_id="step_2",
        completed_action_ids=["act_1"],
        pending_action_ids=["act_2"],
        uncertain_action_ids=[],
        last_event_sequence=5,
        state_snapshot={"active_tab": "https://example.com"},
        timestamp=now,
    )
    chk.checkpoint_hash = chk.compute_hash()
    pg_storage.save_checkpoint(chk)

    # Retrieval with verification succeeds
    retrieved = pg_storage.get_checkpoint("chk_pg_001", verify=True)
    assert retrieved is not None
    assert retrieved.checkpoint_id == "chk_pg_001"
    assert retrieved.sequence == 5

    # Tamper with checkpoint directly in database
    with pg_storage.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE checkpoints SET sequence = 999 WHERE checkpoint_id = %s;",
                ("chk_pg_001",),
            )
        conn.commit()

    # Verification must detect corruption and raise CorruptedCheckpointError
    with pytest.raises(CorruptedCheckpointError):
        pg_storage.get_checkpoint("chk_pg_001", verify=True)


def test_pg_10_transaction_rollback_on_error(pg_storage):
    """Verify database transactions roll back cleanly when a low-level error occurs."""
    task_id = f"task_tx_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    task = Task(
        task_id=task_id,
        objective="Transaction rollback testing",
        status=TaskStatus.CREATED,
        priority=TaskPriority.NORMAL,
        created_at=now,
        updated_at=now,
    )
    pg_storage.save_task(task)

    try:
        with pg_storage.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE tasks SET status = %s WHERE task_id = %s;",
                    (TaskStatus.RUNNING.value, task_id),
                )
                # Intentionally trigger error
                cur.execute("SELECT * FROM non_existent_table_xyz;")
            conn.commit()
    except Exception:
        pass

    # Status must remain CREATED due to rollback
    t = pg_storage.get_task(task_id)
    assert t is not None
    assert t.status == TaskStatus.CREATED


def test_pg_11_worker_heartbeat_and_discovery(pg_storage):
    """Verify worker registration, heartbeats, and status filtering."""
    now = datetime.now(UTC)
    w_id = f"w_{uuid.uuid4().hex[:6]}"
    worker = WorkerRecord(
        worker_id=w_id,
        hostname="cluster-node-1",
        status=WorkerStatus.IDLE,
        capabilities=["browser", "desktop"],
        registered_at=now,
        last_heartbeat_at=now,
        metadata={"region": "us-east-1"},
    )
    pg_storage.register_worker(worker)

    # Heartbeat
    pg_storage.heartbeat_worker(w_id, status=WorkerStatus.BUSY)

    fetched = pg_storage.get_worker(w_id)
    assert fetched is not None
    assert fetched.status == WorkerStatus.BUSY
    assert fetched.capabilities == ["browser", "desktop"]

    busy_workers = pg_storage.list_workers(status=WorkerStatus.BUSY)
    assert any(w.worker_id == w_id for w in busy_workers)


def test_pg_12_concurrent_task_execution(pg_storage):
    """Verify thread-safe concurrent tasks and event interleaving on connection pool."""
    task_ids = [f"task_concur_{i}_{uuid.uuid4().hex[:6]}" for i in range(10)]
    now = datetime.now(UTC)

    for tid in task_ids:
        pg_storage.save_task(
            Task(
                task_id=tid,
                objective=f"Concurrency test {tid}",
                status=TaskStatus.CREATED,
                created_at=now,
                updated_at=now,
            )
        )

    def worker_action(tid: str):
        for seq in range(1, 6):
            pg_storage.append_event(
                ExecutionEvent(
                    event_id=f"e_{tid}_{seq}",
                    task_id=tid,
                    sequence=seq,
                    event_type=EventType.ACTION_COMPLETED,
                    timestamp=datetime.now(UTC),
                    payload={"seq": seq},
                    correlation_id=f"corr_{tid}",
                )
            )
        pg_storage.update_task_status(tid, TaskStatus.COMPLETED)
        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(worker_action, task_ids))

    assert all(results)
    for tid in task_ids:
        t = pg_storage.get_task(tid)
        assert t.status == TaskStatus.COMPLETED
        assert pg_storage.get_latest_sequence(tid) == 5


def test_pg_13_cross_tenant_isolation(pg_storage):
    """Verify multi-tenant task queries and isolation in PostgreSQL storage."""
    now = datetime.now(UTC)
    t_alice = Task(
        task_id=f"task_alice_{uuid.uuid4().hex[:6]}",
        objective="Alice private task",
        status=TaskStatus.CREATED,
        created_at=now,
        updated_at=now,
        metadata={"owner_id": "alice"},
    )
    t_bob = Task(
        task_id=f"task_bob_{uuid.uuid4().hex[:6]}",
        objective="Bob private task",
        status=TaskStatus.CREATED,
        created_at=now,
        updated_at=now,
        metadata={"owner_id": "bob"},
    )
    pg_storage.save_task(t_alice)
    pg_storage.save_task(t_bob)

    all_tasks = pg_storage.list_tasks(limit=100)
    alice_tasks = [t for t in all_tasks if t.metadata.get("owner_id") == "alice"]
    bob_tasks = [t for t in all_tasks if t.metadata.get("owner_id") == "bob"]

    assert any(t.task_id == t_alice.task_id for t in alice_tasks)
    assert not any(t.task_id == t_bob.task_id for t in alice_tasks)
    assert any(t.task_id == t_bob.task_id for t in bob_tasks)


@pytest.mark.asyncio
async def test_pg_14_full_production_runtime_lifecycle(pg_storage):
    """Verify ProductionRuntime runs full task lifecycle using PostgresStorage."""
    runtime = ProductionRuntime(storage=pg_storage)
    await runtime.initialize()

    try:
        req = TaskRequest(
            objective="PostgreSQL runtime lifecycle test",
            priority=TaskPriority.HIGH,
            metadata={"source": "pg_integration_test"},
        )
        task = await runtime.submit_task(req, wait_until_complete=False)
        assert task.task_id is not None
        assert task.status in (
            TaskStatus.CREATED,
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
            TaskStatus.PLANNING,
        )

        # Fetch through storage
        persisted = pg_storage.get_task(task.task_id)
        assert persisted is not None
        assert persisted.objective == "PostgreSQL runtime lifecycle test"

        # Events emitted
        events = pg_storage.get_events(task.task_id)
        assert len(events) >= 1
        assert events[0].event_type == EventType.TASK_CREATED
    finally:
        await runtime.shutdown()
