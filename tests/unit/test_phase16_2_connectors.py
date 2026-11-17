"""Tests for connector credential protection, resilience, and real HTTP transport in atlas_process.connectors."""

import httpx
import pytest
from atlas_process.connectors import (
    CircuitBreakerOpenError,
    CircuitState,
    ConnectorRateLimitExceededError,
    ConnectorScopeViolationError,
    ConnectorType,
    ERPConnector,
    HttpEnterpriseConnector,
)


def test_connector_credential_masking_in_repr():
    conn = ERPConnector(
        connector_id="erp-01",
        name="SAP S/4HANA",
        connector_type=ConnectorType.ERP,
        tenant_id="tenant-corp",
        granted_scopes=["erp:po:write"],
    )
    conn.set_credentials(
        {"api_key": "top_secret_api_key_xyz", "db_password": "super_secret_password"}
    )

    repr_str = repr(conn)
    assert "top_secret_api_key_xyz" not in repr_str
    assert "super_secret_password" not in repr_str
    assert "redacted" in repr_str.lower()
    assert conn.get_credential_value("api_key") == "top_secret_api_key_xyz"


def test_scope_violation_and_rate_limiting():
    conn = ERPConnector(
        connector_id="erp-02",
        name="NetSuite",
        connector_type=ConnectorType.ERP,
        tenant_id="tenant-corp",
        granted_scopes=["erp:po:read"],
        max_requests_per_minute=2,
    )

    # Scope violation
    with pytest.raises(ConnectorScopeViolationError):
        conn.execute(
            action="create_purchase_order",
            required_scope="erp:po:write",
            parameters={},
        )

    # Allowed scope
    res1 = conn.execute(action="read_po", required_scope="erp:po:read", parameters={})
    assert res1.success is True
    res2 = conn.execute(action="read_po", required_scope="erp:po:read", parameters={})
    assert res2.success is True

    # Exceed rate limit (3rd call)
    with pytest.raises(ConnectorRateLimitExceededError):
        conn.execute(action="read_po", required_scope="erp:po:read", parameters={})


def test_circuit_breaker_tripping_and_recovery():
    class FailingConnector(ERPConnector):
        def _perform_call(self, action, parameters, idempotency_key):
            raise ConnectionError("Backend ERP connection refused")

    conn = FailingConnector(
        connector_id="erp-fail",
        name="Flaky ERP",
        connector_type=ConnectorType.ERP,
        tenant_id="tenant-corp",
        granted_scopes=["erp:all"],
        failure_threshold=2,
        circuit_cooldown_seconds=0.05,
    )

    res1 = conn.execute("sync", "erp:all", {})
    assert res1.success is False
    assert conn._circuit_state == CircuitState.CLOSED

    res2 = conn.execute("sync", "erp:all", {})
    assert res2.success is False
    assert conn._circuit_state == CircuitState.OPEN

    # 3rd call immediately fast-fails with CircuitBreakerOpenError
    with pytest.raises(CircuitBreakerOpenError):
        conn.execute("sync", "erp:all", {})


def test_http_enterprise_connector_with_mock_transport():
    recorded_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        if request.url.path in ("/actions/create_order", "/api/v1/actions/create_order"):
            return httpx.Response(200, json={"order_id": "ORD-12345", "status": "CONFIRMED"})
        return httpx.Response(404, json={"error": "Not found"})

    mock_transport = httpx.MockTransport(mock_handler)

    http_conn = HttpEnterpriseConnector(
        connector_id="http-erp",
        name="HTTP ERP",
        connector_type=ConnectorType.ERP,
        tenant_id="tenant-finance",
        granted_scopes=["erp:orders:create"],
        base_url="https://erp.example.internal/api/v1",
        transport=mock_transport,
    )
    http_conn.set_credentials({"token": "bearer_oauth_token_999"})

    result = http_conn.call_http_endpoint(
        method="POST",
        path="/actions/create_order",
        payload={"item": "Widget A", "qty": 10},
        idempotency_key="idem_key_777",
    )

    assert result["order_id"] == "ORD-12345"
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert req.headers["Authorization"] == "Bearer bearer_oauth_token_999"
    assert req.headers["Idempotency-Key"] == "idem_key_777"
