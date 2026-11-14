"""Production resilience patterns: Circuit Breakers and Bulkhead Concurrency Throttling."""

from __future__ import annotations

import asyncio
import enum
import functools
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class CircuitState(enum.StrEnum):
    """Lifecycle states of a circuit breaker."""

    CLOSED = "CLOSED"  # Normal traffic flow; requests pass through
    OPEN = "OPEN"  # Tripped due to failure threshold; requests fail-fast
    HALF_OPEN = "HALF_OPEN"  # Testing downstream health with controlled probe requests


class CircuitBreakerOpenError(Exception):
    """Raised when an operation is rejected by an OPEN circuit breaker."""

    def __init__(self, name: str, retry_after_seconds: float, failure_count: int) -> None:
        super().__init__(
            f"Circuit breaker '{name}' is OPEN (fast-failing). "
            f"Retry after {retry_after_seconds:.1f}s. Concluded {failure_count} consecutive failures."
        )
        self.name = name
        self.retry_after_seconds = retry_after_seconds
        self.failure_count = failure_count


class BulkheadRejectedError(Exception):
    """Raised when an operation exceeds maximum concurrent executions and queue capacity."""

    def __init__(self, name: str, active: int, max_concurrent: int, queue_depth: int) -> None:
        super().__init__(
            f"Bulkhead '{name}' saturated: {active}/{max_concurrent} active, queue depth {queue_depth}. Execution rejected."
        )
        self.name = name
        self.active = active
        self.max_concurrent = max_concurrent
        self.queue_depth = queue_depth


class CircuitBreaker:
    """Thread-safe and async-safe Circuit Breaker pattern implementation."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2,
        expected_exceptions: tuple[type[Exception], ...] | None = None,
    ) -> None:
        self.name = name
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout = max(0.1, recovery_timeout)
        self.success_threshold = max(1, success_threshold)
        self.expected_exceptions = expected_exceptions or (Exception,)

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_state_change = time.monotonic()
        self._lock = threading.RLock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._evaluate_state()
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    def _evaluate_state(self) -> None:
        """Internal transition from OPEN to HALF_OPEN after recovery timeout."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_state_change
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                self._last_state_change = time.monotonic()

    def record_success(self) -> None:
        """Record a successful downstream invocation."""
        with self._lock:
            self._evaluate_state()
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._last_state_change = time.monotonic()
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    def record_failure(self, exc: Exception) -> None:
        """Record a downstream invocation failure."""
        if not isinstance(exc, self.expected_exceptions):
            return

        with self._lock:
            self._evaluate_state()
            self._failure_count += 1
            if self._state in (CircuitState.CLOSED, CircuitState.HALF_OPEN):
                if (
                    self._state == CircuitState.HALF_OPEN
                    or self._failure_count >= self.failure_threshold
                ):
                    self._state = CircuitState.OPEN
                    self._last_state_change = time.monotonic()

    def check_permission(self) -> None:
        """Check whether execution is permitted; raises CircuitBreakerOpenError if OPEN."""
        with self._lock:
            self._evaluate_state()
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_state_change
                remaining = max(0.0, self.recovery_timeout - elapsed)
                raise CircuitBreakerOpenError(
                    name=self.name,
                    retry_after_seconds=remaining,
                    failure_count=self._failure_count,
                )

    def __call__(self, fn: Callable[..., T]) -> Callable[..., T]:
        """Decorator for protecting synchronous and asynchronous functions."""
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                self.check_permission()
                try:
                    res = await fn(*args, **kwargs)
                    self.record_success()
                    return res
                except Exception as exc:
                    self.record_failure(exc)
                    raise

            return async_wrapper  # type: ignore

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            self.check_permission()
            try:
                res = fn(*args, **kwargs)
                self.record_success()
                return res
            except Exception as exc:
                self.record_failure(exc)
                raise

        return sync_wrapper

    def reset(self) -> None:
        """Force manual reset to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_state_change = time.monotonic()


class Bulkhead:
    """Thread-safe and async-safe Concurrency Throttler / Bulkhead."""

    def __init__(
        self,
        name: str,
        max_concurrent: int = 10,
        max_queued: int = 20,
        queue_timeout: float = 5.0,
    ) -> None:
        self.name = name
        self.max_concurrent = max(1, max_concurrent)
        self.max_queued = max(0, max_queued)
        self.queue_timeout = max(0.0, queue_timeout)

        self._active_count = 0
        self._queued_count = 0
        self._lock = threading.Condition(threading.Lock())

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active_count

    @property
    def queued_count(self) -> int:
        with self._lock:
            return self._queued_count

    def acquire(self) -> bool:
        """Attempt to acquire a concurrent execution slot, waiting up to queue_timeout."""
        with self._lock:
            if self._active_count < self.max_concurrent:
                self._active_count += 1
                return True

            if self._queued_count >= self.max_queued:
                raise BulkheadRejectedError(
                    name=self.name,
                    active=self._active_count,
                    max_concurrent=self.max_concurrent,
                    queue_depth=self._queued_count,
                )

            # Enqueue and wait
            self._queued_count += 1
            deadline = time.monotonic() + self.queue_timeout
            try:
                while self._active_count >= self.max_concurrent:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise BulkheadRejectedError(
                            name=self.name,
                            active=self._active_count,
                            max_concurrent=self.max_concurrent,
                            queue_depth=self._queued_count,
                        )
                    self._lock.wait(timeout=remaining)

                self._active_count += 1
                return True
            finally:
                self._queued_count -= 1

    def release(self) -> None:
        """Release an execution slot and signal waiting callers."""
        with self._lock:
            self._active_count = max(0, self._active_count - 1)
            self._lock.notify()

    def __enter__(self) -> Bulkhead:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()

    async def __aenter__(self) -> Bulkhead:
        # Run blocking condition in executor or non-blocking async acquire
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.acquire)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()
