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
        ModelError(error_type="INVALID_ERROR_TYPE", message="Invalid")  # type: ignore[arg-type]


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
    first_tool_call = resp_typed.tool_calls[0]
    assert isinstance(first_tool_call, ToolCall)
    assert first_tool_call.name == "search"
    assert isinstance(resp_typed.usage, TokenUsage)
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
    # Subscriptable dict-like access works on TokenUsage
    assert resp_legacy.usage["prompt_tokens"] == 5
    assert isinstance(resp_legacy.usage, TokenUsage)
    assert resp_legacy.usage.prompt_tokens == 5
    assert "prompt_tokens" in resp_legacy.usage
    assert resp_legacy.usage.get("total_tokens") == 0

    # Subscriptable dict-like access works on ToolCall
    tc = resp_typed.tool_calls[0]
    assert tc["name"] == "search"
    assert isinstance(tc, ToolCall)
    assert tc.name == "search"
    assert "arguments" in tc


def test_contract_validation_errors():
    """Verify strict validation and error handling for model contracts."""
    # Invalid role in ModelMessage
    with pytest.raises(ValidationError):
        ModelMessage(role="invalid_role", content="test")  # type: ignore[arg-type]

    # Invalid discriminator in ContentPart within ModelMessage
    with pytest.raises(ValidationError):
        ModelMessage(
            role="user",
            content=[{"type": "audio", "data": "abc123audio"}],  # type: ignore[list-item]
        )

    # Missing required field in TextPart
    with pytest.raises(ValidationError):
        TextPart()  # type: ignore[call-arg]

    # Missing required fields in ToolDefinition
    with pytest.raises(ValidationError):
        ToolDefinition(name="only_name")  # type: ignore[call-arg]

    # Missing required fields in ToolCall
    with pytest.raises(ValidationError):
        ToolCall(id="only_id")  # type: ignore[call-arg]

    # Missing required fields in ModelRequest
    with pytest.raises(ValidationError):
        ModelRequest(request_id="req_1")  # type: ignore[call-arg]

    # Missing required fields in ModelResponse
    with pytest.raises(ValidationError):
        ModelResponse(response_id="resp_1")  # type: ignore[call-arg]

    # Validate assignment checks
    msg = ModelMessage(role="user", content="valid")
    with pytest.raises(ValidationError):
        msg.role = "super_admin"  # type: ignore[assignment]

    err = ModelError(error_type="TIMEOUT", message="Timed out")
    with pytest.raises(ValidationError):
        err.error_type = "NOT_AN_ERROR"  # type: ignore[assignment]


def test_json_round_trips_for_all_contracts():
    """Verify deterministic JSON serialization and deserialization across all model contracts."""
    # TextPart
    tp = TextPart(text="hello")
    assert TextPart.model_validate_json(tp.model_dump_json()).text == "hello"

    # ImagePart
    ip = ImagePart(data="base64str", media_type="image/jpeg", detail="low")
    assert ImagePart.model_validate_json(ip.model_dump_json()).detail == "low"

    # ModelMessage
    mm = ModelMessage(role="assistant", content=[tp, ip], name="agent_1")
    mm_rt = ModelMessage.model_validate_json(mm.model_dump_json())
    assert mm_rt.role == "assistant"
    assert mm_rt.name == "agent_1"
    assert isinstance(mm_rt.content, list)
    assert len(mm_rt.content) == 2

    # ToolDefinition
    td = ToolDefinition(name="nav", description="Navigate", parameters={"k": "v"})
    assert ToolDefinition.model_validate_json(td.model_dump_json()).name == "nav"

    # ToolCall
    tc = ToolCall(id="tc_1", name="nav", arguments={"url": "https://test.com"})
    assert ToolCall.model_validate_json(tc.model_dump_json()).arguments["url"] == "https://test.com"

    # TokenUsage
    tu = TokenUsage(
        prompt_tokens=100, completion_tokens=50, total_tokens=150, estimated_cost_usd=0.001
    )
    tu_rt = TokenUsage.model_validate_json(tu.model_dump_json())
    assert tu_rt.total_tokens == 150
    assert tu_rt.estimated_cost_usd == 0.001

    # ProviderHealth
    now = datetime.now(UTC)
    ph = ProviderHealth(provider_id="gemini", status="HEALTHY", latency_ms=45, last_checked_at=now)
    ph_rt = ProviderHealth.model_validate_json(ph.model_dump_json())
    assert ph_rt.provider_id == "gemini"
    assert ph_rt.latency_ms == 45

    # ModelError
    me = ModelError(
        error_type="AUTHENTICATION", message="Invalid API key", provider="openai", status_code=401
    )
    me_rt = ModelError.model_validate_json(me.model_dump_json())
    assert me_rt.error_type == "AUTHENTICATION"
    assert me_rt.status_code == 401

    # ModelCapabilities
    mc = ModelCapabilities(model_name="gpt-4o", provider="openai", context_window=128000)
    assert ModelCapabilities.model_validate_json(mc.model_dump_json()).model_name == "gpt-4o"

    # ModelRequest
    mreq = ModelRequest(
        request_id="r1", task_id="t1", model_name="gpt-4o", messages=[mm], tools=[td]
    )
    mreq_rt = ModelRequest.model_validate_json(mreq.model_dump_json())
    assert mreq_rt.request_id == "r1"
    assert len(mreq_rt.messages) == 1

    # ModelResponse
    mresp = ModelResponse(
        response_id="res1",
        request_id="r1",
        model_name="gpt-4o",
        content="Done",
        tool_calls=[tc],
        usage=tu,
    )
    mresp_rt = ModelResponse.model_validate_json(mresp.model_dump_json())
    assert mresp_rt.response_id == "res1"
    assert mresp_rt.content == "Done"
    assert isinstance(mresp_rt.usage, TokenUsage)
    assert mresp_rt.usage.total_tokens == 150


def test_zero_dependency_core_purity():
    """Constitutional Rule 3: packages/atlas-core must NEVER import external vendor SDKs."""
    import subprocess

    check_script = (
        "import sys\n"
        "import atlas_core\n"
        "import atlas_core.contracts\n"
        "import atlas_core.contracts.model\n"
        "forbidden = ['openai', 'anthropic', 'google.genai', 'playwright', 'selenium', 'requests', 'aiohttp']\n"
        "violated = [m for m in forbidden if m in sys.modules]\n"
        "if violated:\n"
        "    print(f'Rule 3 Violation: {violated}')\n"
        "    sys.exit(1)\n"
    )
    res = subprocess.run([sys.executable, "-c", check_script], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout or res.stderr
