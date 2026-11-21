"""Unit tests for ModelAdapter protocol and abstract contract."""

from collections.abc import AsyncIterator

import pytest
from atlas_core.contracts.model import (
    ModelCapabilities,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ProviderHealth,
)
from atlas_models.adapter import ModelAdapter


class DummyValidAdapter(ModelAdapter):
    """Concrete implementation of ModelAdapter for protocol verification."""

    def __init__(self, model_name: str = "dummy-model", provider: str = "dummy"):
        self._model_name = model_name
        self._provider = provider

    @property
    def name(self) -> str:
        return f"{self._provider}:{self._model_name}"

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            model_name=self._model_name,
            provider=self._provider,
            vision=True,
            tool_calling=True,
            context_window=64000,
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            response_id="resp_dummy",
            request_id=request.request_id,
            model_name=self._model_name,
            content="Dummy response",
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        yield "Dummy "
        yield "stream"

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            status="HEALTHY",
            provider_id=self._provider,
            model_name=self._model_name,
            latency_ms=10,
        )


def test_cannot_instantiate_abstract_model_adapter():
    """Verify ModelAdapter cannot be instantiated without implementing abstract methods."""
    with pytest.raises(TypeError):
        ModelAdapter()  # type: ignore


@pytest.mark.asyncio
async def test_concrete_model_adapter_lifecycle():
    """Verify concrete ModelAdapter fulfills lifecycle and returns typed contracts."""
    adapter = DummyValidAdapter(model_name="test-v1", provider="mock")

    assert adapter.name == "mock:test-v1"
    caps = adapter.get_capabilities()
    assert caps.model_name == "test-v1"
    assert caps.provider == "mock"
    assert caps.vision is True

    health = await adapter.health_check()
    assert health.status == "HEALTHY"
    assert health.provider_id == "mock"

    req = ModelRequest(
        request_id="req_test_1",
        task_id="task_test_1",
        model_name="test-v1",
        messages=[ModelMessage(role="user", content="Hello")],
    )
    resp = await adapter.complete(req)
    assert resp.response_id == "resp_dummy"
    assert resp.content == "Dummy response"

    chunks = []
    async for chunk in adapter.stream(req):
        chunks.append(chunk)
    assert "".join(chunks) == "Dummy stream"


def test_mask_credential_helper():
    """Verify credential sanitization helper properly masks secret values."""
    from atlas_models.adapter import mask_credential

    dummy_token = "sk-proj-" + "1234567890abcdef123456"
    assert mask_credential(dummy_token) == "sk-proj-1234...3456"
    assert mask_credential("short") == "***"
    assert mask_credential(None) == ""
