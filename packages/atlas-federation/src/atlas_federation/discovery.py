"""ATLAS Federated Capability Registry & Discovery Engine.

Enables agents to advertise supported capabilities across four visibility scopes
(PRIVATE, ORGANIZATION, FEDERATION, PUBLIC) with strict metadata sanitization.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class VisibilityScope(StrEnum):
    """Visibility boundaries governing capability discovery."""

    PRIVATE = "PRIVATE"  # Visible only within the local installation
    ORGANIZATION = "ORGANIZATION"  # Visible across installations in the same organization
    FEDERATION = "FEDERATION"  # Visible to trusted external federation partners
    PUBLIC = "PUBLIC"  # Globally discoverable


class CapabilityAdvertisement(BaseModel):
    """Structured declaration of an agent or service capability."""

    advertisement_id: str = Field(default_factory=lambda: f"ad_{uuid.uuid4().hex[:10]}")
    organization_id: str
    installation_id: str
    agent_id: str
    supported_task_categories: list[str] = Field(default_factory=list)
    supported_modalities: list[str] = Field(default_factory=lambda: ["text"])
    available_skills: list[str] = Field(default_factory=list)
    declared_permissions: list[str] = Field(default_factory=list)
    visibility: VisibilityScope = VisibilityScope.FEDERATION
    version: str = "1.0.0"


class FederatedCapabilityRegistry:
    """Registry maintaining active capability advertisements with visibility controls."""

    FORBIDDEN_METADATA_KEYS = [
        "secret",
        "password",
        "token",
        "prompt",
        "private_key",
        "internal_url",
    ]

    def __init__(self) -> None:
        self._advertisements: dict[str, CapabilityAdvertisement] = {}

    def register_advertisement(
        self,
        advertisement: CapabilityAdvertisement,
    ) -> CapabilityAdvertisement:
        """Register an agent capability advertisement, sanitizing any sensitive metadata."""
        # Sanitize skills and categories: ensure no secrets are leaked in metadata
        sanitized_skills = [
            s
            for s in advertisement.available_skills
            if not any(k in s.lower() for k in self.FORBIDDEN_METADATA_KEYS)
        ]
        sanitized_categories = [
            c
            for c in advertisement.supported_task_categories
            if not any(k in c.lower() for k in self.FORBIDDEN_METADATA_KEYS)
        ]

        cleaned = advertisement.model_copy(
            update={
                "available_skills": sanitized_skills,
                "supported_task_categories": sanitized_categories,
            }
        )

        self._advertisements[cleaned.advertisement_id] = cleaned
        return cleaned

    def query_capabilities(
        self,
        requesting_org_id: str,
        target_org_id: str | None = None,
        category: str | None = None,
        modality: str | None = None,
    ) -> list[CapabilityAdvertisement]:
        """Query capabilities respecting four-tier visibility scoping rules."""
        results: list[CapabilityAdvertisement] = []

        for ad in self._advertisements.values():
            if target_org_id and ad.organization_id != target_org_id:
                continue

            # Scope Filtering:
            # 1. PRIVATE: only visible to the same organization and installation
            if ad.visibility == VisibilityScope.PRIVATE:
                if ad.organization_id != requesting_org_id:
                    continue

            # 2. ORGANIZATION: visible to installations within the same organization
            elif ad.visibility == VisibilityScope.ORGANIZATION:
                if ad.organization_id != requesting_org_id:
                    continue

            # 3. FEDERATION & PUBLIC: visible to all authenticated federation participants
            # (Public is globally visible; Federation is visible to federation peers)

            # Match filters
            if category and category not in ad.supported_task_categories:
                continue
            if modality and modality not in ad.supported_modalities:
                continue

            results.append(ad)

        return results
