# Phase 16.6 — Connection-Time SSRF & DNS Rebinding Protection

## 1. Executive Summary

This document details the architectural remediation of **FINDING-16.5-04** (Connection-Time SSRF & DNS Rebinding TOCTOU).

In Phase 16.5, the independent audit discovered that `SSRFValidator.validate_url()` performed pre-flight DNS validation before HTTP dispatch. However, standard HTTP client engines (`httpx` / `urllib3`) perform their own internal DNS lookup when opening the actual TCP socket. An attacker controlling an authoritative nameserver could serve a public IP during pre-flight validation (TTL = 0) and immediately respond with a private internal IP (`127.0.0.1`, `169.254.169.254`, `10.0.0.1`) during socket connection, bypassing the application firewall.

## 2. Root Cause Analysis

1. **Time-Of-Check to Time-Of-Use (TOCTOU)**: Validating the hostname in Python code before passing the hostname string to the underlying HTTP transport allows a second, unmonitored DNS lookup to occur during TCP dial.
2. **Standard Socket Transport Behavior**: By default, `httpcore` and `httpx` delegate socket connection to `socket.create_connection((host, port))`, which independently queries system DNS.

## 3. Implemented Architecture & Remediation

### 3.1 Socket-Level Destination Pinning (`PinnedResolutionNetworkBackend`)

Implemented in `packages/atlas-process/src/atlas_process/connectors.py`:

```python
class PinnedResolutionNetworkBackend(httpcore.AsyncNetworkBackend):
    """Network backend connecting strictly to validated IP addresses to prevent DNS rebinding TOCTOU."""
```

#### Verification & Pinning Workflow in `connect_tcp`:
1. **Target Normalization**: Cleans and validates input hostname.
2. **Allowlist Enforcement**: If `allowed_hosts` is configured, verifies `clean_host in self.allowed_hosts`.
3. **Direct IP Inspection**: If direct IP, validates that it does not belong to blocked/private/link-local/multicast ranges (`SSRFValidator.is_ip_blocked(direct_ip)`).
4. **Connection-Time DNS Resolution & Validation**:
   - Resolves all A and AAAA records for the target host via `socket.getaddrinfo(clean_host, port)`.
   - Iterates over EVERY resolved IP address:
     ```python
     for resolved_ip in resolved_ips:
         if SSRFValidator.is_ip_blocked(resolved_ip):
             raise SSRFSecurityError(
                 f"SSRF violation: Host '{clean_host}' resolves to blocked private/internal IP {resolved_ip}."
             )
     ```
   - If any IP belongs to RFC 1918, RFC 3927 (link-local/metadata), loopback, or carrier NAT, connection is aborted before dialing.
5. **Direct Dialing of Pinned IP**:
   - The underlying network backend dials `host=pinned_ip` instead of `host=clean_host`:
     ```python
     return await self._backend.connect_tcp(
         host=pinned_ip,
         port=port,
         timeout=timeout,
         local_address=local_address,
         socket_options=socket_options,
     )
     ```
   - This eliminates any subsequent DNS lookup at socket connection time.

### 3.2 TLS SNI & Certificate Integrity Preservation

When establishing HTTPS connections, `httpcore` calls:
```python
stream.start_tls(server_hostname=host)
```
Because `PinnedResolutionNetworkBackend` dials `pinned_ip` at the TCP transport layer, but `httpcore` preserves the original `host` string for the TLS handshake, **TLS Server Name Indication (SNI) and X.509 certificate hostname verification remain fully functional and strictly enforced**.

### 3.3 Seamless Integration in `AsyncHttpEnterpriseConnector`

In `AsyncHttpEnterpriseConnector._create_async_client()`:
```python
transport = self._custom_transport or PinnedResolutionAsyncTransport(
    allowed_hosts=self.allowed_hosts,
    limits=httpx.Limits(
        max_connections=100,
        max_keepalive_connections=20,
        keepalive_expiry=5.0,
    ),
    http1=True,
    http2=False,
    retries=0,
)
```
Every outgoing asynchronous HTTP enterprise request is automatically protected by the pinned resolution transport.

## 4. Verification Evidence

1. **Unit Test Suite**: `tests/unit/test_phase16_6_dns_rebinding.py` (7/7 passed)
   - `test_direct_private_ips_blocked`: Blocked private IPs (127.0.0.1, 10.0.0.5, 172.16.0.1, 192.168.1.100, 169.254.169.254, ::1, fc00::1).
   - `test_blocked_hostnames`: Blocked localhost, metadata.google.internal, instance-data.
   - `test_allowed_hosts_enforcement`: Blocked non-allowlisted domains.
   - `test_dns_rebinding_attack_prevented_at_connection_time`: Simulated DNS rebinding attack where dynamic DNS resolves to AWS/GCP metadata address `169.254.169.254` at connection time; verified underlying socket was NEVER dialed.
   - `test_pinned_resolution_dials_validated_ip`: Verified valid public host connects directly to pinned IP.
   - `test_unix_domain_sockets_prohibited`: Unix domain socket access blocked.
   - `test_async_http_enterprise_connector_uses_pinned_transport`: Verified connector uses `PinnedResolutionAsyncTransport`.
