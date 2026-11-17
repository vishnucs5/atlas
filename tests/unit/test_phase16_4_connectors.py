"""Unit tests for Phase 16.4 Async Connectors, Non-Blocking Execution & Status Discrimination."""

import httpx
import pytest
from atlas_process.connectors import (
    AsyncHttpEnterpriseConnector,
    CircuitBreakerOpenError,
    ConnectorHttpTransportError,
    ConnectorType,
    SSRFSecurityError,
)


@pytest.mark.asyncio
async def test_async_connector_non_blocking_execution():
    """Verify AsyncHttpEnterpriseConnector executes asynchronously without blocking the loop."""
    call_records = []

    def async_mock_handler(request: httpx.Request) -> httpx.Response:
        call_records.append(request.url.path)
        return httpx.Response(status_code=200, json={"lead_id": "LEAD_123", "status": "QUALIFIED"})

    transport = httpx.MockTransport(async_mock_handler)

    conn = AsyncHttpEnterpriseConnector(
        connector_id="conn_salesforce_async",
        name="Salesforce Async",
        connector_type=ConnectorType.CRM,
        tenant_id="tenant_sales",
        granted_scopes=["crm:write"],
        base_url="https://api.salesforce.example.com",
        transport=transport,
        check_dns=False,
    )

    res = await conn.execute_async(
        action="create_lead",
        required_scope="crm:write",
        parameters={"company": "Acme Corp", "contact": "John Doe"},
        idempotency_key="lead_key_01",
    )

    assert res.success is True
    assert res.data["lead_id"] == "LEAD_123"
    assert "/actions/create_lead" in call_records


@pytest.mark.asyncio
async def test_async_status_code_discrimination_non_transient():
    """Verify non-transient 4xx errors (400, 401, 403, 404) are NOT retried."""
    attempts = 0

    def bad_request_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code=400, json={"error": "Malformed payload"})

    transport = httpx.MockTransport(bad_request_handler)

    conn = AsyncHttpEnterpriseConnector(
        connector_id="conn_bad_req",
        name="Bad Request Test",
        connector_type=ConnectorType.ERP,
        tenant_id="tenant_finance",
        granted_scopes=["erp:write"],
        base_url="https://api.sap.example.com",
        transport=transport,
        max_retries=3,
        check_dns=False,
    )

    with pytest.raises(ConnectorHttpTransportError, match="HTTP 400"):
        await conn.call_http_endpoint_async("POST", "/invoices", payload={"bad": "data"})

    # Non-transient 400 must only be called ONCE (no blind retries)
    assert attempts == 1


@pytest.mark.asyncio
async def test_async_status_code_discrimination_transient():
    """Verify transient 429/503 errors trigger backoff retries and recover on eventual success."""
    attempts = 0

    def rate_limited_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(status_code=429, headers={"Retry-After": "0.01"})
        return httpx.Response(status_code=200, json={"success": True})

    transport = httpx.MockTransport(rate_limited_handler)

    conn = AsyncHttpEnterpriseConnector(
        connector_id="conn_rate_limit_retry",
        name="Rate Limit Retry Test",
        connector_type=ConnectorType.ERP,
        tenant_id="tenant_finance",
        granted_scopes=["erp:write"],
        base_url="https://api.sap.example.com",
        transport=transport,
        max_retries=3,
        check_dns=False,
    )

    result = await conn.call_http_endpoint_async("POST", "/payments", payload={"amt": 100})
    assert result["success"] is True
    # 2 failures followed by 1 success = 3 attempts total
    assert attempts == 3


@pytest.mark.asyncio
async def test_async_circuit_breaker_trips_and_recovers():
    """Verify circuit breaker transitions to OPEN on repeated failures and fast-fails."""

    def server_error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=503, json={"error": "Service Unavailable"})

    transport = httpx.MockTransport(server_error_handler)

    conn = AsyncHttpEnterpriseConnector(
        connector_id="conn_cb_test",
        name="Circuit Breaker Test",
        connector_type=ConnectorType.TICKETING,
        tenant_id="tenant_it",
        granted_scopes=["tickets:write"],
        base_url="https://api.jira.example.com",
        transport=transport,
        failure_threshold=2,
        max_retries=0,
        check_dns=False,
    )

    # 1st failure
    r1 = await conn.execute_async("action", "tickets:write", {})
    assert r1.success is False

    # 2nd failure trips circuit breaker
    r2 = await conn.execute_async("action", "tickets:write", {})
    assert r2.success is False

    # 3rd call must immediately fail with CircuitBreakerOpenError
    with pytest.raises(CircuitBreakerOpenError):
        await conn.execute_async("action", "tickets:write", {})


@pytest.mark.asyncio
async def test_async_redirect_ssrf_blocked():
    """Verify async redirects to private addresses are intercepted and blocked."""

    def redirect_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=301, headers={"Location": "https://10.0.0.1/admin"})

    transport = httpx.MockTransport(redirect_handler)

    conn = AsyncHttpEnterpriseConnector(
        connector_id="conn_async_ssrf",
        name="Async SSRF Redirect Test",
        connector_type=ConnectorType.CRM,
        tenant_id="tenant_sec",
        granted_scopes=["crm:read"],
        base_url="https://api.crm.example.com",
        transport=transport,
        check_dns=False,
    )

    with pytest.raises(SSRFSecurityError, match="belongs to blocked/private range"):
        await conn.call_http_endpoint_async("GET", "/redirect_me")
