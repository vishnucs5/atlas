"""ATLAS Adaptive Model Router.

Selects optimal model routes based on latency, cost, and historical quality while
strictly enforcing data privacy boundaries and preventing external leakages.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DataPrivacyRoutingError(Exception):
    """Raised when an attempt is made to route sensitive data to an external provider."""


class MediaSensitivity(StrEnum):
    """Data sensitivity classifications for routing governance."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class ModelRouteCandidate(BaseModel):
    """A model endpoint candidate available for routing decisions."""

    model_name: str
    provider_id: str
    supported_modalities: list[str] = Field(default_factory=lambda: ["text"])
    avg_latency_ms: float = 100.0
    cost_per_1k_tokens: float = 0.002
    historical_quality_score: float = 0.90  # [0.0, 1.0]
    is_local_gpu: bool = False
    is_available: bool = True


class AdaptiveModelRouter:
    """Routes requests to the optimal model provider enforcing strict privacy invariants."""

    def __init__(self) -> None:
        self._candidates: dict[str, ModelRouteCandidate] = {}

    def register_candidate(self, candidate: ModelRouteCandidate) -> None:
        """Register a model route candidate."""
        key = f"{candidate.provider_id}:{candidate.model_name}"
        self._candidates[key] = candidate

    def select_route(
        self,
        task_category: str = "general",
        required_modalities: list[str] | None = None,
        sensitivity: MediaSensitivity = MediaSensitivity.INTERNAL,
        min_quality: float = 0.75,
        max_latency_ms: float | None = None,
    ) -> ModelRouteCandidate:
        """Select the best model candidate satisfying quality, latency, and privacy rules."""
        modalities = required_modalities or ["text"]

        # 1. Strict Privacy Filter:
        # Restricted or Confidential data MUST NOT be routed to external cloud models
        is_restricted = sensitivity in (MediaSensitivity.CONFIDENTIAL, MediaSensitivity.RESTRICTED)

        eligible = [
            c
            for c in self._candidates.values()
            if c.is_available
            and c.historical_quality_score >= min_quality
            and all(m in c.supported_modalities for m in modalities)
            and (not is_restricted or c.is_local_gpu)
            and (max_latency_ms is None or c.avg_latency_ms <= max_latency_ms)
        ]

        if not eligible:
            if is_restricted:
                raise DataPrivacyRoutingError(
                    f"Data sensitivity is '{sensitivity.value}', but no local on-premise GPU "
                    "provider is available. Routing to external cloud models is strictly forbidden."
                )
            raise ValueError(
                f"No available model candidates satisfy requirements (modalities={modalities}, "
                f"min_quality={min_quality}, max_latency={max_latency_ms})."
            )

        # 2. Score eligible candidates by composite utility
        # Utility = 0.5 * quality - 0.3 * norm_cost - 0.2 * norm_latency
        def score(c: ModelRouteCandidate) -> float:
            cost_penalty = c.cost_per_1k_tokens * 50.0  # scale cost
            latency_penalty = c.avg_latency_ms / 1000.0  # scale latency
            return (
                (c.historical_quality_score * 0.5) - (cost_penalty * 0.3) - (latency_penalty * 0.2)
            )

        eligible.sort(key=score, reverse=True)
        return eligible[0]

    def list_fallbacks(
        self,
        primary: ModelRouteCandidate,
        sensitivity: MediaSensitivity = MediaSensitivity.INTERNAL,
    ) -> list[ModelRouteCandidate]:
        """Return healthy fallback candidates in priority order."""
        is_restricted = sensitivity in (MediaSensitivity.CONFIDENTIAL, MediaSensitivity.RESTRICTED)

        fallbacks = [
            c
            for c in self._candidates.values()
            if c.is_available
            and (c.provider_id != primary.provider_id or c.model_name != primary.model_name)
            and (not is_restricted or c.is_local_gpu)
        ]
        fallbacks.sort(key=lambda c: c.historical_quality_score, reverse=True)
        return fallbacks
