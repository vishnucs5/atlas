"""Comprehensive unit tests for ATLAS Model Contracts (Phase 3)."""

import sys
from datetime import UTC, datetime

import pytest
from atlas_core.contracts.model import (
    ImagePart,
    ModelCapabilities,
    ModelError,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ProviderHealth,
    TextPart,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)
from pydantic import ValidationError


def test_text_and_image_parts_serialization():
    """Verify multimodal parts serialize and validate correctly."""
    text_part = TextPart(text="Hello world")
    assert text_part.type == "text"
    assert text_part.text == "Hello world"
    assert text_part.schema_version == "1.0"

    img_part = ImagePart(
        media_type="image/png",
        data="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
        detail="high",
    )
    assert img_part.type == "image"
    assert img_part.media_type == "image/png"
    assert img_part.detail == "high"
    assert img_part.data is not None

    # Test round trip JSON
    dumped = img_part.model_dump_json()
    reloaded = ImagePart.model_validate_json(dumped)
    assert reloaded.media_type == "image/png"
    assert reloaded.detail == "high"


def test_model_message_multimodal():
    """Verify ModelMessage accepts both string content and multimodal parts list."""
    # Text message
    msg1 = ModelMessage(role="user", content="Describe this image")
    assert msg1.role == "user"
    assert msg1.content == "Describe this image"
    assert msg1.schema_version == "1.0"

    # Multimodal message
    msg2 = ModelMessage(
        role="user",
        content=[
            TextPart(text="What is in this image?"),
            ImagePart(media_type="image/jpeg", url="https://example.com/test.jpg"),
        ],
    )
    assert isinstance(msg2.content, list)
    assert len(msg2.content) == 2
    assert msg2.content[0].type == "text"
    assert msg2.content[1].type == "image"

    # Tool message with tool_call_id
    msg3 = ModelMessage(
        role="tool",
        tool_call_id="call_12345",
        name="browser_click",
        content='{"status": "ok"}',
    )
    assert msg3.role == "tool"
    assert msg3.tool_call_id == "call_12345"
    assert msg3.name == "browser_click"


def test_tool_definition_and_tool_call():
    """Verify ToolDefinition and ToolCall schema structures and validation."""
    tool_def = ToolDefinition(
        name="browser_navigate",
        description="Navigates to the specified URL",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    )
    assert tool_def.name == "browser_navigate"
    assert "url" in tool_def.parameters["properties"]

    tool_call = ToolCall(
        id="call_999",
        name="browser_navigate",
        arguments={"url": "https://example.com"},
    )
    assert tool_call.id == "call_999"
    assert tool_call.name == "browser_navigate"
    assert tool_call.arguments["url"] == "https://example.com"
    assert tool_call.type == "function"

    # Verify JSON round-trip
    reloaded = ToolCall.model_validate_json(tool_call.model_dump_json())
    assert reloaded.arguments == {"url": "https://example.com"}


def test_token_usage_and_cost_accounting():
    """Verify TokenUsage records prompt, completion, total, and cost."""
    usage = TokenUsage(
        prompt_tokens=1500,
        completion_tokens=250,
        total_tokens=1750,
        cached_tokens=500,
        estimated_cost_usd=0.0052,
    )
    assert usage.prompt_tokens == 1500
    assert usage.completion_tokens == 250
    assert usage.total_tokens == 1750
    assert usage.cached_tokens == 500
    assert usage.estimated_cost_usd == 0.0052
    assert usage.schema_version == "1.0"


def test_provider_health():
    """Verify ProviderHealth diagnostic records."""
    now = datetime.now(UTC)
    health = ProviderHealth(
        status="HEALTHY",
        provider_id="openai",
        model_name="gpt-4o",
        latency_ms=180,
        last_checked_at=now,
    )
    assert health.status == "HEALTHY"
    assert health.provider_id == "openai"
    assert health.latency_ms == 180
    assert health.error is None

    # Degraded status
    degraded = ProviderHealth(
        status="DEGRADED",
        provider_id="anthropic",
        error="High latency detected: 2500ms",
    )
    assert degraded.status == "DEGRADED"
    assert degraded.error is not None


def test_model_error_normalization():
    """Verify ModelError classifies standardized error types."""
    err = ModelError(
        error_type="RATE_LIMIT",
        message="Too many requests; back off for 10 seconds",
        provider="openai",
        status_code=429,
        retryable=True,
        raw_error={"error": {"code": "rate_limit_exceeded"}},
    )
    assert err.error_type == "RATE_LIMIT"
    assert err.retryable is True
    assert err.status_code == 429
    assert err.provider == "openai"

    # Invalid error type should raise ValidationError
    with pytest.raises(ValidationError):
        ModelError(error_type="INVALID_ERROR_TYPE", message="Invalid")


def test_model_capabilities_extended():
    """Verify ModelCapabilities supports extended attributes and pricing."""
    caps = ModelCapabilities(
        model_name="claude-3-5-sonnet",
        provider="anthropic",
        vision=True,
        tool_calling=True,
        structured_output=True,
        streaming=True,
        context_window=200000,
        max_output_tokens=8192,
        cost_per_1k_input_tokens=0.003,
        cost_per_1k_output_tokens=0.015,
    )
    assert caps.model_name == "claude-3-5-sonnet"
    assert caps.provider == "anthropic"
    assert caps.context_window == 200000
    assert caps.cost_per_1k_input_tokens == 0.003
    assert caps.cost_per_1k_output_tokens == 0.015


def test_model_request_and_response_backward_compatibility():
    """Verify ModelRequest and ModelResponse accept both Pydantic models and plain dicts."""
    # Test with typed models
    msg = ModelMessage(role="user", content="Run search")
    tool = ToolDefinition(name="search", description="Search web", parameters={})
    req_typed = ModelRequest(
        request_id="req_100",
        task_id="task_200",
        model_name="gpt-4o",
        messages=[msg],
        tools=[tool],
        system_prompt="You are ATLAS",
    )
    assert req_typed.request_id == "req_100"
    assert req_typed.system_prompt == "You are ATLAS"

    # Test with backward-compatible dicts (Phase 1/2 callers)
    req_legacy = ModelRequest(
        request_id="req_101",
        task_id="task_201",
        model_name="gpt-4o",
        messages=[{"role": "user", "content": "legacy content"}],
        tools=[{"name": "legacy_tool"}],
    )
    assert len(req_legacy.messages) == 1
    # Pydantic coerces valid dicts to ModelMessage
    msg_item = req_legacy.messages[0]
    content = msg_item.content if isinstance(msg_item, ModelMessage) else msg_item["content"]
    assert content == "legacy content"

    # Test Response with typed tool call and usage
    tool_call = ToolCall(id="tc_1", name="search", arguments={"q": "atlas"})
    usage = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    resp_typed = ModelResponse(
        response_id="resp_100",
        request_id="req_100",
        model_name="gpt-4o",
        content=None,
        tool_calls=[tool_call],
        usage=usage,
        latency_ms=120,
    )
    assert len(resp_typed.tool_calls) == 1
    assert resp_typed.tool_calls[0].name == "search"
    assert resp_typed.usage.total_tokens == 30

    # Test Response with backward-compatible legacy dicts
    resp_legacy = ModelResponse(
        response_id="resp_101",
        request_id="req_101",
        model_name="gpt-4o",
        content="Hello legacy",
        tool_calls=[{"id": "tc_leg", "name": "click"}],
        usage={"prompt_tokens": 5, "completion_tokens": 10},
    )
    assert resp_legacy.content == "Hello legacy"
    u = resp_legacy.usage
    p_tokens = u.prompt_tokens if isinstance(u, TokenUsage) else u["prompt_tokens"]
    assert p_tokens == 5


def test_zero_dependency_core_purity():
    """Constitutional Rule 3: packages/atlas-core must NEVER import external vendor SDKs."""

    forbidden_modules = [
        "openai",
        "anthropic",
        "google.genai",
        "playwright",
        "selenium",
        "requests",
        "aiohttp",
    ]
    for mod in forbidden_modules:
        assert mod not in sys.modules, f"Rule 3 Violation: {mod} was imported by atlas-core!"
