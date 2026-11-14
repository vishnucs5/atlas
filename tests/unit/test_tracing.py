"""Unit tests for OpenTelemetry distributed tracing and metrics integration."""

import pytest
from atlas_api.main import app
from atlas_observability import (
    SpanContext,
    Tracer,
    get_tracer,
)
from fastapi.testclient import TestClient


def test_span_context_w3c_traceparent():
    """Verify W3C traceparent formatting and parsing."""
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    span_id = "00f067aa0ba902b7"
    ctx = SpanContext(trace_id=trace_id, span_id=span_id, trace_flags="01")

    header = ctx.to_traceparent()
    assert header == f"00-{trace_id}-{span_id}-01"

    parsed = SpanContext.from_traceparent(header)
    assert parsed is not None
    assert parsed.trace_id == trace_id
    assert parsed.span_id == span_id
    assert parsed.trace_flags == "01"

    # Invalid headers
    assert SpanContext.from_traceparent("invalid") is None
    assert SpanContext.from_traceparent("01-traceid-spanid-01") is None
    assert SpanContext.from_traceparent("00-" + "0" * 32 + "-spanid-01") is None


def test_tracer_span_hierarchy_and_context():
    """Verify span parenting, attributes, events, and duration."""
    tracer = Tracer(service_name="test-service")

    with tracer.span("parent_operation", attributes={"env": "test"}) as parent:
        parent.set_attribute("user.id", "usr_123")
        parent.add_event("stage_1_completed", {"items": 5})

        assert tracer.get_current_span() is parent

        with tracer.span("child_operation") as child:
            assert tracer.get_current_span() is child
            assert child.parent_span_id == parent.context.span_id
            assert child.context.trace_id == parent.context.trace_id
            child.set_attribute("db.query", "SELECT 1")

        assert tracer.get_current_span() is parent

    assert parent.end_time is not None
    assert parent.duration_ms >= 0.0

    finished = tracer.get_finished_spans()
    assert len(finished) == 2
    # Child finished first, then parent
    assert finished[0].name == "child_operation"
    assert finished[1].name == "parent_operation"


def test_tracer_exception_recording():
    """Verify span records unhandled exceptions and transitions status to ERROR."""
    tracer = Tracer(service_name="test-service")

    with pytest.raises(ValueError, match="simulated failure"):
        with tracer.span("failing_operation") as span:
            span.set_attribute("step", "init")
            raise ValueError("simulated failure")

    finished = tracer.get_finished_spans()
    assert len(finished) == 1
    err_span = finished[0]
    assert err_span.status == "ERROR"
    assert "simulated failure" in (err_span.status_description or "")
    assert len(err_span.events) == 1
    assert err_span.events[0]["name"] == "exception"


def test_tracer_otlp_json_export():
    """Verify spans export to valid OpenTelemetry ResourceSpans JSON structure."""
    tracer = Tracer(service_name="atlas-test-otlp")
    with tracer.span("otlp_task", attributes={"component": "executor"}):
        pass

    otlp_payload = tracer.export_otlp_json()
    assert "resourceSpans" in otlp_payload
    resource_span = otlp_payload["resourceSpans"][0]
    assert resource_span["resource"]["attributes"][0]["value"]["stringValue"] == "atlas-test-otlp"
    spans = resource_span["scopeSpans"][0]["spans"]
    assert len(spans) >= 1
    assert spans[0]["name"] == "otlp_task"


def test_api_tracing_middleware_and_traceparent_injection():
    """Verify FastAPI automatically traces HTTP requests and returns traceparent header."""
    client = TestClient(app)
    tracer = get_tracer("atlas-api")
    tracer.clear_spans()

    inbound_trace_id = "55555555555555555555555555555555"
    inbound_span_id = "7777777777777777"
    inbound_traceparent = f"00-{inbound_trace_id}-{inbound_span_id}-01"

    res = client.get("/healthz", headers={"traceparent": inbound_traceparent})
    assert res.status_code == 200
    assert "traceparent" in res.headers
    resp_traceparent = res.headers["traceparent"]
    assert resp_traceparent.startswith(f"00-{inbound_trace_id}-")

    # Metrics endpoint check
    metrics_res = client.get("/metrics")
    assert metrics_res.status_code == 200
    assert "atlas_http_requests_total" in metrics_res.text
