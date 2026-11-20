"""Capability-aware ModelRouter with circuit breakers, rate limiting, and cost tracking."""

import asyncio
import logging
import time
from enum import StrEnum
from typing import Any

from atlas_core.contracts.model import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ProviderHealth,
    TokenUsage,
)

from atlas_models.adapter import ModelAdapter

logger = logging.getLogger("atlas.models.router")


class PaidRoutingBlockedError(RuntimeError):
    """Raised when strict free-only routing cannot prove an allowed route."""


class CircuitState(StrEnum):
    """Finite states of a provider circuit breaker."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Per-provider circuit breaker to prevent cascading failures to degraded endpoints."""

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        if self.failure_count >= self.failure_threshold:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                return CircuitState.HALF_OPEN
            return CircuitState.OPEN
        return CircuitState.CLOSED

    def can_attempt(self) -> bool:
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        self.failure_count = 0

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()


class CostTracker:
    """Aggregates prompt, completion, total tokens, and estimated USD costs."""

    def __init__(self) -> None:
        self._task_usage: dict[str, list[TokenUsage]] = {}
        self._total_prompt: int = 0
        self._total_completion: int = 0
        self._total_tokens: int = 0
        self._total_cost_usd: float = 0.0

    def record_usage(self, task_id: str, usage: TokenUsage | dict[str, Any]) -> None:
        if isinstance(usage, dict):
            u = TokenUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                estimated_cost_usd=float(usage.get("estimated_cost_usd", 0.0)),
            )
        else:
            u = usage

        if task_id not in self._task_usage:
            self._task_usage[task_id] = []
        self._task_usage[task_id].append(u)

        self._total_prompt += u.prompt_tokens
        self._total_completion += u.completion_tokens
        self._total_tokens += u.total_tokens
        self._total_cost_usd += u.estimated_cost_usd

    def get_task_cost(self, task_id: str) -> float:
        usages = self._task_usage.get(task_id, [])
        return round(sum(u.estimated_cost_usd for u in usages), 6)

    def get_task_tokens(self, task_id: str) -> dict[str, int]:
        usages = self._task_usage.get(task_id, [])
        return {
            "prompt_tokens": sum(u.prompt_tokens for u in usages),
            "completion_tokens": sum(u.completion_tokens for u in usages),
            "total_tokens": sum(u.total_tokens for u in usages),
        }

    def get_total_cost(self) -> float:
        return round(self._total_cost_usd, 6)

    def get_total_tokens(self) -> dict[str, int]:
        return {
            "prompt_tokens": self._total_prompt,
            "completion_tokens": self._total_completion,
            "total_tokens": self._total_tokens,
        }


class ModelRouter:
    """Manages adapter registration, capability routing, circuit breaking, and failover."""

    def __init__(
        self,
        *,
        free_only: bool = False,
        allowed_free_models: set[str] | None = None,
        default_free_model: str = "openrouter/free",
    ) -> None:
        self._adapters: dict[str, tuple[ModelAdapter, int]] = {}
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self.cost_tracker = CostTracker()
        self.free_only = free_only
        self.allowed_free_models = set(allowed_free_models or ())
        self.default_free_model = default_free_model

    def register_adapter(self, adapter: ModelAdapter, priority: int = 0) -> None:
        """Register an adapter with a preference priority (higher number = preferred)."""
        self._adapters[adapter.name] = (adapter, priority)
        if adapter.name not in self._circuit_breakers:
            self._circuit_breakers[adapter.name] = CircuitBreaker()

    def get_adapter(self, name_or_model: str) -> ModelAdapter | None:
        """Find an adapter by its full name or model identifier."""
        if name_or_model in self._adapters:
            return self._adapters[name_or_model][0]
        for adapter, _ in self._adapters.values():
            caps = adapter.get_capabilities()
            if caps.model_name == name_or_model:
                return adapter
        return None

    def get_circuit_breaker(self, adapter_name: str) -> CircuitBreaker | None:
        return self._circuit_breakers.get(adapter_name)

    def find_adapters(
        self,
        requires_vision: bool = False,
        requires_tools: bool = False,
        min_context_window: int = 0,
    ) -> list[ModelAdapter]:
        """Filter adapters matching criteria, sorted by descending priority."""
        matching = []
        for adapter, priority in self._adapters.values():
            caps: ModelCapabilities = adapter.get_capabilities()
            if requires_vision and not caps.vision:
                continue
            if requires_tools and not caps.tool_calling:
                continue
            if caps.context_window < min_context_window:
                continue
            matching.append((adapter, priority))

        matching.sort(key=lambda item: item[1], reverse=True)
        return [adapter for adapter, _ in matching]

    async def complete(self, request: ModelRequest, fallback: bool = True) -> ModelResponse:
        """Execute a completion using the designated or optimal matching adapter with fallback."""
        requested_model = request.model_name or self.default_free_model
        if requested_model in {"default", "free", "auto"}:
            requested_model = self.default_free_model
        if self.free_only and requested_model not in self.allowed_free_models:
            raise PaidRoutingBlockedError(
                f"Model '{requested_model}' is not in the currently verified free-model catalogue."
            )
        if requested_model != request.model_name:
            request = request.model_copy(update={"model_name": requested_model})
        candidates: list[ModelAdapter] = []

        # 1. Target specific model if requested
        if request.model_name:
            exact = self.get_adapter(request.model_name)
            if exact:
                candidates.append(exact)

        # Strict free routing never fails over to a different model/provider.
        if not self.free_only:
            sorted_all = sorted(self._adapters.values(), key=lambda item: item[1], reverse=True)
            for adapter, _ in sorted_all:
                if adapter not in candidates:
                    candidates.append(adapter)

        if not candidates:
            message = f"No configured adapter for allowed model '{requested_model}'."
            if self.free_only:
                raise PaidRoutingBlockedError(message)
            raise RuntimeError("No model adapters registered in ModelRouter")

        last_error: Exception | None = None

        for adapter in candidates:
            breaker = self._circuit_breakers.get(adapter.name)
            if breaker and not breaker.can_attempt():
                logger.warning(
                    f"Circuit breaker for {adapter.name} is OPEN (state={breaker.state}). Skipping."
                )
                if not fallback:
                    break
                continue

            # Attempt completion with retry backoff for rate limits
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    resp = await adapter.complete(request)
                    if breaker:
                        breaker.record_success()
                    self.cost_tracker.record_usage(request.task_id, resp.usage)
                    return resp
                except Exception as exc:
                    err_str = str(exc)
                    is_rate_limit = (
                        "429" in err_str or "RATE_LIMIT" in err_str or "Rate limit" in err_str
                    )
                    if is_rate_limit and attempt < max_retries:
                        backoff = 1.0 * (2**attempt)
                        logger.warning(
                            f"Rate limit on {adapter.name}. Retrying in {backoff}s (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(backoff)
                        continue

                    # Record failure on breaker
                    if breaker:
                        breaker.record_failure()
                    last_error = exc
                    logger.warning("Adapter %s failed (%s).", adapter.name, type(exc).__name__)
                    break  # Move to next candidate adapter

            if not fallback:
                break

        if self.free_only:
            raise PaidRoutingBlockedError(
                f"Free route '{requested_model}' failed: {last_error}"
            ) from last_error
        raise RuntimeError(f"All model adapters failed. Last error: {last_error}")

    async def health_check_all(self) -> dict[str, ProviderHealth]:
        """Probe all registered adapters and return health map."""
        results = {}
        for name, (adapter, _) in self._adapters.items():
            results[name] = await adapter.health_check()
        return results
