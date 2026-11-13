"""Unit tests verifying Milestone 3 performance baselines, task timeouts, and queue backpressure."""

import asyncio
import time

import pytest
from atlas_agent.runtime import ProductionRuntime, QueueBackpressureError
from atlas_api.main import app
from atlas_core.contracts.task import TaskPriority, TaskRequest, TaskStatus
from atlas_storage.sqlite import SQLiteStorage
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_queue_backpressure_rejection() -> None:
    """Verify runtime rejects submissions when pending task queue reaches max_queue_depth."""
    storage = SQLiteStorage(":memory:")
    storage.initialize()
    runtime = ProductionRuntime(storage=storage, max_queue_depth=2)
    await runtime.initialize()

    # Block workers with sleep coroutines in running tasks
    async def blocking_task():
        await asyncio.sleep(2.0)

    t1 = asyncio.create_task(blocking_task())
    t2 = asyncio.create_task(blocking_task())
    runtime._running_async_tasks["t1"] = t1
    runtime._running_async_tasks["t2"] = t2

    try:
        # Third task should trigger QueueBackpressureError
        req = TaskRequest(objective="Exceed queue depth")
        with pytest.raises(QueueBackpressureError, match="Task queue capacity exceeded"):
            await runtime.submit_task(req, wait_until_complete=False)
    finally:
        t1.cancel()
        t2.cancel()
        await runtime.shutdown()


def test_api_backpressure_returns_429() -> None:
    """Verify API returns HTTP 429 Too Many Requests when runtime queue is saturated."""
    storage = SQLiteStorage(":memory:")
    storage.initialize()
    app.state.storage = storage

    runtime = ProductionRuntime(storage=storage, max_queue_depth=1)
    app.state.runtime = runtime
    client = TestClient(app)

    class ActiveMockTask:
        def done(self) -> bool:
            return False

    runtime._running_async_tasks["active_1"] = ActiveMockTask()  # type: ignore

    try:
        res = client.post(
            "/api/v1/tasks",
            headers={"Authorization": "Bearer operator-key"},
            json={"objective": "Saturate queue"},
        )
        assert res.status_code == 429
        assert "Retry-After" in res.headers
        assert "Backpressure active" in res.json()["detail"]
    finally:
        app.state.storage = None
        app.state.runtime = None
        storage.close()


@pytest.mark.asyncio
async def test_task_execution_timeout() -> None:
    """Verify task transitions to FAILED when execution exceeds configured timeout limit."""
    storage = SQLiteStorage(":memory:")
    storage.initialize()
    runtime = ProductionRuntime(storage=storage, task_timeout_seconds=0.1)
    await runtime.initialize()

    # Mock agent loop with long execution delay
    class HangingLoop:
        async def run(self, task, session, budget=None):
            await asyncio.sleep(1.0)
            return task

    runtime.loop = HangingLoop()  # type: ignore

    try:
        req = TaskRequest(objective="Timeout check", metadata={"timeout_seconds": 0.05})
        task = await runtime.submit_task(req, wait_until_complete=True)
        assert task.status == TaskStatus.FAILED
        events = storage.get_events(task.task_id)
        failed_events = [e for e in events if e.payload.get("to_status") == "FAILED"]
        assert len(failed_events) >= 1
        assert "timeout limit" in failed_events[0].payload.get("reason", "")
    finally:
        await runtime.shutdown()


def test_performance_baselines() -> None:
    """Measure task creation throughput and state persistence latency."""
    storage = SQLiteStorage(":memory:")
    storage.initialize()

    start_time = time.perf_counter()
    iterations = 100

    from datetime import UTC, datetime

    from atlas_core.contracts.task import Task

    for i in range(iterations):
        now = datetime.now(UTC)
        task = Task(
            task_id=f"perf_task_{i}",
            objective="Baseline throughput benchmark",
            status=TaskStatus.RUNNING,
            priority=TaskPriority.NORMAL,
            created_at=now,
            updated_at=now,
        )
        storage.save_task(task)

    elapsed = time.perf_counter() - start_time
    tasks_per_sec = iterations / elapsed

    # Assert persistence throughput is comfortably above 200 tasks/second
    assert tasks_per_sec > 200.0, f"Throughput too low: {tasks_per_sec:.1f} tasks/sec"
    storage.close()
