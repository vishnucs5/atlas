"""Unit tests for Resource-Aware Distributed Scheduler (Milestone 3)."""

import pytest
from atlas_distributed.enrollment import WorkerEnrollmentAuthority
from atlas_distributed.models import (
    EnrollmentRequest,
    SessionType,
    WorkerCapabilities,
    WorkerHardware,
    WorkerPlatform,
)
from atlas_distributed.scheduler import (
    DistributedScheduler,
    NoEligibleWorkerError,
    SchedulerQueueFullError,
    TaskRequirements,
)


@pytest.fixture
def authority() -> WorkerEnrollmentAuthority:
    return WorkerEnrollmentAuthority()


def enroll_worker(
    authority: WorkerEnrollmentAuthority,
    tenant_id: str = "default",
    platform: WorkerPlatform = WorkerPlatform.LINUX,
    session_type: SessionType = SessionType.HEADLESS,
    drivers: list[str] | None = None,
    browsers: list[str] | None = None,
    cpu_cores: int = 4,
    memory_bytes: int = 8 * 1024 * 1024 * 1024,
    has_gpu: bool = False,
    max_concurrent_tasks: int = 2,
    tags: list[str] | None = None,
):
    token, _ = authority.create_enrollment_token(tenant_id=tenant_id)
    caps = WorkerCapabilities(
        platform=platform,
        session_type=session_type,
        drivers=drivers or ["bash", "playwright"],
        browsers=browsers or ["chromium"],
        hardware=WorkerHardware(
            cpu_cores=cpu_cores,
            memory_bytes=memory_bytes,
            has_gpu=has_gpu,
        ),
        max_concurrent_tasks=max_concurrent_tasks,
        tags=tags or [],
    )
    req = EnrollmentRequest(
        provisioning_token=token,
        hostname=f"node-{platform.value}",
        capabilities=caps,
        tenant_id=tenant_id,
    )
    return authority.enroll_worker(req)


def test_platform_and_driver_matching(authority):
    """Verify scheduler matches tasks to workers with matching OS and drivers."""
    enroll_worker(authority, platform=WorkerPlatform.LINUX, drivers=["bash"])
    enroll_worker(
        authority,
        platform=WorkerPlatform.WINDOWS,
        session_type=SessionType.INTERACTIVE_USER,
        drivers=["cmd", "desktop"],
    )

    scheduler = DistributedScheduler(enrollment_authority=authority)

    # Task requiring Windows + desktop driver
    req_win = TaskRequirements(
        task_id="t_win",
        required_platform=WorkerPlatform.WINDOWS,
        required_drivers=["desktop"],
    )
    worker_win, payload_win = scheduler.schedule_task(req_win)
    assert worker_win.capabilities.platform == WorkerPlatform.WINDOWS
    assert "desktop" in worker_win.capabilities.drivers
    assert payload_win.worker_id == worker_win.worker_id

    # Task requiring Linux + bash
    req_lin = TaskRequirements(
        task_id="t_lin",
        required_platform=WorkerPlatform.LINUX,
        required_drivers=["bash"],
    )
    worker_lin, payload_lin = scheduler.schedule_task(req_lin)
    assert worker_lin.capabilities.platform == WorkerPlatform.LINUX
    assert payload_lin.worker_id == worker_lin.worker_id


def test_windows_session_zero_protection(authority):
    """Verify scheduler strictly rejects Windows Session 0 workers for interactive tasks."""
    # Worker 1: Windows Session 0 (service mode, GUI detached)
    enroll_worker(
        authority,
        platform=WorkerPlatform.WINDOWS,
        session_type=SessionType.SESSION_0,
        drivers=["cmd"],
    )

    scheduler = DistributedScheduler(enrollment_authority=authority)

    # Interactive desktop task
    interactive_task = TaskRequirements(
        task_id="t_interactive",
        requires_interactive_desktop=True,
    )

    # Session 0 worker must be rejected
    with pytest.raises(NoEligibleWorkerError) as exc_info:
        scheduler.schedule_task(interactive_task)

    assert "Session 0 rejected" in str(exc_info.value) or "lacks interactive desktop" in str(
        exc_info.value
    )

    # Now enroll Worker 2: Windows Interactive User Session with desktop capability
    enroll_worker(
        authority,
        platform=WorkerPlatform.WINDOWS,
        session_type=SessionType.INTERACTIVE_USER,
        drivers=["cmd", "desktop"],
    )

    # Scheduling should now succeed on Worker 2
    worker, payload = scheduler.schedule_task(interactive_task)
    assert worker.capabilities.session_type == SessionType.INTERACTIVE_USER
    assert payload.worker_id == worker.worker_id


def test_tenant_isolation(authority):
    """Verify tasks from tenant-A never get scheduled on tenant-B workers."""
    enroll_worker(authority, tenant_id="tenant-alpha")
    enroll_worker(authority, tenant_id="tenant-beta")

    scheduler = DistributedScheduler(enrollment_authority=authority)

    req_alpha = TaskRequirements(task_id="t_alpha", tenant_id="tenant-alpha")
    worker_a, payload_a = scheduler.schedule_task(req_alpha)
    assert worker_a.tenant_id == "tenant-alpha"
    assert payload_a.tenant_id == "tenant-alpha"

    req_gamma = TaskRequirements(task_id="t_gamma", tenant_id="tenant-gamma")
    with pytest.raises(NoEligibleWorkerError) as exc_info:
        scheduler.schedule_task(req_gamma)
    assert "tenant mismatch" in str(exc_info.value)


def test_hardware_constraints(authority):
    """Verify GPU and memory constraints are enforced during worker matching."""
    enroll_worker(
        authority,
        cpu_cores=4,
        memory_bytes=4 * 1024 * 1024 * 1024,
        has_gpu=False,
    )
    enroll_worker(
        authority,
        cpu_cores=16,
        memory_bytes=32 * 1024 * 1024 * 1024,
        has_gpu=True,
    )

    scheduler = DistributedScheduler(enrollment_authority=authority)

    # High RAM and GPU required
    req = TaskRequirements(
        task_id="t_gpu",
        min_cpu_cores=8,
        min_memory_bytes=16 * 1024 * 1024 * 1024,
        require_gpu=True,
    )
    worker, _ = scheduler.schedule_task(req)
    assert worker.capabilities.hardware.has_gpu is True
    assert worker.capabilities.hardware.cpu_cores >= 8


def test_concurrency_and_load_balancing_fairness(authority):
    """Verify least-loaded selection and concurrency limits."""
    # Worker 1 and Worker 2 both identical
    enroll_worker(authority, max_concurrent_tasks=2)
    enroll_worker(authority, max_concurrent_tasks=2)

    scheduler = DistributedScheduler(enrollment_authority=authority)

    # First task: should pick either worker
    w1, p1 = scheduler.schedule_task(TaskRequirements(task_id="t1"))

    # Second task: should balance load to the other worker
    w2, p2 = scheduler.schedule_task(TaskRequirements(task_id="t2"))
    assert w1.worker_id != w2.worker_id

    # Third and fourth tasks fill remaining capacity
    w3, p3 = scheduler.schedule_task(TaskRequirements(task_id="t3"))
    w4, p4 = scheduler.schedule_task(TaskRequirements(task_id="t4"))

    # Fifth task: all capacity exhausted (2 workers * 2 tasks = 4 tasks)
    with pytest.raises(NoEligibleWorkerError) as exc_info:
        scheduler.schedule_task(TaskRequirements(task_id="t5"))
    assert "capacity exhausted" in str(exc_info.value)


def test_monotonic_fencing_token_allocation(authority):
    """Verify task leases receive monotonically increasing generation fencing tokens."""
    enroll_worker(authority)
    scheduler = DistributedScheduler(enrollment_authority=authority)

    # Schedule same task twice (e.g. after recovery or timeout)
    _, p1 = scheduler.schedule_task(TaskRequirements(task_id="task_fenced"))
    assert p1.generation == 1

    _, p2 = scheduler.schedule_task(TaskRequirements(task_id="task_fenced"))
    assert p2.generation == 2
    assert p2.generation > p1.generation


def test_priority_queue_and_queue_drain(authority):
    """Verify priority-ordered queuing and queue draining upon task completion."""
    enroll_worker(authority, max_concurrent_tasks=1)
    scheduler = DistributedScheduler(enrollment_authority=authority)

    # Occupy the single worker
    _, p_active = scheduler.schedule_task(TaskRequirements(task_id="active_task"))

    # Submit low priority task (will be queued)
    with pytest.raises(NoEligibleWorkerError):
        scheduler.submit_task(TaskRequirements(task_id="low_pri", priority=5))

    # Submit high priority task (will be queued higher)
    with pytest.raises(NoEligibleWorkerError):
        scheduler.submit_task(TaskRequirements(task_id="high_pri", priority=50))

    assert scheduler.get_queue_depth() == 2

    # Complete the active task; should automatically drain high_pri first!
    scheduler.complete_task(p_active.assignment_id)

    # Queue depth should now be 1 (high_pri dispatched, low_pri still waiting)
    assert scheduler.get_queue_depth() == 1


def test_scheduler_backpressure(authority):
    """Verify backpressure error when queue depth exceeds maximum configured depth."""
    enroll_worker(authority, max_concurrent_tasks=1)
    scheduler = DistributedScheduler(enrollment_authority=authority, max_queue_depth=2)

    # Fill worker
    scheduler.schedule_task(TaskRequirements(task_id="active"))

    # Queue up to limit (2 tasks)
    with pytest.raises(NoEligibleWorkerError):
        scheduler.submit_task(TaskRequirements(task_id="q1"))
    with pytest.raises(NoEligibleWorkerError):
        scheduler.submit_task(TaskRequirements(task_id="q2"))

    assert scheduler.get_queue_depth() == 2

    # Exceed limit: should raise SchedulerQueueFullError
    with pytest.raises(SchedulerQueueFullError) as exc_info:
        scheduler.submit_task(TaskRequirements(task_id="q3"))
    assert "queue depth limit reached" in str(exc_info.value)
