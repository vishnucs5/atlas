"""ATLAS Multimodal Episodic Memory & Isolation Store.

Stores lightweight semantic metadata and offloads heavy media binaries to
the ArtifactManager, enforcing strict multi-tenant boundary checks.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from atlas_multimodal.provider import MultimodalModality


class MultimodalMemoryError(Exception):
    """Base exception for episodic memory operations."""


class CrossTenantMemoryAccessViolation(MultimodalMemoryError):
    """Raised when an agent attempts to access multimodal artifacts of another tenant."""


class TenantContextRequiredError(MultimodalMemoryError):
    """Raised when an operation is attempted without an explicit tenant identifier."""


class MultimodalMemoryRecord(BaseModel):
    """Metadata representing a persisted multimodal artifact in episodic memory."""

    record_id: str = Field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:10]}")
    tenant_id: str
    task_id: str
    timestamp: float = Field(default_factory=time.time)
    modality: MultimodalModality
    summary: str
    semantic_tags: list[str] = Field(default_factory=list)
    artifact_ref: str
    artifact_hash: str
    byte_size: int
    extracted_text: str | None = None


class MultimodalMemoryStore:
    """Episodic memory store with binary artifact offloading and strict tenant isolation."""

    def __init__(self, artifact_manager: Any | None = None) -> None:
        self.artifact_manager = artifact_manager
        self._records: dict[str, MultimodalMemoryRecord] = {}

    def store_observation(
        self,
        tenant_id: str,
        task_id: str,
        modality: MultimodalModality,
        raw_bytes: bytes,
        summary: str,
        semantic_tags: list[str] | None = None,
        extracted_text: str | None = None,
        artifact_filename: str | None = None,
    ) -> MultimodalMemoryRecord:
        """Persist media binary into artifact storage and record its semantic index."""
        if not tenant_id or not tenant_id.strip():
            raise TenantContextRequiredError(
                "Cannot store multimodal memory without explicit tenant_id."
            )

        # Compute content-addressed SHA-256 hash
        content_hash = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
        filename = artifact_filename or f"{modality.value}_{uuid.uuid4().hex[:8]}.bin"

        # Offload to ArtifactManager if available
        if self.artifact_manager is not None:
            if hasattr(self.artifact_manager, "save_artifact"):
                artifact_ref = self.artifact_manager.save_artifact(
                    task_id=task_id,
                    name=filename,
                    data=raw_bytes,
                )
            elif hasattr(self.artifact_manager, "store_artifact"):
                artifact_record = self.artifact_manager.store_artifact(
                    task_id=task_id,
                    name=filename,
                    content=raw_bytes,
                    metadata={"tenant_id": tenant_id, "modality": modality.value},
                )
                artifact_ref = getattr(artifact_record, "uri", str(artifact_record))
            else:
                artifact_ref = f"artifacts/{tenant_id}/{task_id}/{filename}"
        else:
            artifact_ref = f"artifacts/{tenant_id}/{task_id}/{filename}"

        record = MultimodalMemoryRecord(
            tenant_id=tenant_id,
            task_id=task_id,
            modality=modality,
            summary=summary,
            semantic_tags=semantic_tags or [],
            artifact_ref=artifact_ref,
            artifact_hash=content_hash,
            byte_size=len(raw_bytes),
            extracted_text=extracted_text,
        )

        self._records[record.record_id] = record
        return record

    def get_record(
        self,
        record_id: str,
        requesting_tenant_id: str,
    ) -> MultimodalMemoryRecord:
        """Retrieve a specific record, enforcing tenant boundary checks."""
        if not requesting_tenant_id or not requesting_tenant_id.strip():
            raise TenantContextRequiredError(
                "requesting_tenant_id is required to fetch memory records."
            )

        record = self._records.get(record_id)
        if record is None:
            raise KeyError(f"Memory record '{record_id}' not found.")

        if record.tenant_id != requesting_tenant_id:
            raise CrossTenantMemoryAccessViolation(
                f"Unauthorized cross-tenant access! Tenant '{requesting_tenant_id}' "
                f"attempted to access record '{record_id}' belonging to tenant '{record.tenant_id}'."
            )

        return record

    def query(
        self,
        tenant_id: str,
        tag: str | None = None,
        modality: MultimodalModality | None = None,
        task_id: str | None = None,
    ) -> list[MultimodalMemoryRecord]:
        """Query memory records strictly scoped to the specified tenant."""
        if not tenant_id or not tenant_id.strip():
            raise TenantContextRequiredError(
                "Querying episodic memory requires a non-empty tenant_id."
            )

        results = [r for r in self._records.values() if r.tenant_id == tenant_id]

        if task_id:
            results = [r for r in results if r.task_id == task_id]
        if modality:
            results = [r for r in results if r.modality == modality]
        if tag:
            results = [r for r in results if tag in r.semantic_tags]

        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results
