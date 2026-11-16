"""ATLAS Experience Learning System.

Captures structured task experiences, maintains immutable cryptographic provenance,
separates observed facts from recommendations, and enforces tenant scoping.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class ExperienceOutcome(StrEnum):
    """Outcome category for an execution experience."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PARTIAL = "PARTIAL"


class ExperienceRecord(BaseModel):
    """An immutable record of observed facts and generated recommendations."""

    experience_id: str = Field(default_factory=lambda: f"exp_{uuid.uuid4().hex[:10]}")
    tenant_id: str
    task_category: str
    context_fingerprint: str
    observed_facts: list[str] = Field(default_factory=list)
    generated_recommendations: list[str] = Field(default_factory=list)
    outcome: ExperienceOutcome
    evaluation_score: float
    confidence: float = 1.0
    source_task_id: str
    provenance_hash: str
    is_verified: bool = False
    created_at: float = Field(default_factory=time.time)
    version: int = 1


class ExperienceStore:
    """Store for indexing, retrieving, and verifying execution experiences."""

    def __init__(self) -> None:
        self._records: dict[str, ExperienceRecord] = {}

    @staticmethod
    def compute_provenance_hash(
        tenant_id: str,
        source_task_id: str,
        context_fingerprint: str,
        observed_facts: list[str],
    ) -> str:
        """Compute content-addressed SHA-256 provenance hash for an experience."""
        data = (
            f"{tenant_id}:{source_task_id}:{context_fingerprint}:{'|'.join(sorted(observed_facts))}"
        )
        return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"

    def record_experience(
        self,
        tenant_id: str,
        task_category: str,
        context_fingerprint: str,
        observed_facts: list[str],
        generated_recommendations: list[str],
        outcome: ExperienceOutcome,
        evaluation_score: float,
        source_task_id: str,
        confidence: float = 1.0,
        is_verified: bool = False,
    ) -> ExperienceRecord:
        """Create and store a new experience record with provenance."""
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id must be provided to record an experience.")

        prov_hash = self.compute_provenance_hash(
            tenant_id=tenant_id,
            source_task_id=source_task_id,
            context_fingerprint=context_fingerprint,
            observed_facts=observed_facts,
        )

        record = ExperienceRecord(
            tenant_id=tenant_id,
            task_category=task_category,
            context_fingerprint=context_fingerprint,
            observed_facts=observed_facts,
            generated_recommendations=generated_recommendations,
            outcome=outcome,
            evaluation_score=evaluation_score,
            confidence=confidence,
            source_task_id=source_task_id,
            provenance_hash=prov_hash,
            is_verified=is_verified,
        )

        self._records[record.experience_id] = record
        return record

    def get_authoritative_recommendations(
        self,
        tenant_id: str,
        context_fingerprint: str,
    ) -> list[str]:
        """Return only verified recommendations matching the given context.

        Unverified recommendations are strictly prohibited from becoming authoritative.
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required.")

        recommendations: list[str] = []
        for r in self._records.values():
            if r.tenant_id == tenant_id and r.context_fingerprint == context_fingerprint:
                if r.is_verified and r.outcome == ExperienceOutcome.SUCCESS:
                    recommendations.extend(r.generated_recommendations)

        return list(dict.fromkeys(recommendations))  # Unique preserve order

    def verify_experience(
        self,
        experience_id: str,
        requesting_tenant_id: str,
    ) -> ExperienceRecord:
        """Mark an experience as verified after independent outcome validation."""
        record = self._records.get(experience_id)
        if record is None:
            raise KeyError(f"Experience '{experience_id}' not found.")

        if record.tenant_id != requesting_tenant_id:
            raise PermissionError(
                f"Unauthorized cross-tenant verification attempt for experience '{experience_id}'."
            )

        updated = record.model_copy(update={"is_verified": True})
        self._records[experience_id] = updated
        return updated

    def query(
        self,
        tenant_id: str,
        task_category: str | None = None,
    ) -> list[ExperienceRecord]:
        """Query experiences strictly isolated to the specified tenant."""
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required.")

        results = [r for r in self._records.values() if r.tenant_id == tenant_id]
        if task_category:
            results = [r for r in results if r.task_category == task_category]

        results.sort(key=lambda r: r.created_at, reverse=True)
        return results
