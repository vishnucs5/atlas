"""Unit tests for SQLite event-sourced storage and PostgreSQL interface."""

import sqlite3
import threading
from datetime import UTC, datetime

import pytest
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_storage.interfaces import (
    EventStoreProtocol,
    OptimisticLockError,
    SequenceCollisionError,
    TaskNotFoundError,
    TaskStoreProtocol,
)
from atlas_storage.postgres import PostgresConfig, PostgresStorageSpec, PostgresTaskStoreInterface
from atlas_storage.sqlite import SQLiteStorage, SQLiteTaskStore


def test_sqlite_task_and_event_lifecycle(tmp_path):
    """Test basic lifecycle of saving tasks, updating status, and appending events."""
    db_file = tmp_path / "test_atlas.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    now = datetime.now(UTC)
    task = Task(
        task_id="t_001",
        objective="Run benchmark",
        status=TaskStatus.CREATED,
        priority=TaskPriority.NORMAL,
        created_at=now,
        updated_at=now,
        metadata={"env": "test"},
    )
    store.save_task(task)

    fetched = store.get_task("t_001")
    assert fetched is not None
    assert fetched.task_id == "t_001"
    assert fetched.status == TaskStatus.CREATED
    assert fetched.priority == TaskPriority.NORMAL
    assert fetched.objective == "Run benchmark"
    assert fetched.metadata == {"env": "test"}

    evt = ExecutionEvent(
        event_id="e_001",
        task_id="t_001",
        sequence=1,
        event_type=EventType.TASK_CREATED,
        timestamp=now,
        payload={"objective": task.objective},
        correlation_id="c_001",
    )
    store.append_event(evt)
    events = store.get_events("t_001")
    assert len(events) == 1
    assert events[0].event_id == "e_001"
    assert events[0].sequence == 1
    assert events[0].event_type == EventType.TASK_CREATED
    assert events[0].payload == {"objective": "Run benchmark"}

    # Transition status
    store.update_task_status("t_001", TaskStatus.RUNNING)
    updated = store.get_task("t_001")
    assert updated is not None
    assert updated.status == TaskStatus.RUNNING


def test_sqlite_sequence_collision(tmp_path):
    """Verify that duplicate event sequences for the same task raise SequenceCollisionError."""
    db_file = tmp_path / "test_collision.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    now = datetime.now(UTC)
    evt1 = ExecutionEvent(
        event_id="e_001",
        task_id="t_001",
        sequence=1,
        event_type=EventType.TASK_CREATED,
        timestamp=now,
        payload={"step": 1},
        correlation_id="c_001",
    )
    store.append_event(evt1)

    evt2 = ExecutionEvent(
        event_id="e_002",
        task_id="t_001",
        sequence=1,  # Duplicate sequence!
        event_type=EventType.PLAN_GENERATED,
        timestamp=now,
        payload={"step": 2},
        correlation_id="c_002",
    )
    with pytest.raises(SequenceCollisionError):
        store.append_event(evt2)


def test_sqlite_optimistic_concurrency(tmp_path):
    """Verify that update_task_status enforces expected_status checks."""
    db_file = tmp_path / "test_concurrency.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    now = datetime.now(UTC)
    task = Task(
        task_id="t_002",
        objective="Analyze logs",
        status=TaskStatus.CREATED,
        priority=TaskPriority.HIGH,
        created_at=now,
        updated_at=now,
    )
    store.save_task(task)

    # Valid expected status transition
    store.update_task_status("t_002", TaskStatus.RUNNING, expected_status=TaskStatus.CREATED)
    t = store.get_task("t_002")
    assert t is not None
    assert t.status == TaskStatus.RUNNING

    # Invalid expected status transition should fail
    with pytest.raises(OptimisticLockError):
        store.update_task_status("t_002", TaskStatus.COMPLETED, expected_status=TaskStatus.CREATED)

    # Still RUNNING
    assert store.get_task("t_002").status == TaskStatus.RUNNING


def test_sqlite_task_not_found(tmp_path):
    """Verify error behavior on nonexistent tasks."""
    db_file = tmp_path / "test_not_found.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    assert store.get_task("nonexistent") is None

    with pytest.raises(TaskNotFoundError):
        store.update_task_status("nonexistent", TaskStatus.RUNNING)


def test_sqlite_list_tasks(tmp_path):
    """Test listing tasks with filtering and pagination."""
    db_file = tmp_path / "test_list.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    now = datetime.now(UTC)
    for i in range(5):
        t = Task(
            task_id=f"t_{i}",
            objective=f"Objective {i}",
            status=TaskStatus.CREATED if i % 2 == 0 else TaskStatus.RUNNING,
            priority=TaskPriority.NORMAL,
            created_at=now,
            updated_at=now,
        )
        store.save_task(t)

    all_tasks = store.list_tasks(limit=10)
    assert len(all_tasks) == 5

    created_tasks = store.list_tasks(status=TaskStatus.CREATED)
    assert len(created_tasks) == 3

    running_tasks = store.list_tasks(status=TaskStatus.RUNNING)
    assert len(running_tasks) == 2

    paginated = store.list_tasks(limit=2, offset=0)
    assert len(paginated) == 2


def test_sqlite_event_retrieval(tmp_path):
    """Test getting events by sequence and retrieving the latest event."""
    db_file = tmp_path / "test_events.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    now = datetime.now(UTC)
    for seq in range(1, 4):
        evt = ExecutionEvent(
            event_id=f"e_{seq}",
            task_id="t_events",
            sequence=seq,
            event_type=EventType.ACTION_STARTED,
            timestamp=now,
            payload={"step": seq},
            correlation_id=f"c_{seq}",
        )
        store.append_event(evt)

    events_all = store.get_events("t_events")
    assert len(events_all) == 3
    assert [e.sequence for e in events_all] == [1, 2, 3]

    since_seq_1 = store.get_events("t_events", since_sequence=1)
    assert len(since_seq_1) == 2
    assert [e.sequence for e in since_seq_1] == [2, 3]

    latest = store.get_latest_event("t_events")
    assert latest is not None
    assert latest.sequence == 3
    assert latest.event_id == "e_3"

    assert store.get_latest_event("unknown_task") is None


def test_sqlite_get_latest_sequence(tmp_path):
    """Verify get_latest_sequence returns 0 for empty tasks and max sequence for active tasks."""
    db_file = tmp_path / "test_sequence.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    # Returns 0 when no events exist
    assert store.get_latest_sequence("nonexistent_task") == 0

    now = datetime.now(UTC)
    for seq in range(1, 5):
        store.append_event(
            ExecutionEvent(
                event_id=f"e_seq_{seq}",
                task_id="t_seq",
                sequence=seq,
                event_type=EventType.OBSERVATION_CAPTURED,
                timestamp=now,
                payload={"index": seq},
                correlation_id="c_seq",
            )
        )
        assert store.get_latest_sequence("t_seq") == seq

    assert store.get_latest_sequence("t_seq") == 4
    assert store.get_latest_sequence("other_task") == 0
    store.close()


def test_sqlite_batch_events_and_rollback(tmp_path):
    """Test batch appending events and atomic rollback upon collision."""
    db_file = tmp_path / "test_batch.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    now = datetime.now(UTC)
    events = [
        ExecutionEvent(
            event_id=f"e_batch_{i}",
            task_id="t_batch",
            sequence=i,
            event_type=EventType.ACTION_PROPOSED,
            timestamp=now,
            payload={"index": i},
            correlation_id="c_batch",
        )
        for i in range(1, 4)
    ]
    store.append_events(events)
    assert len(store.get_events("t_batch")) == 3

    # Colliding batch: sequence 3 already exists
    bad_batch = [
        ExecutionEvent(
            event_id="e_batch_bad",
            task_id="t_batch",
            sequence=3,
            event_type=EventType.ACTION_PROPOSED,
            timestamp=now,
            payload={"index": 3},
            correlation_id="c_batch",
        ),
        ExecutionEvent(
            event_id="e_batch_4",
            task_id="t_batch",
            sequence=4,
            event_type=EventType.ACTION_PROPOSED,
            timestamp=now,
            payload={"index": 4},
            correlation_id="c_batch",
        ),
    ]
    with pytest.raises(SequenceCollisionError):
        store.append_events(bad_batch)

    # Sequence 4 should not have been inserted due to transaction rollback
    assert len(store.get_events("t_batch")) == 3


def test_sqlite_in_memory_and_context_manager():
    """Verify in-memory database and context manager lifecycle."""
    with SQLiteStorage(":memory:") as store:
        now = datetime.now(UTC)
        task = Task(
            task_id="mem_1",
            objective="In memory task",
            created_at=now,
            updated_at=now,
        )
        store.save_task(task)
        assert store.get_task("mem_1") is not None


def test_sqlite_wal_pragmas(tmp_path):
    """Verify that SQLite engine configures WAL mode, busy timeout, and synchronicity."""
    db_file = tmp_path / "test_pragmas.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    # Verify connection pragmas configured on the active store connection
    conn = store._get_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA journal_mode;")
    journal_mode = cursor.fetchone()[0]
    assert journal_mode.lower() == "wal"

    cursor.execute("PRAGMA busy_timeout;")
    busy_timeout = cursor.fetchone()[0]
    assert busy_timeout == 5000

    cursor.execute("PRAGMA synchronous;")
    sync_mode = cursor.fetchone()[0]
    # 1 is NORMAL in SQLite
    assert sync_mode == 1

    cursor.execute("PRAGMA foreign_keys;")
    foreign_keys = cursor.fetchone()[0]
    assert foreign_keys == 1

    # Verify journal_mode persists in the database file header across independent connections
    ext_conn = sqlite3.connect(str(db_file))
    ext_cursor = ext_conn.cursor()
    ext_cursor.execute("PRAGMA journal_mode;")
    assert ext_cursor.fetchone()[0].lower() == "wal"
    ext_conn.close()

    store.close()


def test_sqlite_wal_concurrency(tmp_path):
    """Verify concurrent reads and writes operate smoothly under WAL mode."""
    db_file = tmp_path / "test_concurrent.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    now = datetime.now(UTC)
    task = Task(
        task_id="t_concurrent",
        objective="Concurrent task",
        created_at=now,
        updated_at=now,
    )
    store.save_task(task)

    reader_errors: list[Exception] = []

    def reader():
        try:
            reader_store = SQLiteStorage(str(db_file))
            for _ in range(20):
                t = reader_store.get_task("t_concurrent")
                assert t is not None
            reader_store.close()
        except Exception as e:
            reader_errors.append(e)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for th in threads:
        th.start()

    # Concurrent writer
    for i in range(1, 21):
        evt = ExecutionEvent(
            event_id=f"e_c_{i}",
            task_id="t_concurrent",
            sequence=i,
            event_type=EventType.OBSERVATION_CAPTURED,
            timestamp=now,
            payload={"counter": i},
            correlation_id="c_concurrent",
        )
        store.append_event(evt)

    for th in threads:
        th.join()

    assert not reader_errors
    assert len(store.get_events("t_concurrent")) == 20
    store.close()


def test_protocol_conformance(tmp_path):
    """Verify SQLiteStorage satisfies TaskStoreProtocol and EventStoreProtocol."""
    db_file = tmp_path / "test_protocols.db"
    store: TaskStoreProtocol = SQLiteStorage(str(db_file))
    assert isinstance(store, TaskStoreProtocol)

    event_store: EventStoreProtocol = SQLiteStorage(str(db_file))
    assert isinstance(event_store, EventStoreProtocol)

    # SQLiteTaskStore alias
    alias_store = SQLiteTaskStore(str(db_file))
    assert isinstance(alias_store, SQLiteStorage)


def test_postgres_storage_spec():
    """Verify PostgreSQL interface specification and DDL definitions."""
    config = PostgresConfig(
        host="localhost",
        port=5432,
        database="atlas",
        user="atlas_user",
        password="secret_password",
        min_pool_size=5,
        max_pool_size=20,
    )
    spec = PostgresStorageSpec(config=config)
    ddl = spec.get_schema_ddl()
    assert "CREATE TABLE IF NOT EXISTS tasks" in ddl
    assert "CREATE TABLE IF NOT EXISTS execution_events" in ddl
    assert spec.dsn == "postgresql://atlas_user:secret_password@localhost:5432/atlas"

    # Verify abstract interface
    interface = PostgresTaskStoreInterface(config=config)
    with pytest.raises(NotImplementedError):
        interface.initialize()
    with pytest.raises(NotImplementedError):
        interface.save_task(
            Task(
                task_id="t_pg",
                objective="pg test",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
    with pytest.raises(NotImplementedError):
        interface.get_task("t_pg")
    with pytest.raises(NotImplementedError):
        interface.update_task_status("t_pg", TaskStatus.RUNNING)
    with pytest.raises(NotImplementedError):
        interface.list_tasks()
    with pytest.raises(NotImplementedError):
        interface.append_event(
            ExecutionEvent(
                event_id="e_pg",
                task_id="t_pg",
                sequence=1,
                event_type=EventType.TASK_CREATED,
                timestamp=datetime.now(UTC),
                correlation_id="c_pg",
            )
        )
    with pytest.raises(NotImplementedError):
        interface.get_events("t_pg")
    with pytest.raises(NotImplementedError):
        interface.get_latest_event("t_pg")
    with pytest.raises(NotImplementedError):
        interface.append_events([])
    with pytest.raises(NotImplementedError):
        interface.get_latest_sequence("t_pg")
