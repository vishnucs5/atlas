"""OpenAI Chat Completions API adapter."""

import json
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


class OpenAIAdapter(ModelAdapter):
    """Adapter for OpenAI Chat Completions API and compatible models."""

    def __init__(
        self,
        model_name: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._model_name = model_name
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=self._timeout)

    @property
    def name(self) -> str:
        return f"openai:{self._model_name}"

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            model_name=self._model_name,
            provider="openai",
            vision=True,
            tool_calling=True,
            structured_output=True,
            streaming=True,
            context_window=128000,
            max_output_tokens=4096,
            cost_per_1k_input_tokens=0.005,
            cost_per_1k_output_tokens=0.015,
        )

    def _format_messages(self, request: ModelRequest) -> list[dict[str, Any]]:
        formatted = []
        if request.system_prompt:
            formatted.append({"role": "system", "content": request.system_prompt})

        for msg in request.messages:
            if isinstance(msg, dict):
                formatted.append(msg)
                continue

            if isinstance(msg.content, str):
                formatted.append(
                    {
                        "role": msg.role,
                        "content": msg.content,
                        **({"name": msg.name} if msg.name else {}),
                        **({"tool_call_id": msg.tool_call_id} if msg.tool_call_id else {}),
                    }
                )
            elif isinstance(msg.content, list):
                parts = []
                for p in msg.content:
                    if isinstance(p, TextPart):
                        parts.append({"type": "text", "text": p.text})
                    elif isinstance(p, ImagePart):
                        url = p.url or (f"data:{p.media_type};base64,{p.data}" if p.data else "")
                        parts.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": url, "detail": p.detail},
                            }
                        )
                formatted.append({"role": msg.role, "content": parts})
            else:
                formatted.append({"role": msg.role, "content": ""})

        return formatted

    def _format_tools(self, tools: list[Any]) -> list[dict[str, Any]]:
        formatted = []
        for t in tools:
            if isinstance(t, dict):
                formatted.append(t)
            elif isinstance(t, ToolDefinition):
                formatted.append(
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.parameters,
                        },
                    }
                )
        return formatted

    async def complete(self, request: ModelRequest) -> ModelResponse:
        start_time = time.perf_counter()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": request.model_name or self._model_name,
            "messages": self._format_messages(request),
            "temperature": request.temperature,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        if request.tools:
            payload["tools"] = self._format_tools(request.tools)
        if request.stop_sequences:
            payload["stop"] = request.stop_sequences

        url = f"{self._base_url}/chat/completions"
        try:
            resp = await self._client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            err = ModelError(
                error_type="TIMEOUT",
                message=f"Request to OpenAI timed out: {exc}",
                provider="openai",
                retryable=True,
            )
            raise RuntimeError(f"Model Error: {err.error_type} - {err.message}") from exc
        except Exception as exc:
            err = ModelError(
                error_type="UNKNOWN",
                message=f"Network error communicating with OpenAI: {exc}",
                provider="openai",
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
                provider="openai",
                status_code=resp.status_code,
                retryable=resp.status_code in (429, 500, 502, 503, 504),
                raw_error=error_data,
            )
            raise RuntimeError(f"Model Error: {err.error_type} - {err.message}")

        data = resp.json()
        choice = data["choices"][0]
        msg = choice.get("message", {})
        raw_finish_reason = choice.get("finish_reason")

        tool_calls = []
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except Exception:
                args = {"raw": fn.get("arguments", "")}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=args,
                    type=tc.get("type", "function"),
                )
            )

        usage_data = data.get("usage", {})
        prompt_tokens = usage_data.get("prompt_tokens", 0)
        completion_tokens = usage_data.get("completion_tokens", 0)
        total_tokens = usage_data.get("total_tokens", prompt_tokens + completion_tokens)
        cost_usd = (prompt_tokens * 0.005 + completion_tokens * 0.015) / 1000.0

        return ModelResponse(
            response_id=data.get("id", f"resp_{int(time.time())}"),
            request_id=request.request_id,
            model_name=data.get("model", self._model_name),
            content=msg.get("content"),
            tool_calls=tool_calls,
            raw_finish_reason=raw_finish_reason,
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=round(cost_usd, 6),
            ),
            latency_ms=latency_ms,
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        # Simple streaming yielding complete content for offline compatibility
        resp = await self.complete(request)
        if resp.content:
            yield resp.content

    async def health_check(self) -> ProviderHealth:
        start_time = time.perf_counter()
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            resp = await self._client.get(f"{self._base_url}/models", headers=headers)
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            if resp.status_code == 200:
                return ProviderHealth(
                    status="HEALTHY",
                    provider_id="openai",
                    model_name=self._model_name,
                    latency_ms=latency_ms,
                )
            return ProviderHealth(
                status="DEGRADED",
                provider_id="openai",
                model_name=self._model_name,
                latency_ms=latency_ms,
                error=f"HTTP {resp.status_code}",
            )
        except Exception as exc:
            return ProviderHealth(
                status="UNAVAILABLE",
                provider_id="openai",
                model_name=self._model_name,
                error=str(exc),
            )
