"""Shared context engine with strict provenance tracking, versioning, and trust-level gating."""

import threading
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from atlas_core.contracts.memory import MemoryScope
from pydantic import BaseModel, ConfigDict, Field

from atlas_orchestration.memory import SharedMemoryEngine


class TrustLevel(StrEnum):
    """Trust tier of shared project context items."""

    VERIFIED = "VERIFIED"  # Deterministically validated via test suite or verification gate
    HEURISTIC = "HEURISTIC"  # Specialist proposal, hypothesis, or plan
    UNTRUSTED_REPOSITORY = "UNTRUSTED_REPOSITORY"  # Extracted from source code or comments
    UNTRUSTED_EXTERNAL = "UNTRUSTED_EXTERNAL"  # External network, web, or user-supplied payload


class UnverifiedFactError(Exception):
    """Raised when an unverified agent claim is improperly queried as an authoritative fact."""


class SharedContextItem(BaseModel):
    """Single item of shared engineering context with full provenance and authorization metadata."""

    model_config = ConfigDict(validate_assignment=True)

    key: str
    content: Any
    source: str
    owner_agent_id: str
    version: int = 1
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provenance: str = ""
    trust_level: TrustLevel = TrustLevel.HEURISTIC
    is_authoritative: bool = False
    task_id: str | None = None
    tenant_id: str | None = None


class CodingSharedContext:
    """Thread-safe context broker enforcing tenant boundaries and preventing unverified claim promotion."""

    def __init__(self, memory_engine: SharedMemoryEngine | None = None) -> None:
        self._lock = threading.RLock()
        self.memory = memory_engine or SharedMemoryEngine()
        self.items: dict[str, SharedContextItem] = {}  # scoped_key -> SharedContextItem

    def _make_key(self, key: str, task_id: str | None, tenant_id: str | None) -> str:
        tenant_prefix = f"{tenant_id}:" if tenant_id else "global:"
        task_prefix = f"{task_id}:" if task_id else ""
        return f"{tenant_prefix}{task_prefix}{key}"

    def publish_context(
        self,
        key: str,
        content: Any,
        owner_agent_id: str,
        source: str,
        provenance: str = "",
        trust_level: TrustLevel = TrustLevel.HEURISTIC,
        task_id: str | None = None,
        tenant_id: str | None = None,
    ) -> SharedContextItem:
        """Publish an item to shared context. Unverified claims cannot declare themselves authoritative."""
        with self._lock:
            scoped_k = self._make_key(key, task_id, tenant_id)
            existing = self.items.get(scoped_k)
            version = (existing.version + 1) if existing else 1

            # Only VERIFIED items can be authoritative
            is_auth = trust_level == TrustLevel.VERIFIED

            item = SharedContextItem(
                key=key,
                content=content,
                source=source,
                owner_agent_id=owner_agent_id,
                version=version,
                timestamp=datetime.now(UTC),
                provenance=provenance,
                trust_level=trust_level,
                is_authoritative=is_auth,
                task_id=task_id,
                tenant_id=tenant_id,
            )

            self.items[scoped_k] = item

            # Also mirror into low-level SharedMemoryEngine
            scope = MemoryScope.TASK_SCOPED if task_id else MemoryScope.PROJECT_SCOPED
            self.memory.store(
                key=key,
                value=content,
                scope=scope,
                contributor_id=owner_agent_id,
                task_id=task_id,
                is_untrusted=(
                    trust_level in (TrustLevel.UNTRUSTED_REPOSITORY, TrustLevel.UNTRUSTED_EXTERNAL)
                ),
                metadata={
                    "source": source,
                    "provenance": provenance,
                    "trust_level": trust_level.value,
                    "is_authoritative": is_auth,
                },
            )

            return item

    def get_context(
        self,
        key: str,
        task_id: str | None = None,
        tenant_id: str | None = None,
        require_authoritative: bool = False,
    ) -> SharedContextItem | None:
        """Retrieve context item with optional authority enforcement."""
        with self._lock:
            scoped_k = self._make_key(key, task_id, tenant_id)
            item = self.items.get(scoped_k)
            if not item:
                return None

            if require_authoritative and not item.is_authoritative:
                raise UnverifiedFactError(
                    f"Context item '{key}' is marked {item.trust_level.value} and is NOT authoritative. "
                    "Unverified claims cannot be used as authoritative engineering facts."
                )

            return item

    def promote_to_verified(
        self,
        key: str,
        verifier_agent_id: str,
        task_id: str | None = None,
        tenant_id: str | None = None,
        verification_evidence: str = "",
    ) -> SharedContextItem:
        """Promote a heuristic claim to authoritative VERIFIED status with verifier provenance."""
        with self._lock:
            scoped_k = self._make_key(key, task_id, tenant_id)
            item = self.items.get(scoped_k)
            if not item:
                msg = f"Cannot promote non-existent context item '{key}'."
                raise KeyError(msg)

            item.trust_level = TrustLevel.VERIFIED
            item.is_authoritative = True
            item.version += 1
            item.timestamp = datetime.now(UTC)
            item.provenance += f" | Verified by {verifier_agent_id}: {verification_evidence}"

            return item

    def list_context_items(
        self,
        task_id: str | None = None,
        tenant_id: str | None = None,
        trust_level: TrustLevel | None = None,
    ) -> list[SharedContextItem]:
        """List context items matching task, tenant, and trust filters."""
        with self._lock:
            results: list[SharedContextItem] = []
            for item in self.items.values():
                if task_id and item.task_id != task_id:
                    continue
                if tenant_id and item.tenant_id != tenant_id:
                    continue
                if trust_level and item.trust_level != trust_level:
                    continue
                results.append(item)
            return results
