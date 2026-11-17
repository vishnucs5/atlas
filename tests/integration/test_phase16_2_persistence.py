"""Integration tests for durable persistence, PostgreSQL integration, and crash recovery in atlas_process."""

import pathlib
import tempfile
import time

import pytest
from atlas_process.definitions import (
    ProcessDefinition,
    ProcessTaskDefinition,
    TaskType,
)
from atlas_process.engine import (
    ProcessExecutionEngine,
    StaleWorkerFencingError,
)
from atlas_process.state_machine import ProcessStatus, ProcessTaskStatus
from atlas_process.storage import (
    PostgresProcessStorage,
    SqliteProcessStorage,
)
from embedded_postgres import PostgresServer


@pytest.fixture(scope="module")
def pg_server():
    """Start an actual native PostgreSQL server for Phase 16.2 persistence testing."""
    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="atlas_p16_pg_"))
    server = PostgresServer(temp_dir)
    server.ensure_pgdata_inited()
    server.ensure_postgres_running()
    yield server
    server.cleanup()


def test_process_crash_and_restart_recovery_sqlite(tmp_path):
    """Verify process state survives application termination using SQLite WAL persistence."""
    db_file = tmp_path / "process_store.db"
    storage1 = SqliteProcessStorage(db_file)
    engine1 = ProcessExecutionEngine(storage=storage1)

    t1 = ProcessTaskDefinition(
        task_def_id="step1",
        name="Ingest Order",
        task_type=TaskType.AGENT_EXECUTION,
        dependencies=[],
    )
    t2 = ProcessTaskDefinition(
        task_def_id="step2",
        name="Charge Card",
        task_type=TaskType.AGENT_EXECUTION,
        dependencies=["step1"],
    )
    pdef = ProcessDefinition(
        definition_id="def_order_1",
        tenant_id="tenant_walmart",
        name="Order Flow",
        tasks=[t1, t2],
    )
    engine1.register_definition(pdef)

    # Start process and execute step 1
    instance = engine1.start_process(
        "def_order_1", "tenant_walmart", initial_variables={"amount": 99.95}
    )
    assert instance.status == ProcessStatus.RUNNING

    lease_token, fencing = engine1.acquire_task_lease(
        instance.instance_id, "step1", "worker-node-1"
    )
    engine1.complete_task(instance.instance_id, "step1", {"order_id": "ORD-1"}, fencing)

    # Step 2 is now READY
    inst_before_crash = engine1.get_instance(instance.instance_id)
    assert inst_before_crash.task_instances["step1"].status == ProcessTaskStatus.COMPLETED
    assert inst_before_crash.task_instances["step2"].status == ProcessTaskStatus.READY

    # Worker begins Step 2 and enters RUNNING
    lease2, fencing2 = engine1.acquire_task_lease(
        instance.instance_id, "step2", "worker-node-1", lease_duration_seconds=0.01
    )
    time.sleep(0.05)  # Let lease expire

    # === CRASH: Simulate total OS process death (engine1 and storage1 garbage collected) ===
    del engine1
    del storage1

    # === RESTART: Start a new engine instance from the persistent SQLite database ===
    storage2 = SqliteProcessStorage(db_file)
    engine2 = ProcessExecutionEngine(storage=storage2)

    # Verify recover_after_restart recovers the expired task back to READY
    recovered_count = engine2.recover_after_restart()
    assert recovered_count == 1

    recovered_instance = engine2.get_instance(instance.instance_id)
    assert recovered_instance is not None
    assert recovered_instance.variables["amount"] == 99.95
    assert recovered_instance.variables["order_id"] == "ORD-1"
    assert recovered_instance.task_instances["step1"].status == ProcessTaskStatus.COMPLETED
    assert recovered_instance.task_instances["step2"].status == ProcessTaskStatus.READY


def test_process_crash_and_restart_recovery_postgres(pg_server):
    """Verify process state survives application termination using real PostgreSQL 16+ storage."""
    uri = pg_server.get_uri()
    storage1 = PostgresProcessStorage(uri)
    storage1.initialize()
    engine1 = ProcessExecutionEngine(storage=storage1)

    t1 = ProcessTaskDefinition(
        task_def_id="pg_step1",
        name="Validate Account",
        task_type=TaskType.AGENT_EXECUTION,
        dependencies=[],
    )
    pdef = ProcessDefinition(
        definition_id="def_pg_flow",
        tenant_id="tenant_bank",
        name="Bank Flow",
        tasks=[t1],
    )
    engine1.register_definition(pdef)

    instance = engine1.start_process(
        "def_pg_flow", "tenant_bank", initial_variables={"balance": 5000}
    )
    lease_token, fencing = engine1.acquire_task_lease(
        instance.instance_id, "pg_step1", "worker-pg-1", lease_duration_seconds=0.01
    )
    time.sleep(0.05)  # Let lease expire

    # === CRASH ===
    storage1.close()
    del engine1
    del storage1

    # === RESTART with engine2 ===
    storage2 = PostgresProcessStorage(uri)
    engine2 = ProcessExecutionEngine(storage=storage2)

    recovered = engine2.recover_after_restart()
    assert recovered == 1

    recovered_instance = engine2.get_instance(instance.instance_id)
    assert recovered_instance is not None
    assert recovered_instance.variables["balance"] == 5000
    assert recovered_instance.task_instances["pg_step1"].status == ProcessTaskStatus.READY

    storage2.close()


def test_distributed_fencing_token_rejection(tmp_path):
    """Verify monotonic fencing token prevents stale workers from corrupting state."""
    db_file = tmp_path / "fencing_store.db"
    storage = SqliteProcessStorage(db_file)
    engine = ProcessExecutionEngine(storage=storage)

    t1 = ProcessTaskDefinition(
        task_def_id="task_fenced",
        name="Update Ledger",
        task_type=TaskType.AGENT_EXECUTION,
        dependencies=[],
    )
    pdef = ProcessDefinition(
        definition_id="def_fenced",
        tenant_id="tenant_fin",
        name="Fenced Flow",
        tasks=[t1],
    )
    engine.register_definition(pdef)

    inst = engine.start_process("def_fenced", "tenant_fin")

    # Worker A acquires lease (fencing = 1)
    lease_a, fencing_a = engine.acquire_task_lease(
        inst.instance_id, "task_fenced", "worker-A", lease_duration_seconds=0.01
    )
    assert fencing_a == 1
    time.sleep(0.05)  # Lease expires

    # Worker B acquires lease (fencing = 2)
    lease_b, fencing_b = engine.acquire_task_lease(
        inst.instance_id, "task_fenced", "worker-B", lease_duration_seconds=60.0
    )
    assert fencing_b == 2

    # Stale Worker A attempts commit with old fencing token 1 -> REJECTED
    with pytest.raises(StaleWorkerFencingError):
        engine.complete_task(
            inst.instance_id, "task_fenced", {"status": "corrupted_by_A"}, fencing_token=fencing_a
        )

    # Active Worker B commits with fencing token 2 -> SUCCESS
    engine.complete_task(
        inst.instance_id, "task_fenced", {"status": "valid_from_B"}, fencing_token=fencing_b
    )
    final_inst = engine.get_instance(inst.instance_id)
    assert final_inst.task_instances["task_fenced"].status == ProcessTaskStatus.COMPLETED
    assert final_inst.variables["status"] == "valid_from_B"


def test_pagination_and_archival(tmp_path):
    """Verify paginated listing and time-based archival."""
    db_file = tmp_path / "archival_store.db"
    storage = SqliteProcessStorage(db_file)
    engine = ProcessExecutionEngine(storage=storage)

    t1 = ProcessTaskDefinition(
        task_def_id="simple_step",
        name="Step",
        task_type=TaskType.AGENT_EXECUTION,
    )
    pdef = ProcessDefinition(
        definition_id="def_arch",
        tenant_id="tenant_archive",
        name="Archival Flow",
        tasks=[t1],
    )
    engine.register_definition(pdef)

    # Start and complete 5 instances
    instances = []
    for i in range(5):
        inst = engine.start_process("def_arch", "tenant_archive", initial_variables={"idx": i})
        lease, fencing = engine.acquire_task_lease(inst.instance_id, "simple_step", "w1")
        engine.complete_task(inst.instance_id, "simple_step", {"done": True}, fencing)
        instances.append(inst)

    # Paginated query
    page1 = engine.list_instances(tenant_id="tenant_archive", limit=3, offset=0)
    assert len(page1) == 3

    page2 = engine.list_instances(tenant_id="tenant_archive", limit=3, offset=3)
    assert len(page2) == 2

    # Archive instances older than future timestamp
    archived_count = engine.archive_completed_instances(
        cutoff_timestamp=time.time() + 100.0, tenant_id="tenant_archive"
    )
    assert archived_count == 5

    remaining = engine.list_instances(tenant_id="tenant_archive")
    assert len(remaining) == 0
