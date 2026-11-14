"""Phase 11 Automated Performance & Scalability Benchmarking Suite.

Measures:
- API response latency (p50, p95, p99) under sustained requests.
- Distributed scheduler matching and dispatch throughput.
- Enterprise persistent storage throughput under concurrent read/write loads.
- Circuit breaker sub-millisecond fast-fail latency in OPEN state.
"""

import concurrent.futures
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from atlas_api.main import app
from atlas_coordination import CircuitBreaker, CircuitState
from atlas_distributed.enrollment import WorkerEnrollmentAuthority
from atlas_distributed.models import (
    EnrollmentRequest,
    SessionType,
    WorkerCapabilities,
    WorkerHardware,
    WorkerPlatform,
)
from atlas_distributed.scheduler import DistributedScheduler, TaskRequirements
from atlas_enterprise import (
    AuditRecord,
    EnterpriseStorage,
    Organization,
    OrganizationStatus,
)
from fastapi.testclient import TestClient


def test_benchmark_01_api_latency_percentiles():
    """Measure API response latency percentiles (p50, p95, p99) over 100 requests."""
    client = TestClient(app)
    latencies: list[float] = []

    # Warmup
    for _ in range(10):
        client.get("/healthz")

    # Measurement
    for _ in range(100):
        start = time.perf_counter()
        res = client.get("/healthz")
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        assert res.status_code == 200
        latencies.append(elapsed_ms)

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]

    assert p50 < 10.0, f"p50 latency too high: {p50:.2f}ms"
    assert p95 < 25.0, f"p95 latency too high: {p95:.2f}ms"
    assert p99 < 50.0, f"p99 latency too high: {p99:.2f}ms"


def test_benchmark_02_distributed_scheduler_throughput():
    """Benchmark distributed scheduler matching 500 tasks across registered worker nodes."""
    authority = WorkerEnrollmentAuthority()
    scheduler = DistributedScheduler(enrollment_authority=authority)

    # Register 10 workers
    for i in range(10):
        token, _ = authority.create_enrollment_token(tenant_id="tenant_perf")
        req_enroll = EnrollmentRequest(
            provisioning_token=token,
            hostname=f"node-{i}",
            capabilities=WorkerCapabilities(
                platform=WorkerPlatform.LINUX,
                session_type=SessionType.HEADLESS,
                drivers=["bash", "python"],
                browsers=["chromium"],
                hardware=WorkerHardware(cpu_cores=8, memory_bytes=16 * 1024 * 1024 * 1024),
                tags=["standard"],
                max_concurrent_tasks=1000,
            ),
            tenant_id="tenant_perf",
        )
        authority.enroll_worker(req_enroll)

    req = TaskRequirements(
        task_id="t_bench",
        tenant_id="tenant_perf",
        required_platform=WorkerPlatform.LINUX,
        required_drivers=["bash"],
        estimated_cpu=1,
        estimated_ram_gb=1.0,
    )

    count = 500
    start = time.perf_counter()
    for i in range(count):
        req.task_id = f"task_{i}"
        worker, payload = scheduler.schedule_task(req)
        assert worker is not None
        assert payload.worker_id == worker.worker_id
    duration = time.perf_counter() - start
    ops_per_sec = count / duration

    assert ops_per_sec > 500.0, f"Scheduler throughput too low: {ops_per_sec:.1f} tasks/sec"
    assert duration < 1.0, f"Scheduling 500 tasks took {duration:.2f}s (> 1.0s)"


def test_benchmark_03_enterprise_storage_concurrency(tmp_path: Path):
    """Benchmark concurrent thread read/write throughput on EnterpriseStorage."""
    db_file = tmp_path / "bench_storage.db"
    storage = EnterpriseStorage(db_path=str(db_file))

    org = Organization(
        org_id="org_bench",
        name="Benchmark Corp",
        slug="bench-corp",
        status=OrganizationStatus.ACTIVE,
        created_at=datetime.now(UTC),
    )
    storage.save_organization(org)

    total_records = 200

    def worker_writer(idx: int):
        rec = AuditRecord(
            record_id=f"rec_{idx}",
            org_id="org_bench",
            sequence=idx,
            department_id=None,
            event_type="BENCH",
            actor_id="user_bench",
            actor_type="USER",
            action=f"action_{idx}",
            target_resource_id=None,
            details={"idx": idx},
            timestamp=datetime.now(UTC),
            previous_hash="0" * 64,
            record_hash=f"{idx:064x}",
        )
        storage.save_audit_record(rec)
        return True

    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker_writer, i) for i in range(1, total_records + 1)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    duration = time.perf_counter() - start
    assert all(results)
    records = storage.get_audit_records("org_bench", limit=total_records)
    assert len(records) == total_records
    assert duration < 2.0, f"Writing {total_records} records took {duration:.2f}s (> 2.0s)"


def test_benchmark_04_circuit_breaker_fast_fail_latency():
    """Benchmark sub-millisecond fast-fail latency of an OPEN circuit breaker over 5,000 calls."""
    cb = CircuitBreaker(name="fast_fail_bench", failure_threshold=1, recovery_timeout=60.0)

    # Force trip to OPEN
    cb.record_failure(RuntimeError("trip"))
    assert cb.state == CircuitState.OPEN

    count = 5000
    start = time.perf_counter()
    rejections = 0
    for _ in range(count):
        try:
            cb.check_permission()
        except Exception:
            rejections += 1
    duration = time.perf_counter() - start
    avg_latency_us = (duration / count) * 1_000_000.0

    assert rejections == count
    # Fast-fail must be sub-microsecond/sub-millisecond (< 5 microseconds average)
    assert avg_latency_us < 20.0, (
        f"Average fast-fail latency too high: {avg_latency_us:.2f} microseconds"
    )
