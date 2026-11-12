"""Google Gemini REST API adapter."""

import os
import time
from collections.abc import AsyncIterator, Sequence
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


class GeminiAdapter(ModelAdapter):
    """Adapter for Google Gemini models via official REST endpoints."""

    def __init__(
        self,
        model_name: str = "gemini-1.5-pro",
        api_key: str | None = None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._model_name = model_name
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=self._timeout)

    @property
    def name(self) -> str:
        return f"gemini:{self._model_name}"

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            model_name=self._model_name,
            provider="gemini",
            vision=True,
            tool_calling=True,
            structured_output=True,
            streaming=True,
            context_window=1000000,
            max_output_tokens=8192,
            cost_per_1k_input_tokens=0.00125,
            cost_per_1k_output_tokens=0.005,
        )

    def _format_contents(self, request: ModelRequest) -> list[dict[str, Any]]:
        contents = []
        for msg in request.messages:
            if isinstance(msg, dict):
                role = "model" if msg.get("role") == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": str(msg.get("content", ""))}]})
                continue

            role = "model" if msg.role == "assistant" else "user"
            parts = []
            if isinstance(msg.content, str):
                parts.append({"text": msg.content})
            elif isinstance(msg.content, list):
                for p in msg.content:
                    if isinstance(p, TextPart):
                        parts.append({"text": p.text})
                    elif isinstance(p, ImagePart):
                        parts.append(
                            {
                                "inline_data": {
                                    "mime_type": p.media_type,
                                    "data": p.data or "",
                                }
                            }
                        )
            contents.append({"role": role, "parts": parts})
        return contents

    def _format_tools(self, tools: Sequence[Any]) -> list[dict[str, Any]]:
        declarations = []
        for t in tools:
            if isinstance(t, dict):
                declarations.append(t)
            elif isinstance(t, ToolDefinition):
                declarations.append(
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    }
                )
        if declarations:
            return [{"function_declarations": declarations}]
        return []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        start_time = time.perf_counter()
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["x-goog-api-key"] = self._api_key

        model_id = request.model_name or self._model_name
        url = f"{self._base_url}/models/{model_id}:generateContent"

        payload: dict[str, Any] = {
            "contents": self._format_contents(request),
        }
        if request.system_prompt:
            payload["system_instruction"] = {"parts": [{"text": request.system_prompt}]}
        tools = self._format_tools(request.tools)
        if tools:
            payload["tools"] = tools

        try:
            resp = await self._client.post(url, headers=headers, json=payload)
        except Exception as exc:
            err = ModelError(
                error_type="UNKNOWN",
                message=f"Network error communicating with Gemini: {exc}",
                provider="gemini",
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
                provider="gemini",
                status_code=resp.status_code,
                retryable=resp.status_code in (429, 500, 503),
                raw_error=error_data,
            )
            raise RuntimeError(f"Model Error: {err.error_type} - {err.message}")

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ModelResponse(
                response_id=f"resp_{int(time.time())}",
                request_id=request.request_id,
                model_name=model_id,
                content="",
                latency_ms=latency_ms,
            )

        candidate = candidates[0]
        content_obj = candidate.get("content", {})
        parts = content_obj.get("parts", [])

        text_parts = []
        tool_calls = []

        for p in parts:
            if "text" in p:
                text_parts.append(p["text"])
            elif "functionCall" in p:
                fc = p["functionCall"]
                tool_calls.append(
                    ToolCall(
                        id=f"call_{int(time.time())}_{fc.get('name')}",
                        name=fc.get("name", ""),
                        arguments=fc.get("args", {}),
                        type="function",
                    )
                )

        usage_meta = data.get("usageMetadata", {})
        prompt_tokens = usage_meta.get("promptTokenCount", 0)
        completion_tokens = usage_meta.get("candidatesTokenCount", 0)
        total_tokens = usage_meta.get("totalTokenCount", prompt_tokens + completion_tokens)
        cost_usd = (prompt_tokens * 0.00125 + completion_tokens * 0.005) / 1000.0

        return ModelResponse(
            response_id=f"resp_{int(time.time())}",
            request_id=request.request_id,
            model_name=model_id,
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            raw_finish_reason=candidate.get("finishReason"),
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
        if self._api_key:
            return ProviderHealth(
                status="HEALTHY",
                provider_id="gemini",
                model_name=self._model_name,
                latency_ms=10,
            )
        return ProviderHealth(
            status="DEGRADED",
            provider_id="gemini",
            model_name=self._model_name,
            error="Missing GEMINI_API_KEY",
        )
