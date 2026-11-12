"""Unit tests for ModelRouter, CircuitBreaker, and CostTracker."""

from collections.abc import AsyncIterator

import pytest
from atlas_core.contracts.model import (
    ModelCapabilities,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ProviderHealth,
    TokenUsage,
)
from atlas_models.adapter import ModelAdapter
from atlas_models.router import CircuitBreaker, CircuitState, CostTracker, ModelRouter


class MockTestAdapter(ModelAdapter):
    """Configurable mock adapter for testing router failover and capability selection."""

    def __init__(
        self,
        name: str,
        provider: str = "mock",
        vision: bool = True,
        tools: bool = True,
        context_window: int = 128000,
        should_fail: bool = False,
        cost_per_1k_input: float = 0.001,
        cost_per_1k_output: float = 0.002,
    ) -> None:
        self._name = name
        self._provider = provider
        self._vision = vision
        self._tools = tools
        self._context_window = context_window
        self.should_fail = should_fail
        self._cost_in = cost_per_1k_input
        self._cost_out = cost_per_1k_output
        self.call_count = 0

    @property
    def name(self) -> str:
        return f"{self._provider}:{self._name}"

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            model_name=self._name,
            provider=self._provider,
            vision=self._vision,
            tool_calling=self._tools,
            context_window=self._context_window,
            cost_per_1k_input_tokens=self._cost_in,
            cost_per_1k_output_tokens=self._cost_out,
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError(f"Simulated failure from {self.name}")

        prompt_tokens = 100
        completion_tokens = 50
        cost = (prompt_tokens * self._cost_in + completion_tokens * self._cost_out) / 1000.0
        return ModelResponse(
            response_id=f"resp_{self._name}",
            request_id=request.request_id,
            model_name=self._name,
            content=f"Response from {self.name}",
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                estimated_cost_usd=cost,
            ),
        )

    def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        async def _gen():
            yield f"Stream from {self.name}"

        return _gen()

    async def health_check(self) -> ProviderHealth:
        if self.should_fail:
            return ProviderHealth(status="UNAVAILABLE", provider_id=self._provider, error="Down")
        return ProviderHealth(status="HEALTHY", provider_id=self._provider)


# ==============================================================================
# CircuitBreaker Tests
# ==============================================================================
def test_circuit_breaker_transitions():
    """Verify CircuitBreaker transitions from CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
    assert cb.state == CircuitState.CLOSED
    assert cb.can_attempt() is True

    # 1 failure
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED

    # 2 failures -> trips
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.can_attempt() is False

    # After recovery timeout
    import time

    time.sleep(0.12)
    assert cb.can_attempt() is True
    assert cb.state == CircuitState.HALF_OPEN

    # Success closes circuit
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


# ==============================================================================
# CostTracker Tests
# ==============================================================================
def test_cost_tracker_aggregation():
    """Verify CostTracker tracks tokens and estimated cost per task and in total."""
    tracker = CostTracker()
    usage1 = TokenUsage(
        prompt_tokens=100, completion_tokens=50, total_tokens=150, estimated_cost_usd=0.002
    )
    usage2 = TokenUsage(
        prompt_tokens=200, completion_tokens=100, total_tokens=300, estimated_cost_usd=0.004
    )

    tracker.record_usage("task-1", usage1)
    tracker.record_usage("task-1", usage2)
    tracker.record_usage("task-2", usage1)

    assert tracker.get_task_cost("task-1") == 0.006
    assert tracker.get_task_tokens("task-1")["total_tokens"] == 450
    assert tracker.get_task_cost("task-2") == 0.002
    assert tracker.get_total_cost() == 0.008
    assert tracker.get_total_tokens()["total_tokens"] == 600


# ==============================================================================
# ModelRouter Tests
# ==============================================================================
@pytest.mark.asyncio
async def test_model_router_capability_filtering():
    """Verify ModelRouter matches models based on required capabilities."""
    router = ModelRouter()
    adapter_text = MockTestAdapter("text-only", vision=False, tools=False, context_window=16000)
    adapter_vision = MockTestAdapter("vision-pro", vision=True, tools=True, context_window=128000)

    router.register_adapter(adapter_text, priority=1)
    router.register_adapter(adapter_vision, priority=2)

    # Requires vision
    matches = router.find_adapters(requires_vision=True)
    assert len(matches) == 1
    assert matches[0].name == "mock:vision-pro"

    # Context window requirement
    matches_ctx = router.find_adapters(min_context_window=32000)
    assert len(matches_ctx) == 1
    assert matches_ctx[0].name == "mock:vision-pro"


@pytest.mark.asyncio
async def test_model_router_fallback_on_failure():
    """Verify ModelRouter seamlessly falls back to backup adapter on primary failure."""
    router = ModelRouter()
    primary = MockTestAdapter("primary", should_fail=True)
    backup = MockTestAdapter("backup", should_fail=False)

    router.register_adapter(primary, priority=10)
    router.register_adapter(backup, priority=5)

    req = ModelRequest(
        request_id="req_route_1",
        task_id="task_route_1",
        model_name="primary",
        messages=[ModelMessage(role="user", content="Hello")],
    )

    resp = await router.complete(req, fallback=True)
    assert resp.content == "Response from mock:backup"
    assert primary.call_count == 1
    assert backup.call_count == 1

    # Verify primary circuit breaker recorded failure
    breaker = router.get_circuit_breaker(primary.name)
    assert breaker is not None
    assert breaker.failure_count == 1

    # Verify cost tracking recorded
    assert router.cost_tracker.get_task_cost("task_route_1") > 0


@pytest.mark.asyncio
async def test_model_router_health_checks():
    """Verify ModelRouter probes health across all registered adapters."""
    router = ModelRouter()
    healthy = MockTestAdapter("healthy", should_fail=False)
    down = MockTestAdapter("down", should_fail=True)

    router.register_adapter(healthy)
    router.register_adapter(down)

    health_map = await router.health_check_all()
    assert health_map[healthy.name].status == "HEALTHY"
    assert health_map[down.name].status == "UNAVAILABLE"
