"""Unit tests for ATLAS Model Provider Adapters (OpenAI, Anthropic, Gemini, Ollama, OpenAI-Compatible)."""

import json

import httpx
import pytest
from atlas_core.contracts.model import (
    ImagePart,
    ModelMessage,
    ModelRequest,
    TextPart,
    ToolDefinition,
)
from atlas_models.adapters.anthropic import AnthropicAdapter
from atlas_models.adapters.gemini import GeminiAdapter
from atlas_models.adapters.ollama import OllamaAdapter
from atlas_models.adapters.openai import OpenAIAdapter
from atlas_models.adapters.openai_compatible import OpenAICompatibleAdapter


# ==============================================================================
# OpenAI Adapter Tests
# ==============================================================================
@pytest.mark.asyncio
async def test_openai_adapter_completion_and_tools():
    """Verify OpenAIAdapter normalizes text, tool calls, and token usage."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers.get("authorization") == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-4o"
        assert len(payload["messages"]) == 2
        assert payload["messages"][0]["role"] == "system"

        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-123",
                "object": "chat.completion",
                "model": "gpt-4o",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Navigating now",
                            "tool_calls": [
                                {
                                    "id": "call_abc",
                                    "type": "function",
                                    "function": {
                                        "name": "browser_navigate",
                                        "arguments": json.dumps({"url": "https://example.com"}),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 150,
                    "completion_tokens": 25,
                    "total_tokens": 175,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAIAdapter(api_key="test-key", client=client)

    tool = ToolDefinition(
        name="browser_navigate",
        description="Navigate to URL",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}},
    )
    req = ModelRequest(
        request_id="req_oai_1",
        task_id="task_oai_1",
        model_name="gpt-4o",
        system_prompt="You are ATLAS",
        messages=[ModelMessage(role="user", content="Go to example.com")],
        tools=[tool],
    )

    resp = await adapter.complete(req)
    assert resp.content == "Navigating now"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "browser_navigate"
    assert resp.tool_calls[0].arguments == {"url": "https://example.com"}
    assert resp.usage.prompt_tokens == 150
    assert resp.usage.completion_tokens == 25
    assert resp.usage.total_tokens == 175


@pytest.mark.asyncio
async def test_openai_adapter_rate_limit_error():
    """Verify OpenAIAdapter normalizes 429 rate limit errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": "Rate limit exceeded", "type": "tokens"}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAIAdapter(api_key="test-key", client=client)

    req = ModelRequest(
        request_id="req_oai_err",
        task_id="task_oai_err",
        model_name="gpt-4o",
        messages=[ModelMessage(role="user", content="Hi")],
    )

    with pytest.raises(Exception) as excinfo:
        await adapter.complete(req)
    assert "Rate limit" in str(excinfo.value) or "RATE_LIMIT" in str(excinfo.value)


# ==============================================================================
# Anthropic Adapter Tests
# ==============================================================================
@pytest.mark.asyncio
async def test_anthropic_adapter_completion_and_tools():
    """Verify AnthropicAdapter extracts system prompt and normalizes tool_use."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers.get("x-api-key") == "anthropic-secret"
        payload = json.loads(request.content)
        assert payload["model"] == "claude-3-5-sonnet-20241022"
        assert payload["system"] == "You are ATLAS Claude"
        assert len(payload["messages"]) == 1
        assert payload["tools"][0]["name"] == "browser_click"

        return httpx.Response(
            200,
            json={
                "id": "msg_claude_1",
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Clicking button"},
                    {
                        "type": "tool_use",
                        "id": "toolu_01",
                        "name": "browser_click",
                        "input": {"selector": "#btn-submit"},
                    },
                ],
                "stop_reason": "tool_use",
                "usage": {
                    "input_tokens": 200,
                    "output_tokens": 40,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = AnthropicAdapter(api_key="anthropic-secret", client=client)

    tool = ToolDefinition(
        name="browser_click",
        description="Click element",
        parameters={"type": "object", "properties": {"selector": {"type": "string"}}},
    )
    req = ModelRequest(
        request_id="req_ant_1",
        task_id="task_ant_1",
        model_name="claude-3-5-sonnet-20241022",
        system_prompt="You are ATLAS Claude",
        messages=[ModelMessage(role="user", content="Submit form")],
        tools=[tool],
    )

    resp = await adapter.complete(req)
    assert resp.content == "Clicking button"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].id == "toolu_01"
    assert resp.tool_calls[0].name == "browser_click"
    assert resp.tool_calls[0].arguments == {"selector": "#btn-submit"}
    assert resp.usage.prompt_tokens == 200
    assert resp.usage.completion_tokens == 40


# ==============================================================================
# Google Gemini Adapter Tests
# ==============================================================================
@pytest.mark.asyncio
async def test_gemini_adapter_completion_and_multimodal():
    """Verify GeminiAdapter handles inlineData image and functionCall."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert ":generateContent" in request.url.path
        payload = json.loads(request.content)
        assert len(payload["contents"]) == 1
        parts = payload["contents"][0]["parts"]
        assert parts[0]["text"] == "Inspect this screenshot"
        assert parts[1]["inline_data"]["mime_type"] == "image/png"

        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "browser_type",
                                        "args": {"text": "atlas-user"},
                                    }
                                }
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 350,
                    "candidatesTokenCount": 30,
                    "totalTokenCount": 380,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GeminiAdapter(api_key="gemini-key", client=client)

    req = ModelRequest(
        request_id="req_gem_1",
        task_id="task_gem_1",
        model_name="gemini-1.5-pro",
        messages=[
            ModelMessage(
                role="user",
                content=[
                    TextPart(text="Inspect this screenshot"),
                    ImagePart(media_type="image/png", data="iVBORw0KGgoAAAANSUhEUgAAAAE="),
                ],
            )
        ],
    )

    resp = await adapter.complete(req)
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "browser_type"
    assert resp.tool_calls[0].arguments == {"text": "atlas-user"}
    assert resp.usage.prompt_tokens == 350
    assert resp.usage.completion_tokens == 30
    assert resp.usage.total_tokens == 380


# ==============================================================================
# Ollama Adapter Tests
# ==============================================================================
@pytest.mark.asyncio
async def test_ollama_adapter_completion_and_health():
    """Verify OllamaAdapter interfaces with local endpoint without API keys."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.4.1"})
        elif request.url.path == "/api/chat":
            payload = json.loads(request.content)
            assert payload["model"] == "llama3.2"
            assert payload["stream"] is False
            return httpx.Response(
                200,
                json={
                    "model": "llama3.2",
                    "message": {
                        "role": "assistant",
                        "content": "Local model completed task",
                    },
                    "prompt_eval_count": 45,
                    "eval_count": 20,
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OllamaAdapter(model_name="llama3.2", client=client)

    health = await adapter.health_check()
    assert health.status == "HEALTHY"
    assert health.provider_id == "ollama"

    req = ModelRequest(
        request_id="req_ollama_1",
        task_id="task_ollama_1",
        model_name="llama3.2",
        messages=[ModelMessage(role="user", content="Hello local model")],
    )

    resp = await adapter.complete(req)
    assert resp.content == "Local model completed task"
    assert resp.usage.prompt_tokens == 45
    assert resp.usage.completion_tokens == 20


# ==============================================================================
# OpenAI-Compatible Adapter Tests
# ==============================================================================
@pytest.mark.asyncio
async def test_openai_compatible_adapter():
    """Verify OpenAICompatibleAdapter routes to custom base_url endpoints."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("http://localhost:8000/v1/chat/completions")
        assert request.headers.get("authorization") == "Bearer vllm-key"
        return httpx.Response(
            200,
            json={
                "id": "vllm-1",
                "object": "chat.completion",
                "model": "mistral-7b-instruct",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "vLLM Response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleAdapter(
        model_name="mistral-7b-instruct",
        base_url="http://localhost:8000/v1",
        api_key="vllm-key",
        provider_name="vllm",
        client=client,
    )

    assert adapter.name == "vllm:mistral-7b-instruct"
    req = ModelRequest(
        request_id="req_vllm_1",
        task_id="task_vllm_1",
        model_name="mistral-7b-instruct",
        messages=[ModelMessage(role="user", content="test")],
    )

    resp = await adapter.complete(req)
    assert resp.content == "vLLM Response"
    assert resp.usage.total_tokens == 20
