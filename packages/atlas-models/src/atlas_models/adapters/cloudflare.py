"""Cloudflare Workers AI adapter for an explicitly attested Workers Free account."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from atlas_core.contracts.model import (
    ModelCapabilities,
    ModelError,
    ModelRequest,
    ModelResponse,
    ProviderHealth,
    TokenUsage,
)

from atlas_models.adapter import ModelAdapter


class CloudflareWorkersAIAdapter(ModelAdapter):
    """Run text inference through the exact documented Workers AI model route."""

    def __init__(
        self,
        api_token: str,
        account_id: str,
        model_name: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not api_token or not account_id:
            raise ValueError("Cloudflare API token and account ID are required")
        self._api_token = api_token
        self._account_id = account_id
        self._model_name = model_name
        self._base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run"
        self._client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)

    @property
    def name(self) -> str:
        return f"cloudflare:{self._model_name}"

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            model_name=self._model_name,
            provider="cloudflare",
            vision=False,
            tool_calling=False,
            structured_output=False,
            streaming=False,
            context_window=24000,
            max_output_tokens=4096,
            cost_per_1k_input_tokens=0.0,
            cost_per_1k_output_tokens=0.0,
        )

    def _messages(self, request: ModelRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        for item in request.messages:
            if isinstance(item, dict):
                role = str(item.get("role", "user"))
                content = str(item.get("content", ""))
            else:
                role = item.role
                content = item.content if isinstance(item.content, str) else ""
            if role in {"system", "user", "assistant"}:
                messages.append({"role": role, "content": content})
        return messages

    async def complete(self, request: ModelRequest) -> ModelResponse:
        model_id = request.model_name or self._model_name
        if model_id != self._model_name:
            raise ValueError("Cloudflare adapter only accepts its exact registered model ID")
        started = time.perf_counter()
        url = f"{self._base_url}/{model_id}"
        try:
            response = await self._client.post(
                url,
                headers={"Authorization": f"Bearer {self._api_token}"},
                json={"messages": self._messages(request)},
            )
        except httpx.HTTPError as exc:
            error = ModelError(
                error_type="UNAVAILABLE",
                message=f"Cloudflare request failed ({type(exc).__name__}).",
                provider="cloudflare",
                retryable=True,
            )
            raise RuntimeError(error.message) from exc
        if response.status_code >= 400:
            error_type = "RATE_LIMIT" if response.status_code == 429 else "PROVIDER_ERROR"
            message = "Cloudflare rejected the request; check account plan, quota, and model availability."
            raise RuntimeError(f"{error_type}: {message} HTTP {response.status_code}")
        try:
            payload: dict[str, Any] = response.json()
            result = payload.get("result") or {}
            content = result.get("response") or result.get("generated_text") or ""
            usage = result.get("usage") or {}
        except (ValueError, AttributeError, TypeError) as exc:
            raise RuntimeError("Cloudflare returned an unsupported response shape.") from exc
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        return ModelResponse(
            response_id=f"cf-{int(time.time() * 1000)}",
            request_id=request.request_id,
            model_name=model_id,
            content=str(content),
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                estimated_cost_usd=0.0,
            ),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        response = await self.complete(request)
        if response.content:
            yield response.content

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            status="DEGRADED",
            provider_id="cloudflare",
            model_name=self._model_name,
            error="Use the non-generation model-search probe for provider readiness.",
        )
