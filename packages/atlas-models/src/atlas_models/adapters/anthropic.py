"""Anthropic Messages API adapter."""

import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from atlas_core.contracts.model import (
    ImagePart,
    ModelCapabilities,
    ModelError,
    ModelRequest,
    ModelResponse,
    ProviderHealth,
    TextPart,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

from atlas_models.adapter import ModelAdapter


class AnthropicAdapter(ModelAdapter):
    """Adapter for Anthropic Claude Messages API."""

    def __init__(
        self,
        model_name: str = "claude-3-5-sonnet-20241022",
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com/v1",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._model_name = model_name
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=self._timeout)

    @property
    def name(self) -> str:
        return f"anthropic:{self._model_name}"

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            model_name=self._model_name,
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

    def _format_messages_and_system(
        self, request: ModelRequest
    ) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts = []
        if request.system_prompt:
            system_parts.append(request.system_prompt)

        formatted_messages = []
        for msg in request.messages:
            if isinstance(msg, dict):
                role = msg.get("role", "user")
                if role == "system":
                    system_parts.append(str(msg.get("content", "")))
                else:
                    formatted_messages.append(msg)
                continue

            if msg.role == "system":
                if isinstance(msg.content, str):
                    system_parts.append(msg.content)
                continue

            if msg.role == "tool":
                formatted_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id or "",
                                "content": msg.content if isinstance(msg.content, str) else "",
                            }
                        ],
                    }
                )
            elif isinstance(msg.content, str):
                formatted_messages.append({"role": msg.role, "content": msg.content})
            elif isinstance(msg.content, list):
                blocks = []
                for p in msg.content:
                    if isinstance(p, TextPart):
                        blocks.append({"type": "text", "text": p.text})
                    elif isinstance(p, ImagePart):
                        data = p.data or ""
                        blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": p.media_type,
                                    "data": data,
                                },
                            }
                        )
                formatted_messages.append({"role": msg.role, "content": blocks})
            else:
                formatted_messages.append({"role": msg.role, "content": ""})

        system_str = "\n\n".join(system_parts) if system_parts else None
        return system_str, formatted_messages

    def _format_tools(self, tools: list[Any]) -> list[dict[str, Any]]:
        formatted = []
        for t in tools:
            if isinstance(t, dict):
                formatted.append(t)
            elif isinstance(t, ToolDefinition):
                formatted.append(
                    {
                        "name": t.name,
                        "description": t.description,
                        "input_schema": t.parameters,
                    }
                )
        return formatted

    async def complete(self, request: ModelRequest) -> ModelResponse:
        start_time = time.perf_counter()
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        system_str, messages = self._format_messages_and_system(request)
        payload: dict[str, Any] = {
            "model": request.model_name or self._model_name,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
            "temperature": request.temperature,
        }
        if system_str:
            payload["system"] = system_str
        if request.tools:
            payload["tools"] = self._format_tools(request.tools)
        if request.stop_sequences:
            payload["stop_sequences"] = request.stop_sequences

        url = f"{self._base_url}/messages"
        try:
            resp = await self._client.post(url, headers=headers, json=payload)
        except Exception as exc:
            err = ModelError(
                error_type="UNKNOWN",
                message=f"Network error communicating with Anthropic: {exc}",
                provider="anthropic",
                retryable=True,
            )
            raise RuntimeError(f"Model Error: {err.error_type} - {err.message}") from exc

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        if resp.status_code != 200:
            error_data = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            err_msg = error_data.get("error", {}).get("message", resp.text)
            err_type = (
                "RATE_LIMIT"
                if resp.status_code == 429
                else (
                    "AUTHENTICATION"
                    if resp.status_code in (401, 403)
                    else ("INVALID_REQUEST" if resp.status_code == 400 else "SERVER_ERROR")
                )
            )
            err = ModelError(
                error_type=err_type,
                message=err_msg,
                provider="anthropic",
                status_code=resp.status_code,
                retryable=resp.status_code in (429, 500, 502, 503, 504),
                raw_error=error_data,
            )
            raise RuntimeError(f"Model Error: {err.error_type} - {err.message}")

        data = resp.json()
        text_parts = []
        tool_calls = []

        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input", {}),
                        type="function",
                    )
                )

        combined_text = "\n".join(text_parts) if text_parts else None
        usage_data = data.get("usage", {})
        prompt_tokens = usage_data.get("input_tokens", 0)
        completion_tokens = usage_data.get("output_tokens", 0)
        total_tokens = prompt_tokens + completion_tokens
        cost_usd = (prompt_tokens * 0.003 + completion_tokens * 0.015) / 1000.0

        return ModelResponse(
            response_id=data.get("id", f"resp_{int(time.time())}"),
            request_id=request.request_id,
            model_name=data.get("model", self._model_name),
            content=combined_text,
            tool_calls=tool_calls,
            raw_finish_reason=data.get("stop_reason"),
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=round(cost_usd, 6),
            ),
            latency_ms=latency_ms,
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        resp = await self.complete(request)
        if resp.content:
            yield resp.content

    async def health_check(self) -> ProviderHealth:
        # Anthropic doesn't have a public free ping endpoint; return based on client initialization
        if self._api_key:
            return ProviderHealth(
                status="HEALTHY",
                provider_id="anthropic",
                model_name=self._model_name,
                latency_ms=5,
            )
        return ProviderHealth(
            status="DEGRADED",
            provider_id="anthropic",
            model_name=self._model_name,
            error="Missing ANTHROPIC_API_KEY",
        )
