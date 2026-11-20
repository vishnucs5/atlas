"""Validated zero-cost model catalog contracts and lookup helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelEligibilityStatus(StrEnum):
    FREE_VERIFIED = "FREE_VERIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INELIGIBLE = "INELIGIBLE"


class ProviderAuthStatus(StrEnum):
    CONFIGURED = "CONFIGURED"
    PRESENT_UNVERIFIED = "PRESENT_UNVERIFIED"
    NEEDS_KEY = "NEEDS_KEY"
    INVALID_KEY = "INVALID_KEY"
    FORBIDDEN = "FORBIDDEN"


class ProviderBillingStatus(StrEnum):
    VERIFIED_FREE = "VERIFIED_FREE"
    ATTESTED_FREE = "ATTESTED_FREE"
    UNKNOWN = "UNKNOWN"
    BILLABLE = "BILLABLE"


class ProviderRuntimeStatus(StrEnum):
    HEALTHY = "HEALTHY"
    RATE_LIMITED = "RATE_LIMITED"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class InventorySource(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    url: str
    method: str = "GET"
    auth: str = "none"
    refresh_interval_minutes: int = Field(ge=1, le=10080)
    eligibility_filter: str


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    id: str
    name: str
    provider: str
    classification: str = "fixed_model"
    availability_class: str = "provider_free_tier"
    context_window: int | str | None = None
    max_output_tokens: int | str | None = None
    capabilities: list[str] | str = Field(default_factory=list)
    modalities: list[str] = Field(default_factory=lambda: ["text"])
    pricing: dict[str, float] = Field(default_factory=dict)
    eligibility_status: ModelEligibilityStatus
    verification_date: datetime | None = None
    review_expiry: datetime | None = None
    verification_sources: list[str] = Field(
        default_factory=list, alias="official_verification_sources"
    )
    privacy_disclosure: str = ""
    known_free_until: datetime | None = None
    is_default: bool = False
    capability_evidence: str = ""
    account_level_quota: str = ""
    billing_and_overage_policy: str = ""

    @field_validator("id", "name", "provider")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("catalog model identifiers and names cannot be empty")
        return value

    def is_currently_eligible(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        if self.eligibility_status != ModelEligibilityStatus.FREE_VERIFIED:
            return False
        if self.review_expiry is not None and current > self.review_expiry:
            return False
        if self.known_free_until is not None and current > self.known_free_until:
            return False
        return True

    @property
    def capability_names(self) -> list[str]:
        return self.capabilities if isinstance(self.capabilities, list) else []


class ProviderEntry(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    display_name: str
    signup_url: str | None = None
    env_var: str | None = None
    approved_origins: list[str] = Field(default_factory=list)
    approved_api_bases: list[str] = Field(default_factory=list)
    account_billing_policy: str
    inventory_source: InventorySource | None = None
    provider_status: str = "ACTIVE"
    models: list[dict[str, Any]] = Field(default_factory=list)
    required_account_config: list[str] = Field(default_factory=list)


class CatalogueDocument(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    version: str
    last_audit_date: datetime | None = None
    default_model: str
    providers: dict[str, ProviderEntry]


class CatalogValidationError(ValueError):
    """The catalog is malformed or does not satisfy its safety invariants."""


class FreeModelCatalogue:
    """Loads and serves only exact catalog entries with current free evidence."""

    def __init__(self, document: CatalogueDocument) -> None:
        self.document = document
        self._entries: dict[str, ModelEntry] = {}
        for provider_id, provider in document.providers.items():
            for raw in provider.models:
                data = dict(raw)
                data.setdefault("provider", provider_id)
                try:
                    entry = ModelEntry.model_validate(data)
                except (ValueError, TypeError) as exc:
                    raise CatalogValidationError(
                        f"Invalid model catalog entry for provider {provider_id}: {exc}"
                    ) from exc
                if entry.id in self._entries:
                    raise CatalogValidationError(f"Duplicate model identifier: {entry.id}")
                if entry.eligibility_status == ModelEligibilityStatus.FREE_VERIFIED and not (
                    entry.verification_sources and entry.review_expiry
                ):
                    raise CatalogValidationError(
                        f"FREE_VERIFIED entry {entry.id} requires verification sources and review expiry"
                    )
                self._entries[entry.id] = entry

    @classmethod
    def load(cls, path: Path) -> FreeModelCatalogue:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            document = CatalogueDocument.model_validate(payload)
            return cls(document)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise CatalogValidationError(f"Could not load model catalog {path}: {exc}") from exc

    @classmethod
    def from_json(cls, raw: str) -> FreeModelCatalogue:
        try:
            return cls(CatalogueDocument.model_validate_json(raw))
        except (ValueError, TypeError) as exc:
            raise CatalogValidationError(f"Could not parse model catalog: {exc}") from exc

    @property
    def default_model(self) -> str:
        return self.document.default_model

    @property
    def entries(self) -> tuple[ModelEntry, ...]:
        return tuple(self._entries.values())

    def get_model(self, model_id: str) -> ModelEntry | None:
        return self._entries.get(model_id)

    def eligible_models(self) -> tuple[ModelEntry, ...]:
        return tuple(entry for entry in self._entries.values() if entry.is_currently_eligible())

    def provider(self, provider_id: str) -> ProviderEntry | None:
        return self.document.providers.get(provider_id)
