"""ATLAS Event Ingestion & Webhook Trigger Engine.

Provides authenticated webhook verification, deduplication guards, tenant-scoped subscriptions,
per-tenant secret isolation, and process dispatch.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TriggerType(StrEnum):
    """Event ingestion channels."""

    WEBHOOK = "WEBHOOK"
    MESSAGE_BUS = "MESSAGE_BUS"
    CRON = "CRON"
    FILE_SYSTEM = "FILE_SYSTEM"
    MANUAL = "MANUAL"


class TriggerError(Exception):
    """Base exception for event and trigger errors."""


class ForgedEventError(TriggerError):
    """Raised when an incoming webhook or event fails cryptographic signature verification."""


class DuplicateEventError(TriggerError):
    """Raised when an event with a duplicate ID or correlation key is submitted."""


class UnauthorizedTriggerError(TriggerError):
    """Raised when an event attempts to trigger a process outside its tenant scope or without a configured secret."""


class BusinessEvent(BaseModel):
    """Structured, authenticated business event payload."""

    event_id: str = Field(default_factory=lambda: f"bev_{uuid.uuid4().hex[:12]}")
    tenant_id: str
    event_type: str
    source: str
    correlation_id: str = Field(default_factory=lambda: f"corr_{uuid.uuid4().hex[:12]}")
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
    signature: str = ""


class EventTriggerEngine:
    """Manages event subscriptions, webhook verification, deduplication, and process dispatch."""

    def __init__(
        self,
        secret_key: str | None = None,
        tenant_secrets: dict[str, str] | None = None,
        storage: Any | None = None,
    ) -> None:
        # Per-tenant secret isolation (no static default fallback secret!)
        self._tenant_secrets: dict[str, str] = dict(tenant_secrets or {})
        if secret_key:
            self._tenant_secrets["__default__"] = secret_key

        self.storage = storage
        self._processed_event_ids: dict[str, float] = {}  # event_id -> timestamp
        self._subscriptions: dict[str, list[str]] = {}  # event_type -> list of process_def_ids

    def provision_tenant_secret(self, tenant_id: str, secret: str) -> None:
        """Explicitly provision a cryptographically secure webhook secret for a tenant."""
        if not secret or len(secret) < 16:
            raise ValueError("Webhook secret must be at least 16 characters long.")
        self._tenant_secrets[tenant_id] = secret

    def rotate_tenant_secret(self, tenant_id: str, new_secret: str) -> None:
        """Rotate the webhook secret for a specific tenant."""
        self.provision_tenant_secret(tenant_id, new_secret)

    def subscribe(self, event_type: str, process_definition_id: str) -> None:
        """Register a process definition to trigger on a specific event type."""
        subs = self._subscriptions.setdefault(event_type, [])
        if process_definition_id not in subs:
            subs.append(process_definition_id)

    def _get_secret_for_tenant(self, tenant_id: str | None = None) -> str:
        """Resolve the webhook secret for a tenant with strict absence rejection."""
        if tenant_id and tenant_id in self._tenant_secrets:
            return self._tenant_secrets[tenant_id]
        if "__default__" in self._tenant_secrets:
            return self._tenant_secrets["__default__"]
        raise UnauthorizedTriggerError(
            f"No webhook secret configured for tenant '{tenant_id or 'unknown'}'. "
            "Insecure static default secrets are prohibited."
        )

    def compute_signature(self, raw_body: bytes, tenant_id: str | None = None) -> str:
        """Compute HMAC-SHA256 signature for payload verification using the tenant's secret."""
        secret = self._get_secret_for_tenant(tenant_id)
        return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    def verify_webhook(
        self,
        raw_body: bytes,
        signature_header: str,
        tenant_id: str,
        timestamp: float | None = None,
        max_drift_seconds: float = 300.0,
    ) -> BusinessEvent:
        """Verify HMAC signature and parse raw webhook body into a BusinessEvent."""
        # 1. Resolve secret strictly
        secret = self._get_secret_for_tenant(tenant_id)

        # 2. Timestamp & Replay Window Protection
        now = time.time()
        if timestamp is not None and abs(now - timestamp) > max_drift_seconds:
            raise ForgedEventError(
                f"Webhook verification failed: Timestamp drift ({abs(now - timestamp):.1f}s) "
                f"exceeds tolerance of {max_drift_seconds}s."
            )

        # 3. Constant-Time Signature Comparison
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        cleaned_sig = signature_header.removeprefix("sha256=").strip()

        if not hmac.compare_digest(expected, cleaned_sig):
            raise ForgedEventError("Webhook verification failed: Invalid HMAC-SHA256 signature.")

        # 4. Parse Body
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            raise ForgedEventError(f"Malformed webhook JSON body: {exc}") from exc

        # 5. Deterministic Event Identity (Guarantees replay detection across window)
        body_hash = hashlib.sha256(raw_body).hexdigest()
        provider_event_id = data.get("id") or data.get("event_id") or data.get("delivery_id")
        if provider_event_id:
            deterministic_id = f"bev_{hashlib.sha256(f'{tenant_id}:{provider_event_id}'.encode()).hexdigest()[:24]}"
        else:
            # Deterministic hash of tenant, signature, timestamp, and body
            ts_str = f"{timestamp:.3f}" if timestamp is not None else ""
            deterministic_id = f"bev_{hashlib.sha256(f'{tenant_id}:{cleaned_sig}:{ts_str}:{body_hash}'.encode()).hexdigest()[:24]}"

        event = BusinessEvent(
            event_id=deterministic_id,
            tenant_id=tenant_id,
            event_type=data.get("event_type", "webhook.received"),
            source=data.get("source", "external_webhook"),
            correlation_id=data.get("correlation_id", f"corr_{uuid.uuid4().hex[:12]}"),
            payload=data.get("data", {}),
            timestamp=timestamp or now,
            signature=cleaned_sig,
        )

        return event

    def ingest_event(self, event: BusinessEvent) -> list[str]:
        """Ingest event with durable deduplication guard and return matching process definition IDs."""
        now = time.time()

        # Clean old processed IDs (older than 3600 seconds)
        cutoff = now - 3600.0
        expired = [k for k, ts in self._processed_event_ids.items() if ts < cutoff]
        for k in expired:
            self._processed_event_ids.pop(k, None)

        # 1. In-memory deduplication guard
        if event.event_id in self._processed_event_ids:
            raise DuplicateEventError(
                f"Duplicate event '{event.event_id}' detected and suppressed."
            )

        # 2. Durable database deduplication guard
        if self.storage and hasattr(self.storage, "has_event_inbox"):
            if self.storage.has_event_inbox(event.tenant_id, event.event_id):
                raise DuplicateEventError(
                    f"Duplicate event '{event.event_id}' detected and suppressed in durable storage."
                )

        if self.storage and hasattr(self.storage, "record_event_inbox"):
            recorded = self.storage.record_event_inbox(
                event.event_id,
                event.tenant_id,
                event.source,
                event.event_type,
                event.payload,
            )
            if not recorded:
                raise DuplicateEventError(
                    f"Duplicate event '{event.event_id}' detected during concurrent database ingestion."
                )

        self._processed_event_ids[event.event_id] = now

        # Find matching subscriptions
        return self._subscriptions.get(event.event_type, [])
