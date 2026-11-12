"""Abstract ModelAdapter base class and provider protocols."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from atlas_core.contracts.model import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ProviderHealth,
)


def mask_credential(secret: str | None) -> str:
    """Mask sensitive tokens or API keys for safe diagnostic reporting."""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "***"
    return f"{secret[:12]}...{secret[-4:]}"


class ModelAdapter(ABC):
    """Abstract interface for all model provider adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique adapter identifier in format 'provider:model_name'."""
        ...

    @abstractmethod
    def get_capabilities(self) -> ModelCapabilities:
        """Return the declared capabilities, limitations, and modalities."""
        ...

    @abstractmethod
    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Execute a model completion request and return a normalized ModelResponse."""
        ...

    @abstractmethod
    def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        """Stream completion text tokens asynchronously."""
        ...

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Probe the upstream provider or model endpoint and return diagnostic health."""
        ...
