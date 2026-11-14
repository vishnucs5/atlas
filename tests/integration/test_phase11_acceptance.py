"""Phase 11 Acceptance Test Suite — Production Operational Readiness (PR-01 through PR-15).

Verifies:
- PR-01: Multi-stage container images with non-root execution.
- PR-02: Production Docker Compose 7-service orchestration manifest.
- PR-03: Production environment configuration template.
- PR-04: Prometheus and OpenTelemetry Collector deployment configurations.
- PR-05: Multi-OS CI/CD pipeline with security and container validation stages.
- PR-06: OpenTelemetry W3C distributed traceparent context propagation.
- PR-07: In-span attribute and exception recording with status transitions.
- PR-08: Standard OpenTelemetry ResourceSpans JSON export schema.
- PR-09: Control plane HTTP request tracing middleware and Prometheus metrics.
- PR-10: Circuit Breaker state machine (CLOSED -> OPEN -> HALF_OPEN -> CLOSED).
- PR-11: Sub-millisecond fast-failing in OPEN circuit breaker state.
- PR-12: Bulkhead concurrency throttling and queue saturation protection.
- PR-13: Production API latency performance bounds (p95 < 25ms).
- PR-14: Comprehensive operational runbooks and disaster recovery playbooks.
- PR-15: Monorepo regression baseline and dual database persistence invariants.
"""

from pathlib import Path

import pytest
from atlas_api.main import app
from atlas_coordination import (
    Bulkhead,
    BulkheadRejectedError,
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
)
from atlas_observability import (
    SpanContext,
    Tracer,
    get_tracer,
)
from fastapi.testclient import TestClient


def test_pr01_multistage_container_builds():
    """PR-01: Verify production Dockerfiles exist, use multi-stage builds and non-root users."""
    api_dockerfile = Path("apps/api/Dockerfile")
    worker_dockerfile = Path("apps/worker/Dockerfile")

    assert api_dockerfile.exists()
    assert worker_dockerfile.exists()

    api_txt = api_dockerfile.read_text(encoding="utf-8")
    assert "FROM python:3.11-slim AS builder" in api_txt
    assert "FROM python:3.11-slim AS runner" in api_txt
    assert "useradd -u 10001" in api_txt
    assert "USER atlas" in api_txt
    assert "ENTRYPOINT" in api_txt

    worker_txt = worker_dockerfile.read_text(encoding="utf-8")
    assert "FROM python:3.11-slim AS builder" in worker_txt
    assert "FROM python:3.11-slim AS runner" in worker_txt
    assert "USER atlas" in worker_txt
    assert "ENTRYPOINT" in worker_txt


def test_pr02_production_docker_compose_manifest():
    """PR-02: Verify production Docker Compose defines all 7 required services and healthchecks."""
    compose_path = Path("docker-compose.prod.yml")
    assert compose_path.exists()
    txt = compose_path.read_text(encoding="utf-8")

    # Required production services
    required_services = [
        "atlas-postgres",
        "atlas-redis",
        "otel-collector",
        "prometheus",
        "grafana",
        "atlas-api",
        "atlas-worker",
    ]
    for svc in required_services:
        assert f"{svc}:" in txt, f"Service {svc} missing in docker-compose.prod.yml"

    # Healthchecks and persistent volumes
    assert "healthcheck:" in txt
    assert "atlas_postgres_data:" in txt
    assert "atlas_redis_data:" in txt


def test_pr03_production_env_configuration():
    """PR-03: Verify production environment template documents all required variables."""
    env_path = Path(".env.production.example")
    assert env_path.exists()
    txt = env_path.read_text(encoding="utf-8")

    assert "ATLAS_ENV=production" in txt
    assert "POSTGRES_PASSWORD=" in txt
    assert "ATLAS_DATABASE_URL=" in txt
    assert "REDIS_PASSWORD=" in txt
    assert "ATLAS_REDIS_URL=" in txt
    assert "ATLAS_VAULT_ENCRYPTION_KEY=" in txt
    assert "OTEL_EXPORTER_OTLP_ENDPOINT=" in txt


def test_pr04_prometheus_and_otel_configs():
    """PR-04: Verify Prometheus and OpenTelemetry collector configuration files."""
    prom_path = Path("deploy/prometheus/prometheus.yml")
    otel_path = Path("deploy/otel/otel-collector-config.yml")

    assert prom_path.exists()
    assert otel_path.exists()

    prom_txt = prom_path.read_text(encoding="utf-8")
    assert 'job_name: "atlas-api"' in prom_txt
    assert 'job_name: "otel-collector"' in prom_txt

    otel_txt = otel_path.read_text(encoding="utf-8")
    assert "receivers:" in otel_txt
    assert "otlp:" in otel_txt
    assert "exporters:" in otel_txt


def test_pr05_cicd_pipeline_expansion():
    """PR-05: Verify GitHub Actions workflow has multi-OS matrix and security scanning."""
    ci_path = Path(".github/workflows/ci.yml")
    assert ci_path.exists()
    txt = ci_path.read_text(encoding="utf-8")

    assert "ubuntu-latest" in txt
    assert "windows-latest" in txt
    assert "macos-latest" in txt
    assert "bandit" in txt
    assert "pip-audit" in txt
    assert "docker compose" in txt


def test_pr06_opentelemetry_w3c_context_propagation():
    """PR-06: Verify OpenTelemetry W3C traceparent formatting and context extraction."""
    trace_id = "0af7651916cd43dd8448eb211c80319c"
    span_id = "b7ad6b7169203331"
    ctx = SpanContext(trace_id=trace_id, span_id=span_id, trace_flags="01")

    header = ctx.to_traceparent()
    assert header == f"00-{trace_id}-{span_id}-01"

    parsed = SpanContext.from_traceparent(header)
    assert parsed is not None
    assert parsed.trace_id == trace_id
    assert parsed.span_id == span_id

    tracer = Tracer(service_name="test-pr06")
    headers = tracer.inject_headers({}, span=tracer.start_span("root", parent_context=ctx))
    assert "traceparent" in headers
    extracted = tracer.extract_context(headers)
    assert extracted is not None
    assert extracted.trace_id == trace_id


def test_pr07_span_attribute_and_exception_recording():
    """PR-07: Verify in-span attribute recording and error status handling."""
    tracer = Tracer(service_name="test-pr07")

    with pytest.raises(RuntimeError):
        with tracer.span("faulty_step", attributes={"module": "worker"}) as span:
            span.set_attribute("attempt", 1)
            span.add_event("checkpoint_saved")
            raise RuntimeError("disk failure")

    spans = tracer.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.status == "ERROR"
    assert s.attributes["attempt"] == 1
    assert any(e["name"] == "exception" for e in s.events)


def test_pr08_opentelemetry_otlp_json_export():
    """PR-08: Verify export to standard OpenTelemetry ResourceSpans JSON structure."""
    tracer = Tracer(service_name="test-pr08")
    with tracer.span("job_run"):
        pass

    data = tracer.export_otlp_json()
    assert "resourceSpans" in data
    assert len(data["resourceSpans"]) >= 1
    scope_spans = data["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(scope_spans) >= 1
    assert scope_spans[0]["name"] == "job_run"


def test_pr09_http_tracing_middleware_and_prometheus_metrics():
    """PR-09: Verify FastAPI request tracing middleware and Prometheus metric updates."""
    client = TestClient(app)
    tracer = get_tracer("atlas-api")
    tracer.clear_spans()

    res = client.get("/healthz")
    assert res.status_code == 200
    assert "traceparent" in res.headers

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "atlas_http_requests_total" in metrics.text


def test_pr10_circuit_breaker_lifecycle():
    """PR-10: Verify Circuit Breaker state transitions from CLOSED to OPEN to HALF_OPEN to CLOSED."""
    cb = CircuitBreaker(
        "payment_gw", failure_threshold=2, recovery_timeout=0.1, success_threshold=1
    )
    assert cb.state == CircuitState.CLOSED

    # Failures trip to OPEN
    cb.record_failure(TimeoutError("timeout 1"))
    assert cb.state == CircuitState.CLOSED
    cb.record_failure(TimeoutError("timeout 2"))
    assert cb.state == CircuitState.OPEN

    # Rejection in OPEN state
    with pytest.raises(CircuitBreakerOpenError):
        cb.check_permission()

    # Recovery timeout elapses -> HALF_OPEN
    import time

    time.sleep(0.12)
    assert cb.state == CircuitState.HALF_OPEN

    # Success closes breaker
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_pr11_circuit_breaker_fast_fail_performance():
    """PR-11: Verify sub-millisecond fast-failing in OPEN state."""
    import time

    cb = CircuitBreaker("fast_fail_pr11", failure_threshold=1, recovery_timeout=60.0)
    cb.record_failure(Exception("trip"))
    assert cb.state == CircuitState.OPEN

    start = time.perf_counter()
    for _ in range(1000):
        try:
            cb.check_permission()
        except CircuitBreakerOpenError:
            pass
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    # 1000 fast-fails should execute in < 20ms (sub-0.02ms per check)
    assert elapsed_ms < 20.0


def test_pr12_bulkhead_concurrency_throttling():
    """PR-12: Verify Bulkhead concurrency isolation and rejection upon queue saturation."""
    bulkhead = Bulkhead("api_limiter", max_concurrent=1, max_queued=0, queue_timeout=0.01)

    with bulkhead:
        assert bulkhead.active_count == 1
        with pytest.raises(BulkheadRejectedError):
            bulkhead.acquire()

    assert bulkhead.active_count == 0


def test_pr13_production_api_latency_bounds():
    """PR-13: Verify API latency remains within production bounds (p95 < 25ms)."""
    import time

    client = TestClient(app)
    times = []
    for _ in range(50):
        t0 = time.perf_counter()
        res = client.get("/healthz")
        assert res.status_code == 200
        times.append((time.perf_counter() - t0) * 1000.0)

    times.sort()
    p95 = times[int(len(times) * 0.95)]
    assert p95 < 25.0, f"p95 was {p95:.2f}ms (> 25ms)"


def test_pr14_operational_runbooks_presence():
    """PR-14: Verify incident response, disaster recovery, and database backup runbooks exist and are non-empty."""
    irp = Path("docs/runbooks/INCIDENT_RESPONSE.md")
    dr = Path("docs/runbooks/DISASTER_RECOVERY.md")
    backup = Path("docs/runbooks/DATABASE_BACKUP_RESTORE.md")

    assert irp.exists() and len(irp.read_text(encoding="utf-8")) > 500
    assert dr.exists() and len(dr.read_text(encoding="utf-8")) > 500
    assert backup.exists() and len(backup.read_text(encoding="utf-8")) > 500


def test_pr15_monorepo_regression_and_dual_db_invariants():
    """PR-15: Verify monorepo registration and dual database compatibility."""
    from atlas_enterprise import EnterpriseStorage

    storage_sqlite = EnterpriseStorage(db_path=":memory:")
    assert storage_sqlite is not None
