"""OpenTelemetry-compatible distributed tracing for ATLAS runtime.

Provides W3C traceparent context propagation, distributed span hierarchies,
contextvar-based span scoping, span attributes, events, error recording,
and OTLP payload formatting.
"""

from __future__ import annotations

import contextvars
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

# W3C Trace Context Regex: 00-{32hex}-{16hex}-{2hex}
TRACEPARENT_REGEX = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


class SpanContext:
    """Immutable W3C-compliant distributed span context."""

    def __init__(
        self,
        trace_id: str,
        span_id: str,
        trace_flags: str = "01",
        trace_state: str = "",
    ) -> None:
        self.trace_id = trace_id.lower()
        self.span_id = span_id.lower()
        self.trace_flags = trace_flags.lower()
        self.trace_state = trace_state

    def to_traceparent(self) -> str:
        """Render W3C traceparent header value."""
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags}"

    @classmethod
    def from_traceparent(cls, header: str) -> SpanContext | None:
        """Parse W3C traceparent header."""
        if not header:
            return None
        match = TRACEPARENT_REGEX.match(header.strip().lower())
        if not match:
            return None
        trace_id, span_id, trace_flags = match.groups()
        if trace_id == "0" * 32 or span_id == "0" * 16:
            return None
        return cls(trace_id=trace_id, span_id=span_id, trace_flags=trace_flags)

    @classmethod
    def generate_trace_id(cls) -> str:
        """Generate a random 128-bit trace ID (32 hex characters)."""
        return secrets.token_hex(16)

    @classmethod
    def generate_span_id(cls) -> str:
        """Generate a random 64-bit span ID (16 hex characters)."""
        return secrets.token_hex(8)


class Span:
    """Distributed tracing span tracking execution interval, attributes, and events."""

    def __init__(
        self,
        name: str,
        context: SpanContext,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.context = context
        self.parent_span_id = parent_span_id
        self.start_time: datetime = datetime.now(UTC)
        self.start_perf: float = time.perf_counter()
        self.end_time: datetime | None = None
        self.end_perf: float | None = None
        self.attributes: dict[str, Any] = dict(attributes or {})
        self.events: list[dict[str, Any]] = []
        self.status: str = "OK"  # "OK" | "ERROR"
        self.status_description: str | None = None

    def set_attribute(self, key: str, value: Any) -> Span:
        """Attach a metadata attribute to the span."""
        self.attributes[key] = value
        return self

    def set_attributes(self, attributes: dict[str, Any]) -> Span:
        """Attach multiple metadata attributes to the span."""
        self.attributes.update(attributes)
        return self

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> Span:
        """Record an in-span milestone event."""
        self.events.append(
            {
                "name": name,
                "timestamp": datetime.now(UTC).isoformat(),
                "attributes": attributes or {},
            }
        )
        return self

    def record_exception(self, exc: Exception) -> Span:
        """Record an exception event and transition span status to ERROR."""
        self.status = "ERROR"
        self.status_description = str(exc)
        self.add_event(
            "exception",
            {
                "exception.type": type(exc).__name__,
                "exception.message": str(exc),
            },
        )
        return self

    def set_status(self, status: str, description: str | None = None) -> Span:
        """Set span completion status."""
        self.status = status.upper()
        self.status_description = description
        return self

    def end(self) -> None:
        """Complete span and calculate duration."""
        if self.end_time is None:
            self.end_time = datetime.now(UTC)
            self.end_perf = time.perf_counter()

    @property
    def duration_ms(self) -> float:
        """Elapsed duration in milliseconds."""
        if self.end_perf is not None:
            return (self.end_perf - self.start_perf) * 1000.0
        return (time.perf_counter() - self.start_perf) * 1000.0

    def to_dict(self) -> dict[str, Any]:
        """Convert span to canonical dictionary format."""
        return {
            "name": self.name,
            "trace_id": self.context.trace_id,
            "span_id": self.context.span_id,
            "parent_span_id": self.parent_span_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": round(self.duration_ms, 3),
            "status": self.status,
            "status_description": self.status_description,
            "attributes": self.attributes,
            "events": self.events,
        }


# Context variable holding the currently active Span in the execution flow
_active_span_var: contextvars.ContextVar[Span | None] = contextvars.ContextVar(
    "atlas_active_span", default=None
)


class Tracer:
    """Thread-safe OpenTelemetry-compatible Tracer instance."""

    def __init__(self, service_name: str = "atlas") -> None:
        self.service_name = service_name
        self._lock = threading.Lock()
        self._finished_spans: list[Span] = []
        self._max_buffered_spans = 2000

    def get_current_span(self) -> Span | None:
        """Retrieve the currently active span in the async/thread context."""
        return _active_span_var.get()

    def start_span(
        self,
        name: str,
        parent_context: SpanContext | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        """Start a new span, establishing parentage from parent_context or ambient active span."""
        current_active = self.get_current_span()

        if parent_context is not None:
            trace_id = parent_context.trace_id
            parent_span_id = parent_context.span_id
            trace_flags = parent_context.trace_flags
        elif current_active is not None:
            trace_id = current_active.context.trace_id
            parent_span_id = current_active.context.span_id
            trace_flags = current_active.context.trace_flags
        else:
            trace_id = SpanContext.generate_trace_id()
            parent_span_id = None
            trace_flags = "01"

        span_id = SpanContext.generate_span_id()
        context = SpanContext(trace_id=trace_id, span_id=span_id, trace_flags=trace_flags)

        merged_attrs = {"service.name": self.service_name}
        if attributes:
            merged_attrs.update(attributes)

        return Span(
            name=name,
            context=context,
            parent_span_id=parent_span_id,
            attributes=merged_attrs,
        )

    @contextmanager
    def span(
        self,
        name: str,
        parent_context: SpanContext | None = None,
        attributes: dict[str, Any] | None = None,
    ):
        """Context manager for tracing execution blocks with automatic lifecycle management."""
        span = self.start_span(name, parent_context=parent_context, attributes=attributes)
        token = _active_span_var.set(span)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            raise
        finally:
            span.end()
            _active_span_var.reset(token)
            self._record_finished_span(span)

    def _record_finished_span(self, span: Span) -> None:
        with self._lock:
            if len(self._finished_spans) >= self._max_buffered_spans:
                self._finished_spans.pop(0)
            self._finished_spans.append(span)

    def get_finished_spans(self) -> list[Span]:
        """Retrieve copy of all recorded finished spans."""
        with self._lock:
            return list(self._finished_spans)

    def clear_spans(self) -> None:
        """Clear the in-memory span buffer."""
        with self._lock:
            self._finished_spans.clear()

    def inject_headers(self, headers: dict[str, str], span: Span | None = None) -> dict[str, str]:
        """Inject W3C traceparent header into an outbound dictionary."""
        target_span = span or self.get_current_span()
        if target_span is not None:
            headers["traceparent"] = target_span.context.to_traceparent()
        return headers

    def extract_context(self, headers: dict[str, str]) -> SpanContext | None:
        """Extract SpanContext from W3C traceparent header in headers dictionary."""
        # Case-insensitive header lookup
        for key, val in headers.items():
            if key.lower() == "traceparent":
                return SpanContext.from_traceparent(val)
        return None

    def export_otlp_json(self) -> dict[str, Any]:
        """Render recorded spans in standard OpenTelemetry ResourceSpans JSON structure."""
        with self._lock:
            spans_data = []
            for s in self._finished_spans:
                spans_data.append(
                    {
                        "traceId": s.context.trace_id,
                        "spanId": s.context.span_id,
                        "parentSpanId": s.parent_span_id or "",
                        "name": s.name,
                        "kind": 1,  # SPAN_KIND_INTERNAL
                        "startTimeUnixNano": int(s.start_time.timestamp() * 1e9),
                        "endTimeUnixNano": int(s.end_time.timestamp() * 1e9) if s.end_time else 0,
                        "attributes": [
                            {"key": k, "value": {"stringValue": str(v)}}
                            for k, v in s.attributes.items()
                        ],
                        "status": {
                            "code": 1 if s.status == "OK" else 2,
                            "message": s.status_description or "",
                        },
                    }
                )

        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": self.service_name}}
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "atlas.tracer", "version": "1.0.0"},
                            "spans": spans_data,
                        }
                    ],
                }
            ]
        }


# Global default Tracer instance
_GLOBAL_TRACER: Tracer | None = None
_TRACER_LOCK = threading.Lock()


def get_tracer(service_name: str | None = None) -> Tracer:
    """Retrieve or initialize the global ATLAS Tracer."""
    global _GLOBAL_TRACER
    with _TRACER_LOCK:
        if _GLOBAL_TRACER is None:
            name = service_name or os.getenv("OTEL_SERVICE_NAME", "atlas")
            _GLOBAL_TRACER = Tracer(service_name=name)
        return _GLOBAL_TRACER
