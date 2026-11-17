"""ATLAS Business Event and Trigger Engine.

Provides HMAC-authenticated webhook ingestion, event correlation, scheduled triggers,
event deduplication, and tenant-scoped subscription routing.
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
    """Supported trigger types for starting or resuming processes."""

    WEBHOOK = "WEBHOOK"
    SCHEDULED = "SCHEDULED"
    BUSINESS_EVENT = "BUSINESS_EVENT"
    API_CALL = "API_CALL"


class TriggerError(Exception):
    """Base exception for event and trigger errors."""


class ForgedEventError(TriggerError):
    """Raised when an incoming webhook or event fails cryptographic signature verification."""


class DuplicateEventError(TriggerError):
    """Raised when an event with a duplicate ID or correlation key is submitted."""


class UnauthorizedTriggerError(TriggerError):
    """Raised when an event attempts to trigger a process outside its tenant scope."""


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

    def __init__(self, secret_key: str = "atlas-process-trigger-secret-v16") -> None:
        self.secret_key = secret_key
        self._processed_event_ids: dict[str, float] = {}  # event_id -> timestamp
        self._subscriptions: dict[str, list[str]] = {}  # event_type -> list of process_def_ids

    def subscribe(self, event_type: str, process_definition_id: str) -> None:
        """Register a process definition to trigger on a specific event type."""
        subs = self._subscriptions.setdefault(event_type, [])
        if process_definition_id not in subs:
            subs.append(process_definition_id)

    def compute_signature(self, raw_body: bytes) -> str:
        """Compute HMAC-SHA256 signature for payload verification."""
        return hmac.new(self.secret_key.encode(), raw_body, hashlib.sha256).hexdigest()

    def verify_webhook(
        self,
        raw_body: bytes,
        signature_header: str,
        tenant_id: str,
    ) -> BusinessEvent:
        """Verify HMAC signature and parse raw webhook body into a BusinessEvent."""
        expected = self.compute_signature(raw_body)
        cleaned_sig = signature_header.removeprefix("sha256=").strip()

        if not hmac.compare_digest(expected, cleaned_sig):
            raise ForgedEventError("Webhook verification failed: Invalid HMAC-SHA256 signature.")

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            raise ForgedEventError(f"Malformed webhook JSON body: {exc}") from exc

        event = BusinessEvent(
            tenant_id=tenant_id,
            event_type=data.get("event_type", "webhook.received"),
            source=data.get("source", "external_webhook"),
            correlation_id=data.get("correlation_id", f"corr_{uuid.uuid4().hex[:12]}"),
            payload=data.get("data", {}),
            signature=cleaned_sig,
        )

        return event

    def ingest_event(self, event: BusinessEvent) -> list[str]:
        """Ingest event with deduplication guard and return matching process definition IDs."""
        now = time.time()

        # Clean old processed IDs (older than 3600 seconds)
        cutoff = now - 3600.0
        expired = [k for k, ts in self._processed_event_ids.items() if ts < cutoff]
        for k in expired:
            self._processed_event_ids.pop(k, None)

        # Deduplication Guard
        if event.event_id in self._processed_event_ids:
            raise DuplicateEventError(
                f"Duplicate event '{event.event_id}' detected and suppressed."
            )

        self._processed_event_ids[event.event_id] = now

        # Find matching subscriptions
        return self._subscriptions.get(event.event_type, [])
