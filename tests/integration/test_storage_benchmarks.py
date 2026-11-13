"""Reproducible performance benchmark and deployment verification comparing SQLite and PostgreSQL."""

import concurrent.futures
import math
import pathlib
import tempfile
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from atlas_api.main import app
from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_storage.postgres import PostgresStorage
from atlas_storage.sqlite import SQLiteStorage
from embedded_postgres import PostgresServer
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def pg_server():
    """Spin up isolated native PostgreSQL server for benchmark execution."""
    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="atlas_pg_bench_"))
    server = PostgresServer(temp_dir)
    server.ensure_pgdata_inited()
    server.ensure_postgres_running()
    yield server.get_uri()
    server.cleanup()


def _percentile(data: list[float], percentile_rank: float) -> float:
    """Calculate percentile from a sorted list of numeric values."""
    if not data:
        return 0.0
    k = (len(data) - 1) * (percentile_rank / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    d0 = data[int(f)] * (c - k)
    d1 = data[int(c)] * (k - f)
    return d0 + d1


def test_benchmark_task_persistence_throughput(pg_server: str, tmp_path) -> None:
    """Measure and compare task insertion throughput (tasks/second) between SQLite and PostgreSQL."""
    iterations = 100
    now = datetime.now(UTC)

    # 1. Benchmark SQLite
    sqlite_path = str(tmp_path / "bench_sqlite.db")
    sqlite_storage = SQLiteStorage(sqlite_path)
    sqlite_storage.initialize()

    t0 = time.perf_counter()
    for i in range(iterations):
        task = Task(
            task_id=f"sqlite_task_{i}",
            objective="SQLite persistence benchmark",
            status=TaskStatus.RUNNING,
            priority=TaskPriority.NORMAL,
            created_at=now,
            updated_at=now,
        )
        sqlite_storage.save_task(task)
    sqlite_duration = time.perf_counter() - t0
    sqlite_tps = iterations / sqlite_duration
    sqlite_storage.close()

    # 2. Benchmark PostgreSQL
    pg_storage = PostgresStorage(pg_server)
    pg_storage.initialize()

    t1 = time.perf_counter()
    for i in range(iterations):
        task = Task(
            task_id=f"pg_task_{i}",
            objective="PostgreSQL persistence benchmark",
            status=TaskStatus.RUNNING,
            priority=TaskPriority.NORMAL,
            created_at=now,
            updated_at=now,
        )
        pg_storage.save_task(task)
    pg_duration = time.perf_counter() - t1
    pg_tps = iterations / pg_duration
    pg_storage.close()

    print(f"\n--- TASK PERSISTENCE THROUGHPUT ({iterations} operations) ---")
    print(f"SQLite:     {sqlite_tps:8.2f} tasks/sec (total {sqlite_duration * 1000:6.1f} ms)")
    print(f"PostgreSQL: {pg_tps:8.2f} tasks/sec (total {pg_duration * 1000:6.1f} ms)")

    # Assert reasonable baseline performance for production deployment
    assert sqlite_tps > 50.0, f"SQLite throughput too low: {sqlite_tps:.1f} ops/sec"
    assert pg_tps > 50.0, f"PostgreSQL throughput too low: {pg_tps:.1f} ops/sec"


def test_benchmark_event_append_latency_percentiles(pg_server: str, tmp_path) -> None:
    """Measure p50, p90, and p99 latency percentiles for sequential event logging."""
    num_events = 150
    now = datetime.now(UTC)

    # Setup backends
    sqlite_storage = SQLiteStorage(str(tmp_path / "bench_events_sqlite.db"))
    sqlite_storage.initialize()

    pg_storage = PostgresStorage(pg_server)
    pg_storage.initialize()

    # Seed base task
    base_task_sqlite = Task(
        task_id="bench_task_events_sql",
        objective="Event latency bench",
        status=TaskStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )
    sqlite_storage.save_task(base_task_sqlite)

    base_task_pg = Task(
        task_id="bench_task_events_pg",
        objective="Event latency bench",
        status=TaskStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )
    pg_storage.save_task(base_task_pg)

    # 1. Benchmark SQLite event appends
    sqlite_latencies: list[float] = []
    for seq in range(1, num_events + 1):
        evt = ExecutionEvent(
            event_id=f"evt_sqlite_{seq}",
            task_id=base_task_sqlite.task_id,
            sequence=seq,
            event_type=EventType.ACTION_COMPLETED,
            timestamp=now,
            payload={"step_index": seq, "result": "ok"},
            correlation_id=f"corr_sqlite_{seq}",
        )
        t_start = time.perf_counter()
        sqlite_storage.append_event(evt)
        sqlite_latencies.append((time.perf_counter() - t_start) * 1000.0)

    # 2. Benchmark PostgreSQL event appends
    pg_latencies: list[float] = []
    for seq in range(1, num_events + 1):
        evt = ExecutionEvent(
            event_id=f"evt_pg_{seq}",
            task_id=base_task_pg.task_id,
            sequence=seq,
            event_type=EventType.ACTION_COMPLETED,
            timestamp=now,
            payload={"step_index": seq, "result": "ok"},
            correlation_id=f"corr_pg_{seq}",
        )
        t_start = time.perf_counter()
        pg_storage.append_event(evt)
        pg_latencies.append((time.perf_counter() - t_start) * 1000.0)

    sqlite_storage.close()
    pg_storage.close()

    sqlite_latencies.sort()
    pg_latencies.sort()

    sql_p50 = _percentile(sqlite_latencies, 50)
    sql_p90 = _percentile(sqlite_latencies, 90)
    sql_p99 = _percentile(sqlite_latencies, 99)

    pg_p50 = _percentile(pg_latencies, 50)
    pg_p90 = _percentile(pg_latencies, 90)
    pg_p99 = _percentile(pg_latencies, 99)

    print(f"\n--- EVENT APPEND LATENCY ({num_events} events) ---")
    print(f"SQLite     p50: {sql_p50:6.3f}ms | p90: {sql_p90:6.3f}ms | p99: {sql_p99:6.3f}ms")
    print(f"PostgreSQL p50: {pg_p50:6.3f}ms | p90: {pg_p90:6.3f}ms | p99: {pg_p99:6.3f}ms")

    # Latency SLAs: p99 must be under 50ms locally
    assert sql_p99 < 50.0, f"SQLite p99 latency exceeded SLA: {sql_p99:.2f}ms"
    assert pg_p99 < 50.0, f"PostgreSQL p99 latency exceeded SLA: {pg_p99:.2f}ms"


def test_benchmark_checkpoint_creation_and_tamper_verification(pg_server: str, tmp_path) -> None:
    """Measure throughput of checkpoint snapshot sealing and SHA-256 integrity verification."""
    num_checkpoints = 50
    now = datetime.now(UTC)

    pg_storage = PostgresStorage(pg_server)
    pg_storage.initialize()

    # Pre-create parent task
    parent_task = Task(
        task_id="task_ckpt_bench",
        objective="Checkpoint benchmark parent",
        status=TaskStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )
    pg_storage.save_task(parent_task)

    # Save sealed checkpoints
    t0 = time.perf_counter()
    for i in range(num_checkpoints):
        ckpt = Checkpoint(
            checkpoint_id=f"ckpt_bench_{i}",
            task_id=parent_task.task_id,
            sequence=i,
            state=TaskStatus.RUNNING,
            state_snapshot={"model": "test", "state_vector": [1, 2, 3, i], "env": "prod"},
            timestamp=now,
        )
        ckpt.seal()
        pg_storage.save_checkpoint(ckpt)
    write_duration = time.perf_counter() - t0
    write_rate = num_checkpoints / write_duration

    # Read and cryptographically verify checkpoints
    t1 = time.perf_counter()
    for i in range(num_checkpoints):
        retrieved = pg_storage.get_checkpoint(f"ckpt_bench_{i}")
        assert retrieved is not None
        assert retrieved.sequence == i
        # Cryptographic verification check
        assert retrieved.verify_hash() is True
    read_duration = time.perf_counter() - t1
    read_rate = num_checkpoints / read_duration

    pg_storage.close()

    print(f"\n--- CHECKPOINT PERFORMANCE ({num_checkpoints} snapshots) ---")
    print(f"PostgreSQL Checkpoint Writes: {write_rate:8.2f} ops/sec")
    print(f"PostgreSQL Checkpoint Reads:  {read_rate:8.2f} ops/sec")

    assert write_rate > 50.0
    assert read_rate > 50.0


def test_benchmark_concurrent_worker_interleaving(pg_server: str) -> None:
    """Verify concurrency scaling with 5 parallel worker threads operating against PostgreSQL."""
    pg_storage = PostgresStorage(pg_server)
    pg_storage.initialize()

    num_workers = 5
    events_per_worker = 20
    now = datetime.now(UTC)

    from atlas_core.contracts.worker import WorkerRecord, WorkerStatus

    # Pre-create tasks and register workers
    for w in range(num_workers):
        task = Task(
            task_id=f"worker_task_{w}",
            objective=f"Concurrent worker task {w}",
            status=TaskStatus.RUNNING,
            created_at=now,
            updated_at=now,
        )
        pg_storage.save_task(task)

        worker_rec = WorkerRecord(
            worker_id=f"worker_{w}",
            hostname="worker-node-1",
            status=WorkerStatus.IDLE,
            capabilities=["browser", "desktop"],
            registered_at=now,
            last_heartbeat_at=now,
        )
        pg_storage.register_worker(worker_rec)

    def worker_action(worker_id: int) -> dict[str, Any]:
        task_id = f"worker_task_{worker_id}"
        t_start = time.perf_counter()

        # 1. Acquire lease
        lease = pg_storage.acquire_lease(
            task_id=task_id,
            worker_id=f"worker_{worker_id}",
            ttl_seconds=30.0,
        )
        assert lease.generation == 1

        # 2. Append events concurrently
        for seq in range(1, events_per_worker + 1):
            evt = ExecutionEvent(
                event_id=f"conc_evt_{worker_id}_{seq}",
                task_id=task_id,
                sequence=seq,
                event_type=EventType.ACTION_COMPLETED,
                timestamp=now,
                payload={"worker": worker_id, "step": seq},
                correlation_id=f"corr_worker_{worker_id}_{seq}",
            )
            pg_storage.append_event(evt)

        # 3. Renew lease
        renewed_lease = pg_storage.renew_lease(
            lease_id=lease.lease_id,
            worker_id=f"worker_{worker_id}",
            ttl_seconds=30.0,
        )
        assert renewed_lease.lease_id == lease.lease_id

        elapsed = time.perf_counter() - t_start
        return {"worker_id": worker_id, "elapsed": elapsed}

    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_action, w) for w in range(num_workers)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    total_elapsed = time.perf_counter() - t0

    # Verify all tasks have exact event count
    for w in range(num_workers):
        events = pg_storage.get_events(f"worker_task_{w}")
        assert len(events) == events_per_worker

    pg_storage.close()

    total_ops = num_workers * (1 + events_per_worker + 1)
    concurrency_ops_per_sec = total_ops / total_elapsed
    print(f"\n--- CONCURRENT WORKER INTERLEAVING ({num_workers} threads) ---")
    print(f"Total concurrent operations: {total_ops}")
    print(f"Total duration:              {total_elapsed:6.3f}s")
    print(f"Concurrent throughput:       {concurrency_ops_per_sec:8.2f} ops/sec")

    assert len(results) == num_workers
    assert concurrency_ops_per_sec > 100.0


def test_full_stack_postgres_deployment_lifecycle(
    pg_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify complete application stack startup, readiness, API operation, and graceful shutdown on PostgreSQL."""
    monkeypatch.setenv("ATLAS_DATABASE_URL", pg_server)
    monkeypatch.setenv("ATLAS_API_KEY_OPERATOR", "operator-key")
    monkeypatch.setenv("ATLAS_API_KEY_ADMIN", "admin-key")

    with TestClient(app) as client:
        # 1. Readiness probe
        ready_res = client.get("/readyz")
        assert ready_res.status_code == 200
        ready_data = ready_res.json()
        assert ready_data["status"] == "ok"
        assert ready_data["components"]["storage"] == "ok"

        # 2. Status probe
        status_res = client.get("/api/v1/status")
        assert status_res.status_code == 200
        assert status_res.json()["status"] == "ok"

        # 3. Submit task via REST API
        create_res = client.post(
            "/api/v1/tasks",
            headers={"Authorization": "Bearer operator-key"},
            json={
                "objective": "Verify PostgreSQL full-stack deployment",
                "priority": "HIGH",
            },
        )
        assert create_res.status_code == 201
        created_task = create_res.json()
        task_id = created_task["task_id"]
        assert task_id.startswith("task_")
        assert created_task["status"] in ("RUNNING", "CREATED", "QUEUED")

        # 4. Fetch task via REST API
        get_res = client.get(
            f"/api/v1/tasks/{task_id}",
            headers={"Authorization": "Bearer operator-key"},
        )
        assert get_res.status_code == 200
        fetched_task = get_res.json()
        assert fetched_task["task_id"] == task_id
        assert fetched_task["objective"] == "Verify PostgreSQL full-stack deployment"

        # 5. List tasks
        list_res = client.get(
            "/api/v1/tasks",
            headers={"Authorization": "Bearer operator-key"},
        )
        assert list_res.status_code == 200
        tasks = list_res.json()
        assert any(t["task_id"] == task_id for t in tasks)

        # 6. Check Prometheus metrics
        metrics_res = client.get("/metrics")
        assert metrics_res.status_code == 200
        assert "atlas_active_tasks" in metrics_res.text

    # After with-block exits, FastAPI lifespan shutdown executed cleanly
    # Verify we can still connect to Postgres and verify the task was persisted durably
    verify_storage = PostgresStorage(pg_server)
    verify_storage.initialize()
    persisted = verify_storage.get_task(task_id)
    assert persisted is not None
    assert persisted.task_id == task_id
    verify_storage.close()
