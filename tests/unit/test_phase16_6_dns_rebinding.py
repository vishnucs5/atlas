"""Unit tests for Phase 16.6 Connection-Time SSRF & DNS Rebinding Protection."""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from atlas_process.connectors import (
    AsyncHttpEnterpriseConnector,
    ConnectorType,
    PinnedResolutionAsyncTransport,
    PinnedResolutionNetworkBackend,
    SSRFSecurityError,
)


@pytest.mark.asyncio
async def test_direct_private_ips_blocked():
    """Verify that private IP targets are blocked before any TCP connection is attempted."""
    backend = PinnedResolutionNetworkBackend()

    private_ips = [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.100",
        "169.254.169.254",
        "::1",
        "fc00::1",
    ]

    for ip in private_ips:
        with pytest.raises(SSRFSecurityError, match="blocked/private range"):
            await backend.connect_tcp(host=ip, port=80)


@pytest.mark.asyncio
async def test_blocked_hostnames():
    """Verify that internal/metadata hostnames are blocked immediately."""
    backend = PinnedResolutionNetworkBackend()

    blocked = [
        "localhost",
        "metadata.google.internal",
        "instance-data",
    ]

    for host in blocked:
        with pytest.raises(SSRFSecurityError, match="blocked"):
            await backend.connect_tcp(host=host, port=80)


@pytest.mark.asyncio
async def test_allowed_hosts_enforcement():
    """Verify that non-whitelisted hosts are blocked when allowed_hosts is configured."""
    backend = PinnedResolutionNetworkBackend(allowed_hosts=["api.example.com"])

    # Disallowed host
    with pytest.raises(SSRFSecurityError, match="not in configured allowed_hosts"):
        await backend.connect_tcp(host="other.example.com", port=443)


@pytest.mark.asyncio
async def test_dns_rebinding_attack_prevented_at_connection_time():
    """FINDING-16.5-04 regression test:
    Simulate a DNS rebinding attack where a malicious domain's DNS returns
    a private IP (e.g., 169.254.169.254 or 127.0.0.1) at socket connect time.
    The PinnedResolutionNetworkBackend must detect this and abort before dialing.
    """
    mock_backend = MagicMock()
    mock_backend.connect_tcp = AsyncMock()
    backend = PinnedResolutionNetworkBackend(backend=mock_backend)

    # Mock getaddrinfo returning AWS/cloud metadata address for malicious-rebind.com
    rebound_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]

    with patch("socket.getaddrinfo", return_value=rebound_addrinfo):
        with pytest.raises(SSRFSecurityError, match="resolves to blocked private/internal IP"):
            await backend.connect_tcp(host="malicious-rebind.com", port=80)

    # Verify underlying TCP connect was NEVER called!
    mock_backend.connect_tcp.assert_not_called()


@pytest.mark.asyncio
async def test_pinned_resolution_dials_validated_ip():
    """Verify that valid public hosts are dialed by their pinned IP to eliminate TOCTOU."""
    mock_backend = MagicMock()
    mock_stream = MagicMock()
    mock_backend.connect_tcp = AsyncMock(return_value=mock_stream)
    backend = PinnedResolutionNetworkBackend(backend=mock_backend)

    public_ip = "93.184.216.34"
    valid_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (public_ip, 443))]

    with patch("socket.getaddrinfo", return_value=valid_addrinfo):
        stream = await backend.connect_tcp(host="example.com", port=443)
        assert stream == mock_stream

    # Must connect to the resolved IP address directly, not the unresolved hostname
    mock_backend.connect_tcp.assert_called_once()
    call_kwargs = mock_backend.connect_tcp.call_args[1]
    assert call_kwargs["host"] == public_ip
    assert call_kwargs["port"] == 443


@pytest.mark.asyncio
async def test_unix_domain_sockets_prohibited():
    """Verify that unix socket connections are unconditionally prohibited."""
    backend = PinnedResolutionNetworkBackend()
    with pytest.raises(SSRFSecurityError, match="Unix domain socket connections are prohibited"):
        await backend.connect_unix_socket(path="/var/run/docker.sock")


@pytest.mark.asyncio
async def test_async_http_enterprise_connector_uses_pinned_transport():
    """Verify that AsyncHttpEnterpriseConnector initializes with PinnedResolutionAsyncTransport."""
    connector = AsyncHttpEnterpriseConnector(
        connector_id="conn_secure_01",
        name="Secure Connector",
        connector_type=ConnectorType.REST_API,
        tenant_id="tenant_sec",
        granted_scopes=["read:api"],
        base_url="https://api.example.com",
        allowed_hosts=["api.example.com"],
        check_dns=False,
    )

    client = connector._create_async_client()
    transport = client._transport

    assert isinstance(transport, PinnedResolutionAsyncTransport)
    await client.aclose()
