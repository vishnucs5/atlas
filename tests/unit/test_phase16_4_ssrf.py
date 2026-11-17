"""Unit tests for Phase 16.4 SSRF Firewall Guardrails & Transport Hardening."""

import httpx
import pytest
from atlas_process.connectors import (
    ConnectorHttpTransportError,
    ConnectorType,
    HttpEnterpriseConnector,
    SSRFSecurityError,
    SSRFValidator,
)


def test_ssrf_prohibited_schemes():
    """Verify non-HTTP/HTTPS schemes are blocked unconditionally."""
    for bad_url in [
        "ftp://example.com/file.txt",
        "file:///etc/passwd",
        "gopher://example.com",
        "dict://example.com:2628",
        "data:text/plain;base64,SGVsbG8=",
    ]:
        with pytest.raises(SSRFSecurityError, match="Prohibited URL scheme"):
            SSRFValidator.validate_url(bad_url, check_dns=False)


def test_ssrf_http_blocked_by_default():
    """Verify unencrypted HTTP is blocked unless allow_http=True is explicitly set."""
    with pytest.raises(SSRFSecurityError, match="Insecure HTTP scheme is blocked by default"):
        SSRFValidator.validate_url("http://api.external.com/v1", allow_http=False, check_dns=False)

    # Allowed when explicitly enabled
    parsed = SSRFValidator.validate_url(
        "http://api.external.com/v1", allow_http=True, check_dns=False
    )
    assert parsed.scheme == "http"


def test_ssrf_blocked_hostnames_and_metadata():
    """Verify internal and cloud metadata hostnames are blocked."""
    for host in ["localhost", "metadata.google.internal", "metadata", "instance-data"]:
        with pytest.raises(SSRFSecurityError, match="blocked.*internal/metadata"):
            SSRFValidator.validate_url(f"https://{host}/computeMetadata/v1", check_dns=False)


def test_ssrf_direct_private_ipv4():
    """Verify direct RFC 1918, loopback, and link-local IPv4 addresses are blocked."""
    blocked_ips = [
        "127.0.0.1",
        "127.0.0.2",
        "10.0.0.1",
        "10.254.0.1",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.0.1",
        "192.168.1.100",
        "169.254.169.254",  # AWS/GCP/Azure metadata
        "0.0.0.0",
        "255.255.255.255",
    ]
    for ip in blocked_ips:
        with pytest.raises(SSRFSecurityError, match="belongs to blocked/private range"):
            SSRFValidator.validate_url(f"https://{ip}/api", check_dns=False)


def test_ssrf_alternate_ip_encodings():
    """Verify integer, hex, and octal dotted IP representations cannot bypass the firewall."""
    # 2130706433 is integer for 127.0.0.1
    with pytest.raises(SSRFSecurityError, match="belongs to blocked/private range"):
        SSRFValidator.validate_url("https://2130706433/admin", check_dns=False)

    # 0x7f000001 is hex for 127.0.0.1
    with pytest.raises(SSRFSecurityError, match="belongs to blocked/private range"):
        SSRFValidator.validate_url("https://0x7f000001/admin", check_dns=False)

    # 0177.0.0.1 is octal dotted notation for 127.0.0.1
    with pytest.raises(SSRFSecurityError, match="belongs to blocked/private range"):
        SSRFValidator.validate_url("https://0177.0.0.1/admin", check_dns=False)


def test_ssrf_ipv6_loopback_and_mapped():
    """Verify IPv6 loopback, link-local, private, and IPv4-mapped addresses are blocked."""
    blocked_v6 = [
        "::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:10.0.0.1",  # IPv4-mapped private
        "::ffff:169.254.169.254",
        "fe80::1",
        "fc00::1",
        "fd00::1",
    ]
    for ip6 in blocked_v6:
        with pytest.raises(SSRFSecurityError, match="belongs to blocked/private range"):
            SSRFValidator.validate_url(f"https://[{ip6}]/secret", check_dns=False)


def test_ssrf_redirect_validation_blocks_internal_hops():
    """Verify that an external redirect to an internal/metadata address is intercepted and blocked."""

    def redirect_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(
                status_code=302,
                headers={"Location": "https://169.254.169.254/computeMetadata/v1"},
            )
        return httpx.Response(status_code=200, json={"ok": True})

    mock_transport = httpx.MockTransport(redirect_handler)

    conn = HttpEnterpriseConnector(
        connector_id="conn_redirect_test",
        name="Redirect Test Connector",
        connector_type=ConnectorType.ERP,
        tenant_id="tenant_sec",
        granted_scopes=["erp:read"],
        base_url="https://api.external-partner.com",
        transport=mock_transport,
        check_dns=False,
    )

    with pytest.raises(
        SSRFSecurityError,
        match="Direct IP address '169.254.169.254' belongs to blocked/private range",
    ):
        conn.call_http_endpoint("GET", "/start")


def test_response_size_limit_protection():
    """Verify responses exceeding maximum allowed bytes are rejected to prevent OOM."""

    def large_response_handler(request: httpx.Request) -> httpx.Response:
        large_body = b"X" * 2000
        return httpx.Response(
            status_code=200, content=large_body, headers={"Content-Length": "2000"}
        )

    mock_transport = httpx.MockTransport(large_response_handler)

    conn = HttpEnterpriseConnector(
        connector_id="conn_size_test",
        name="Size Limit Connector",
        connector_type=ConnectorType.ERP,
        tenant_id="tenant_sec",
        granted_scopes=["erp:read"],
        base_url="https://api.external-partner.com",
        transport=mock_transport,
        check_dns=False,
        max_response_bytes=1000,  # Max 1000 bytes
    )

    with pytest.raises(ConnectorHttpTransportError, match="exceeds limit"):
        conn.call_http_endpoint("GET", "/data")
