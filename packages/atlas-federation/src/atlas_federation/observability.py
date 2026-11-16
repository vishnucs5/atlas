"""ATLAS Federated Observability & Correlation Tracing.

Implements distributed W3C tracecontext propagation, cross-organization correlation,
and strict telemetry sanitization to prevent sensitive data leakage.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field


class FederatedTraceContext(BaseModel):
    """W3C-compatible distributed tracecontext carrying cross-boundary correlation."""

    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    span_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_span_id: str | None = None
    correlation_id: str = Field(default_factory=lambda: f"corr_{uuid.uuid4().hex[:12]}")
    originating_org_id: str = "org_atlas_local"

    def to_traceparent(self) -> str:
        """Format as standard W3C 'traceparent' header (00-traceid-spanid-01)."""
        return f"00-{self.trace_id.zfill(32)}-{self.span_id.zfill(16)}-01"

    @classmethod
    def from_traceparent(
        cls,
        header: str,
        correlation_id: str,
        originating_org_id: str,
    ) -> FederatedTraceContext:
        """Parse incoming W3C traceparent header or create child span."""
        parts = header.strip().split("-")
        if len(parts) >= 3 and parts[0] == "00":
            trace_id = parts[1]
            parent_span_id = parts[2]
            return cls(
                trace_id=trace_id,
                span_id=uuid.uuid4().hex[:16],
                parent_span_id=parent_span_id,
                correlation_id=correlation_id,
                originating_org_id=originating_org_id,
            )
        return cls(correlation_id=correlation_id, originating_org_id=originating_org_id)


class FederationTelemetryCollector:
    """Collects and sanitizes distributed metrics and spans across federated nodes."""

    SENSITIVE_KEY_PATTERNS = [
        re.compile(r"token", re.IGNORECASE),
        re.compile(r"secret", re.IGNORECASE),
        re.compile(r"password", re.IGNORECASE),
        re.compile(r"api_?key", re.IGNORECASE),
        re.compile(r"authorization", re.IGNORECASE),
        re.compile(r"private_?data", re.IGNORECASE),
        re.compile(r"credential", re.IGNORECASE),
    ]

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def sanitize_telemetry(self, data: Any) -> Any:
        """Recursively redact secrets, credentials, and sensitive values from telemetry data."""
        if isinstance(data, dict):
            sanitized: dict[str, Any] = {}
            for k, v in data.items():
                if any(pat.search(k) for pat in self.SENSITIVE_KEY_PATTERNS):
                    sanitized[k] = "[REDACTED]"
                else:
                    sanitized[k] = self.sanitize_telemetry(v)
            return sanitized
        if isinstance(data, list):
            return [self.sanitize_telemetry(item) for item in data]
        return data

    def record_event(
        self,
        event_name: str,
        trace_context: FederatedTraceContext,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an observable event, ensuring all attributes are strictly sanitized."""
        cleaned_attributes = self.sanitize_telemetry(attributes or {})
        record = {
            "event_name": event_name,
            "timestamp": time.time(),
            "trace_id": trace_context.trace_id,
            "span_id": trace_context.span_id,
            "correlation_id": trace_context.correlation_id,
            "originating_org": trace_context.originating_org_id,
            "attributes": cleaned_attributes,
        }
        self._events.append(record)
        return record

    def get_events(self) -> list[dict[str, Any]]:
        """Return all recorded telemetry events."""
        return list(self._events)
