"""Ollama local inference API adapter."""

import json
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


class OllamaAdapter(ModelAdapter):
    """Adapter for local Ollama instances via native /api/chat endpoints."""

    def __init__(
        self,
        model_name: str = "llama3.2",
        host: str = "http://localhost:11434",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._model_name = model_name
        self._host = host.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=self._timeout)

    @property
    def name(self) -> str:
        return f"ollama:{self._model_name}"

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            model_name=self._model_name,
            provider="ollama",
            vision=True,
            tool_calling=True,
            structured_output=True,
            streaming=True,
            context_window=64000,
            max_output_tokens=4096,
            cost_per_1k_input_tokens=0.0,
            cost_per_1k_output_tokens=0.0,
        )

    def _format_messages(self, request: ModelRequest) -> list[dict[str, Any]]:
        formatted = []
        if request.system_prompt:
            formatted.append({"role": "system", "content": request.system_prompt})

        for msg in request.messages:
            if isinstance(msg, dict):
                formatted.append(msg)
                continue

            entry: dict[str, Any] = {"role": msg.role}
            if isinstance(msg.content, str):
                entry["content"] = msg.content
            elif isinstance(msg.content, list):
                text_segments = []
                images = []
                for p in msg.content:
                    if isinstance(p, TextPart):
                        text_segments.append(p.text)
                    elif isinstance(p, ImagePart) and p.data:
                        images.append(p.data)
                entry["content"] = "\n".join(text_segments)
                if images:
                    entry["images"] = images
            else:
                entry["content"] = ""
            formatted.append(entry)
        return formatted

    def _format_tools(self, tools: Sequence[Any]) -> list[dict[str, Any]]:
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
        url = f"{self._host}/api/chat"

        payload: dict[str, Any] = {
            "model": request.model_name or self._model_name,
            "messages": self._format_messages(request),
            "stream": False,
        }
        if request.tools:
            payload["tools"] = self._format_tools(request.tools)

        try:
            resp = await self._client.post(url, json=payload)
        except Exception as exc:
            err = ModelError(
                error_type="SERVER_ERROR",
                message=f"Cannot reach Ollama at {self._host}: {exc}",
                provider="ollama",
                retryable=True,
            )
            raise RuntimeError(f"Model Error: {err.error_type} - {err.message}") from exc

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        if resp.status_code != 200:
            err = ModelError(
                error_type="SERVER_ERROR",
                message=f"Ollama returned HTTP {resp.status_code}: {resp.text}",
                provider="ollama",
                status_code=resp.status_code,
                retryable=True,
            )
            raise RuntimeError(f"Model Error: {err.error_type} - {err.message}")

        data = resp.json()
        msg = data.get("message", {})

        tool_calls = []
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"raw": args}
            tool_calls.append(
                ToolCall(
                    id=f"ollama_{int(time.time())}_{fn.get('name')}",
                    name=fn.get("name", ""),
                    arguments=args,
                    type="function",
                )
            )

        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        total_tokens = prompt_tokens + completion_tokens

        return ModelResponse(
            response_id=f"resp_{int(time.time())}",
            request_id=request.request_id,
            model_name=data.get("model", self._model_name),
            content=msg.get("content"),
            tool_calls=tool_calls,
            raw_finish_reason=data.get("done_reason", "stop"),
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=0.0,
            ),
            latency_ms=latency_ms,
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        resp = await self.complete(request)
        if resp.content:
            yield resp.content

    async def health_check(self) -> ProviderHealth:
        start_time = time.perf_counter()
        try:
            resp = await self._client.get(f"{self._host}/api/version")
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            if resp.status_code == 200:
                return ProviderHealth(
                    status="HEALTHY",
                    provider_id="ollama",
                    model_name=self._model_name,
                    latency_ms=latency_ms,
                )
            return ProviderHealth(
                status="DEGRADED",
                provider_id="ollama",
                model_name=self._model_name,
                latency_ms=latency_ms,
                error=f"HTTP {resp.status_code}",
            )
        except Exception as exc:
            return ProviderHealth(
                status="UNAVAILABLE",
                provider_id="ollama",
                model_name=self._model_name,
                error=str(exc),
            )
