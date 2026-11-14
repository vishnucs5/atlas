"""Unit tests for CircuitBreaker and Bulkhead concurrency throttler."""

import asyncio
import time

import pytest
from atlas_coordination import (
    Bulkhead,
    BulkheadRejectedError,
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
)


def test_circuit_breaker_transitions_closed_to_open_to_half_open_to_closed():
    """Verify circuit breaker lifecycle and state machine."""
    cb = CircuitBreaker(
        name="test_service",
        failure_threshold=3,
        recovery_timeout=0.2,
        success_threshold=2,
    )
    assert cb.state == CircuitState.CLOSED

    # 1. Successful executions remain CLOSED
    @cb
    def reliable_call(val: int) -> int:
        return val * 2

    assert reliable_call(5) == 10
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0

    # 2. Consecutive failures trip breaker to OPEN
    @cb
    def failing_call():
        raise ConnectionResetError("downstream timeout")

    for _ in range(2):
        with pytest.raises(ConnectionResetError):
            failing_call()
        assert cb.state == CircuitState.CLOSED

    # 3rd failure trips breaker
    with pytest.raises(ConnectionResetError):
        failing_call()
    assert cb.state == CircuitState.OPEN

    # 3. OPEN state fast-fails without executing function
    with pytest.raises(CircuitBreakerOpenError) as exc_info:
        reliable_call(10)
    assert exc_info.value.name == "test_service"
    assert exc_info.value.failure_count == 3

    # 4. Wait for recovery timeout -> transitions to HALF_OPEN
    time.sleep(0.25)
    assert cb.state == CircuitState.HALF_OPEN

    # 5. Probe request succeeds
    assert reliable_call(7) == 14
    # Requires 2 consecutive successes in HALF_OPEN to close
    assert cb.state == CircuitState.HALF_OPEN

    assert reliable_call(8) == 16
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_async_circuit_breaker():
    """Verify circuit breaker wraps async coroutine functions."""
    cb = CircuitBreaker(name="async_service", failure_threshold=2, recovery_timeout=0.1)

    @cb
    async def async_op(x: int) -> int:
        await asyncio.sleep(0.01)
        if x < 0:
            raise ValueError("negative")
        return x + 1

    assert await async_op(5) == 6

    with pytest.raises(ValueError):
        await async_op(-1)
    with pytest.raises(ValueError):
        await async_op(-1)

    assert cb.state == CircuitState.OPEN
    with pytest.raises(CircuitBreakerOpenError):
        await async_op(5)


def test_bulkhead_concurrency_and_rejection():
    """Verify Bulkhead concurrency isolation and rejection on queue saturation."""
    bulkhead = Bulkhead(name="test_bulkhead", max_concurrent=2, max_queued=1, queue_timeout=0.05)

    acquired_1 = bulkhead.acquire()
    acquired_2 = bulkhead.acquire()
    assert acquired_1 is True
    assert acquired_2 is True
    assert bulkhead.active_count == 2

    # 3rd request would be queued; but 4th request exceeds max_queued and is rejected immediately
    import threading

    def queued_worker():
        try:
            bulkhead.acquire()
            time.sleep(0.02)
            bulkhead.release()
        except Exception:
            pass

    t = threading.Thread(target=queued_worker)
    t.start()
    time.sleep(0.01)  # Allow thread to enter queue
    assert bulkhead.queued_count == 1

    # Now with max_queued=1 reached, any additional request is immediately rejected
    with pytest.raises(BulkheadRejectedError) as exc_info:
        bulkhead.acquire()
    assert exc_info.value.name == "test_bulkhead"
    assert exc_info.value.active == 2

    bulkhead.release()
    bulkhead.release()
    t.join()
