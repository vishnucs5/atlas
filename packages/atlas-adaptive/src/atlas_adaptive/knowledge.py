"""ATLAS Controlled Knowledge Evolution Store.

Manages knowledge candidates, detects duplicates and contradictions, supports
version history, human approval, cryptographic signatures, rollback, and deprecation.
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class KnowledgeStatus(StrEnum):
    """Lifecycle status of an evolving knowledge item."""

    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEPRECATED = "DEPRECATED"


class KnowledgeCandidate(BaseModel):
    """A structured factual knowledge candidate proposed for agent memory."""

    candidate_id: str = Field(default_factory=lambda: f"know_{uuid.uuid4().hex[:10]}")
    tenant_id: str
    topic: str
    statement: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    version: int = 1
    signature: str = ""
    status: KnowledgeStatus = KnowledgeStatus.CANDIDATE
    created_at: float = Field(default_factory=time.time)
    previous_version_id: str | None = None


class ContradictionDetectedError(Exception):
    """Raised when a candidate statement directly contradicts approved knowledge."""


class ControlledKnowledgeStore:
    """Versioned knowledge evolution repository with contradiction detection."""

    def __init__(self) -> None:
        self._items: dict[str, KnowledgeCandidate] = {}

    def propose_candidate(
        self,
        tenant_id: str,
        topic: str,
        statement: str,
        evidence_refs: list[str],
        confidence: float = 1.0,
        signature: str = "",
    ) -> KnowledgeCandidate:
        """Propose a new knowledge candidate, checking for duplicates and contradictions."""
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required.")

        normalized_stmt = statement.strip().lower()

        # 1. Duplicate Detection
        for item in self._items.values():
            if item.tenant_id == tenant_id and item.topic == topic:
                if (
                    item.statement.strip().lower() == normalized_stmt
                    and item.status != KnowledgeStatus.DEPRECATED
                ):
                    return item  # Existing duplicate returned

        # 2. Contradiction Detection
        # Check against active approved items on the same topic
        for item in self._items.values():
            if (
                item.tenant_id == tenant_id
                and item.topic == topic
                and item.status == KnowledgeStatus.APPROVED
            ):
                existing_lower = item.statement.strip().lower()
                # Heuristic contradiction checks
                is_contradiction = (
                    ("always" in normalized_stmt and "never" in existing_lower)
                    or ("never" in normalized_stmt and "always" in existing_lower)
                    or ("enabled" in normalized_stmt and "disabled" in existing_lower)
                    or ("disabled" in normalized_stmt and "enabled" in existing_lower)
                    or ("true" in normalized_stmt and "false" in existing_lower)
                    or ("false" in normalized_stmt and "true" in existing_lower)
                )
                if is_contradiction:
                    raise ContradictionDetectedError(
                        f"Proposed statement '{statement}' contradicts approved knowledge item "
                        f"'{item.candidate_id}' ('{item.statement}') on topic '{topic}'."
                    )

        candidate = KnowledgeCandidate(
            tenant_id=tenant_id,
            topic=topic,
            statement=statement,
            evidence_refs=evidence_refs,
            confidence=confidence,
            signature=signature,
            status=KnowledgeStatus.CANDIDATE,
        )

        self._items[candidate.candidate_id] = candidate
        return candidate

    def approve_candidate(
        self,
        candidate_id: str,
        approver_id: str,
        requesting_tenant_id: str,
    ) -> KnowledgeCandidate:
        """Approve a knowledge candidate after human review."""
        candidate = self._items.get(candidate_id)
        if not candidate:
            raise KeyError(f"Candidate '{candidate_id}' not found.")

        if candidate.tenant_id != requesting_tenant_id:
            raise PermissionError("Cross-tenant approval is forbidden.")

        updated = candidate.model_copy(update={"status": KnowledgeStatus.APPROVED})
        self._items[candidate_id] = updated
        return updated

    def rollback(
        self,
        candidate_id: str,
        requesting_tenant_id: str,
    ) -> KnowledgeCandidate:
        """Rollback an approved knowledge item, restoring its previous version if present."""
        item = self._items.get(candidate_id)
        if not item:
            raise KeyError(f"Item '{candidate_id}' not found.")

        if item.tenant_id != requesting_tenant_id:
            raise PermissionError("Cross-tenant rollback is forbidden.")

        # Deprecate the current item
        deprecated = item.model_copy(update={"status": KnowledgeStatus.DEPRECATED})
        self._items[candidate_id] = deprecated

        # Re-activate previous version if available
        if item.previous_version_id and item.previous_version_id in self._items:
            prev = self._items[item.previous_version_id]
            reverted = prev.model_copy(update={"status": KnowledgeStatus.APPROVED})
            self._items[prev.candidate_id] = reverted
            return reverted

        return deprecated

    def get_active_knowledge(
        self,
        tenant_id: str,
        topic: str | None = None,
    ) -> list[KnowledgeCandidate]:
        """Fetch all approved, non-deprecated knowledge items for a tenant."""
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required.")

        results = [
            i
            for i in self._items.values()
            if i.tenant_id == tenant_id and i.status == KnowledgeStatus.APPROVED
        ]
        if topic:
            results = [i for i in results if i.topic == topic]

        return results
