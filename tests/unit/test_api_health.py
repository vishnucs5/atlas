"""Unit tests for ATLAS FastAPI health and status endpoints."""

import pytest
from atlas_api.main import app, create_app
from atlas_storage.sqlite import SQLiteStorage
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def configure_test_storage():
    """Ensure test app has a cleanly managed in-memory storage engine."""
    storage = SQLiteStorage(":memory:")
    storage.initialize()
    app.state.storage = storage
    try:
        yield storage
    finally:
        try:
            storage.close()
        finally:
            app.state.storage = None


def test_health_endpoint():
    """Verify GET /health returns service status, version, and timestamp."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"
    assert "timestamp" in data


def test_healthz_liveness_endpoint():
    """Verify GET /healthz liveness alias returns 200 healthy."""
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"
    assert "timestamp" in data


def test_v1_status_endpoint():
    """Verify GET /v1/status returns component readiness."""
    client = TestClient(app)
    response = client.get("/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "healthy")
    assert data["version"] == "0.1.0"
    assert "timestamp" in data
    assert "components" in data
    assert data["components"]["api"] == "ok"
    assert data["components"]["storage"] == "ok"


def test_api_v1_status_alias():
    """Verify GET /api/v1/status alias returns identical payload."""
    client = TestClient(app)
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "healthy")
    assert data["version"] == "0.1.0"
    assert data["components"]["api"] == "ok"
    assert data["components"]["storage"] == "ok"


def test_readyz_readiness_endpoint():
    """Verify GET /readyz readiness endpoint returns component readiness."""
    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "healthy")
    assert data["components"]["api"] == "ok"
    assert data["components"]["storage"] == "ok"


def test_v1_status_when_storage_missing():
    """Verify /v1/status reports degraded when app.state.storage is None."""
    test_app = create_app()
    test_app.state.storage = None
    client = TestClient(test_app)

    response = client.get("/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["components"]["api"] == "ok"
    assert data["components"]["storage"] == "error"


def test_readyz_when_storage_missing_returns_503():
    """Verify /readyz returns HTTP 503 when app.state.storage is None."""
    test_app = create_app()
    test_app.state.storage = None
    client = TestClient(test_app)

    response = client.get("/readyz")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["components"]["api"] == "ok"
    assert data["components"]["storage"] == "error"


def test_v1_status_storage_degraded():
    """Verify /v1/status reports degraded when storage check fails."""
    test_app = create_app()
    test_app.state.storage_check = lambda: False
    client = TestClient(test_app)

    response = client.get("/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["components"]["api"] == "ok"
    assert data["components"]["storage"] == "error"


def test_readyz_storage_unhealthy_returns_503():
    """Verify /readyz returns HTTP 503 when storage readiness check fails."""
    test_app = create_app()
    test_app.state.storage_check = lambda: False
    client = TestClient(test_app)

    response = client.get("/readyz")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["components"]["api"] == "ok"
    assert data["components"]["storage"] == "error"


def test_lifespan_lifecycle():
    """Verify lifespan startup and shutdown initializes storage on state."""
    test_app = create_app()
    with TestClient(test_app) as client:
        assert test_app.state.storage is not None
        response = client.get("/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["components"]["storage"] == "ok"
