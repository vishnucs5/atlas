"""ATLAS Multimodal Provider Abstraction.

Defines modalities, capabilities, requests, responses, model adapters, and
routing logic with capability negotiation, fallback selection, and fast-failure.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MultimodalModality(StrEnum):
    """Supported multimodal modalities in ATLAS."""

    IMAGE_UNDERSTANDING = "image_understanding"
    IMAGE_GENERATION = "image_generation"
    VIDEO_UNDERSTANDING = "video_understanding"
    SPEECH_TO_TEXT = "speech_to_text"
    SPEECH_TO_SPEECH = "speech_to_speech"
    DOCUMENT_OCR = "document_ocr"
    STRUCTURED_OUTPUT = "structured_output"


class MultimodalError(Exception):
    """Base exception for all multimodal operations."""


class UnsupportedModalityError(MultimodalError):
    """Raised when a requested modality is not supported by any available provider."""


class ProviderUnavailableError(MultimodalError):
    """Raised when a selected provider cannot be contacted or reached."""


class ModalityNegotiationError(MultimodalError):
    """Raised when no provider can satisfy all required modalities."""


class MultimodalCapability(BaseModel):
    """Declared capabilities of a multimodal provider or model."""

    provider_id: str
    model_name: str
    supported_modalities: list[MultimodalModality] = Field(default_factory=list)
    max_image_resolution: tuple[int, int] = (4096, 4096)
    max_video_duration_sec: float = 300.0
    supports_streaming: bool = False
    cost_per_image: float = 0.005
    cost_per_video_minute: float = 0.05
    cost_per_audio_minute: float = 0.01
    cost_per_1k_tokens: float = 0.002
    is_local_gpu: bool = False
    priority: int = 100

    def supports_all(self, modalities: list[MultimodalModality]) -> bool:
        """Check if this capability satisfies all requested modalities."""
        return all(m in self.supported_modalities for m in modalities)


class MultimodalRequest(BaseModel):
    """Input payload for a multimodal perception or generation task."""

    request_id: str = Field(default_factory=lambda: f"mm_req_{uuid.uuid4().hex[:12]}")
    task_id: str
    tenant_id: str
    required_modalities: list[MultimodalModality]
    prompt: str = ""
    image_refs: list[str] = Field(default_factory=list)
    video_refs: list[str] = Field(default_factory=list)
    audio_refs: list[str] = Field(default_factory=list)
    document_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    preferred_provider: str | None = None
    timeout_sec: float = 30.0


class MultimodalResponse(BaseModel):
    """Structured response from a multimodal provider."""

    response_id: str = Field(default_factory=lambda: f"mm_res_{uuid.uuid4().hex[:12]}")
    request_id: str
    provider_id: str
    model_name: str
    text: str = ""
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    timestamp: float = Field(default_factory=time.time)


class MultimodalCostAccounting:
    """Tracks and audits multimodal token and media spend per tenant."""

    def __init__(self) -> None:
        self._tenant_costs: dict[str, float] = {}
        self._task_costs: dict[str, float] = {}

    def record_cost(self, tenant_id: str, task_id: str, cost_usd: float) -> None:
        self._tenant_costs[tenant_id] = self._tenant_costs.get(tenant_id, 0.0) + cost_usd
        self._task_costs[task_id] = self._task_costs.get(task_id, 0.0) + cost_usd

    def get_tenant_spend(self, tenant_id: str) -> float:
        return self._tenant_costs.get(tenant_id, 0.0)

    def get_task_spend(self, task_id: str) -> float:
        return self._task_costs.get(task_id, 0.0)


class MultimodalModelAdapter(ABC):
    """Abstract base class for all multimodal model adapters."""

    def __init__(self, capability: MultimodalCapability) -> None:
        self.capability = capability
        self.is_healthy: bool = True

    @abstractmethod
    async def execute(self, request: MultimodalRequest) -> MultimodalResponse:
        """Execute multimodal inference against the underlying model."""


class MockMultimodalAdapter(MultimodalModelAdapter):
    """Deterministic in-memory multimodal adapter for tests and local execution."""

    def __init__(
        self,
        capability: MultimodalCapability,
        default_response_text: str = "Mock multimodal response",
        default_extracted: dict[str, Any] | None = None,
        should_fail: bool = False,
    ) -> None:
        super().__init__(capability)
        self.default_response_text = default_response_text
        self.default_extracted = default_extracted or {}
        self.should_fail = should_fail
        self.calls: list[MultimodalRequest] = []

    async def execute(self, request: MultimodalRequest) -> MultimodalResponse:
        self.calls.append(request)
        if self.should_fail or not self.is_healthy:
            raise ProviderUnavailableError(
                f"Provider {self.capability.provider_id} failed or is unhealthy."
            )

        # Validate that this adapter can handle the request's modalities
        if not self.capability.supports_all(request.required_modalities):
            missing = [
                m
                for m in request.required_modalities
                if m not in self.capability.supported_modalities
            ]
            raise UnsupportedModalityError(
                f"Provider {self.capability.provider_id} does not support requested modalities: {missing}"
            )

        # Calculate simulated cost
        cost = 0.0
        if MultimodalModality.IMAGE_UNDERSTANDING in request.required_modalities:
            cost += len(request.image_refs) * self.capability.cost_per_image
        if MultimodalModality.VIDEO_UNDERSTANDING in request.required_modalities:
            cost += self.capability.cost_per_video_minute
        if MultimodalModality.SPEECH_TO_TEXT in request.required_modalities:
            cost += self.capability.cost_per_audio_minute
        cost += self.capability.cost_per_1k_tokens * 0.1  # baseline token cost

        return MultimodalResponse(
            request_id=request.request_id,
            provider_id=self.capability.provider_id,
            model_name=self.capability.model_name,
            text=self.default_response_text,
            extracted_data=self.default_extracted,
            cost_usd=round(cost, 5),
            latency_ms=15.0,
        )


class MultimodalRouter:
    """Manages provider registration, capability negotiation, and fallback routing."""

    def __init__(self, cost_accounting: MultimodalCostAccounting | None = None) -> None:
        self._adapters: dict[str, MultimodalModelAdapter] = {}
        self.cost_accounting = cost_accounting or MultimodalCostAccounting()

    def register_adapter(self, adapter: MultimodalModelAdapter) -> None:
        """Register a multimodal model adapter."""
        self._adapters[adapter.capability.provider_id] = adapter

    def unregister_adapter(self, provider_id: str) -> None:
        """Unregister a model adapter."""
        self._adapters.pop(provider_id, None)

    def get_adapter(self, provider_id: str) -> MultimodalModelAdapter | None:
        """Retrieve an adapter by provider ID."""
        return self._adapters.get(provider_id)

    def list_capabilities(self) -> list[MultimodalCapability]:
        """List all registered provider capabilities."""
        return [adapter.capability for adapter in self._adapters.values()]

    def negotiate_adapter(
        self,
        required_modalities: list[MultimodalModality],
        preferred_provider: str | None = None,
        require_local_gpu: bool = False,
    ) -> MultimodalModelAdapter:
        """Negotiate the best provider for the given modalities and constraints."""
        candidates = [
            a
            for a in self._adapters.values()
            if a.is_healthy
            and a.capability.supports_all(required_modalities)
            and (not require_local_gpu or a.capability.is_local_gpu)
        ]

        if not candidates:
            # Check if ANY provider supports at least one of the modalities
            all_supported: set[MultimodalModality] = set()
            for a in self._adapters.values():
                all_supported.update(a.capability.supported_modalities)

            unsupported = [m for m in required_modalities if m not in all_supported]
            if unsupported:
                raise UnsupportedModalityError(
                    f"No registered providers support requested modalities: {unsupported}"
                )
            raise ModalityNegotiationError(
                f"No single healthy provider satisfies all required modalities: {required_modalities}"
            )

        # If preferred provider is available and satisfies constraints, pick it
        if preferred_provider:
            for c in candidates:
                if c.capability.provider_id == preferred_provider:
                    return c

        # Otherwise pick the highest priority (lowest priority number) or lowest cost
        candidates.sort(key=lambda a: (a.capability.priority, a.capability.cost_per_image))
        return candidates[0]

    async def route_and_execute(
        self,
        request: MultimodalRequest,
        require_local_gpu: bool = False,
    ) -> MultimodalResponse:
        """Route request to the best adapter with fallback execution."""
        primary_adapter = self.negotiate_adapter(
            required_modalities=request.required_modalities,
            preferred_provider=request.preferred_provider,
            require_local_gpu=require_local_gpu,
        )

        try:
            response = await primary_adapter.execute(request)
            self.cost_accounting.record_cost(request.tenant_id, request.task_id, response.cost_usd)
            return response
        except Exception as primary_err:
            # Try fallback adapters
            fallback_candidates = [
                a
                for a in self._adapters.values()
                if a.is_healthy
                and a.capability.provider_id != primary_adapter.capability.provider_id
                and a.capability.supports_all(request.required_modalities)
                and (not require_local_gpu or a.capability.is_local_gpu)
            ]
            fallback_candidates.sort(
                key=lambda a: (a.capability.priority, a.capability.cost_per_image)
            )

            for fallback in fallback_candidates:
                try:
                    response = await fallback.execute(request)
                    self.cost_accounting.record_cost(
                        request.tenant_id, request.task_id, response.cost_usd
                    )
                    return response
                except Exception:
                    continue

            # If all fallbacks fail, re-raise original error
            if isinstance(primary_err, MultimodalError):
                raise primary_err
            raise ProviderUnavailableError(
                f"Primary provider {primary_adapter.capability.provider_id} and all fallbacks failed: {primary_err}"
            ) from primary_err
