"""OpenAI-compatible local/remote inference endpoint adapter."""

import httpx
from atlas_core.contracts.model import ModelCapabilities

from atlas_models.adapters.openai import OpenAIAdapter


class OpenAICompatibleAdapter(OpenAIAdapter):
    """Adapter for self-hosted or OpenAI-compatible endpoints (vLLM, LocalAI, Groq, Together)."""

    def __init__(
        self,
        model_name: str,
        base_url: str = "http://localhost:8000/v1",
        api_key: str | None = None,
        provider_name: str = "openai-compatible",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(
            model_name=model_name,
            api_key=api_key or "none",
            base_url=base_url,
            client=client,
            timeout=timeout,
        )
        self._provider_name = provider_name

    @property
    def name(self) -> str:
        return f"{self._provider_name}:{self._model_name}"

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            model_name=self._model_name,
            provider=self._provider_name,
            vision=True,
            tool_calling=True,
            structured_output=True,
            streaming=True,
            context_window=32768,
            max_output_tokens=4096,
            cost_per_1k_input_tokens=0.0,
            cost_per_1k_output_tokens=0.0,
        )
