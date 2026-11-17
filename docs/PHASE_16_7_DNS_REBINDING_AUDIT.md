# ATLAS Phase 16.7 — Outbound Connector SSRF & DNS Rebinding Security Audit Report

## 1. Executive Summary

This report delivers the independent technical audit of **FINDING-16.5-04** (Connection-Time SSRF & DNS Rebinding TOCTOU) in ATLAS Phase 16.6 at commit `c309ec4e5be6cf438aa7ee038e5a34c2d8e37d57`.

The audit evaluated whether the implementation of `PinnedResolutionNetworkBackend` and `PinnedResolutionAsyncTransport` in `packages/atlas-process/src/atlas_process/connectors.py` deterministically eliminates connection-time DNS rebinding vulnerabilities and enforces RFC 1918, RFC 3927 (cloud metadata), loopback, and IPv6 private boundaries while strictly preserving TLS Server Name Indication (SNI) and X.509 certificate verification.

## 2. Code Inspection & Line-Level Verification

### 2.1 Transport Hook in `connectors.py:704-771`

```python
class PinnedResolutionNetworkBackend(httpcore.AsyncNetworkBackend):
    """Network backend connecting strictly to validated IP addresses to prevent DNS rebinding TOCTOU."""

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        clean_host = host.lower().strip(".").strip("[]")
        if self.allowed_hosts and clean_host not in self.allowed_hosts:
            raise SSRFSecurityError(
                f"Target host '{clean_host}' is not in configured allowed_hosts."
            )

        direct_ip = SSRFValidator._parse_raw_ip(clean_host)
        if direct_ip is not None:
            if SSRFValidator.is_ip_blocked(direct_ip):
                raise SSRFSecurityError(
                    f"Direct IP address '{direct_ip}' belongs to blocked/private range."
                )
            pinned_ip = str(direct_ip)
        else:
            if clean_host in SSRFValidator.BLOCKED_HOSTNAMES:
                raise SSRFSecurityError(
                    f"Target hostname '{clean_host}' is blocked (internal/metadata host)."
                )
            try:
                addr_info = socket.getaddrinfo(clean_host, port)
            except socket.gaierror as exc:
                raise SSRFSecurityError(
                    f"DNS resolution failed for host '{clean_host}': {exc}"
                ) from exc

            resolved_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
            for _, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                try:
                    resolved_ips.append(ipaddress.ip_address(ip_str))
                except ValueError:
                    continue

            if not resolved_ips:
                raise SSRFSecurityError(f"No IP addresses resolved for host '{clean_host}'.")

            for resolved_ip in resolved_ips:
                if SSRFValidator.is_ip_blocked(resolved_ip):
                    raise SSRFSecurityError(
                        f"SSRF violation: Host '{clean_host}' resolves to blocked private/internal IP {resolved_ip}."
                    )
            pinned_ip = str(resolved_ips[0])

        return await self._backend.connect_tcp(
            host=pinned_ip,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )
```

#### Verification of Security Path:
1. **Pre-Dial Interception**: In standard `httpcore`, `connect_tcp` receives the unresolved hostname (e.g. `api.example.com`).
2. **Connection-Time Resolution**: `socket.getaddrinfo(clean_host, port)` is invoked immediately before opening the socket.
3. **Multi-Answer Inspection**: If the DNS query returns multiple IP records, **every single IP address** in `resolved_ips` is evaluated against `SSRFValidator.is_ip_blocked()`. If even one IP points to a private/reserved/link-local address, the entire connection is aborted.
4. **IP Pinning**: The underlying network backend is called with `host=pinned_ip`. The OS socket API (`connect()`) connects to the IP string directly, ensuring no secondary unmonitored DNS lookup can occur.
5. **Unix Domain Sockets**: Blocked unconditionally in `connect_unix_socket` (`SSRFSecurityError: Unix domain socket connections are prohibited`).

### 2.2 TLS SNI & Certificate Validation Verification

In `httpcore`:
```python
stream = await self._network_backend.connect_tcp(host, port, ...)
if self._ssl_context:
    stream = await stream.start_tls(
        server_hostname=host,
        ssl_context=self._ssl_context,
        timeout=timeout,
    )
```
- Because `PinnedResolutionAsyncTransport` hooks into the `network_backend` layer:
  - TCP layer dials: `pinned_ip` (`93.184.216.34`).
  - TLS layer initializes with: `server_hostname=host` (`api.example.com`).
- **Result**:
  1. The TLS ClientHello extension includes the SNI `api.example.com`.
  2. The server returns its certificate chain for `api.example.com`.
  3. Python's `ssl` module verifies that the certificate Subject Alternative Name (SAN) matches `api.example.com`.
  4. Man-in-the-middle attacks and certificate domain mismatches are completely prevented.

## 3. Threat Modeling & Test Verification

### Threat 1: TTL=0 DNS Rebinding to Cloud Metadata (`169.254.169.254`)
- **Test File**: `tests/unit/test_phase16_6_dns_rebinding.py::test_dns_rebinding_attack_prevented_at_connection_time`
- **Simulation**: Attacker domain returns `169.254.169.254` at socket dial time.
- **Observed Behavior**: Intercepted in `connect_tcp`, raised `SSRFSecurityError: SSRF violation: Host 'malicious-rebind.com' resolves to blocked private/internal IP 169.254.169.254`. The underlying socket was never created.
- **Verdict**: **PASSED**.

### Threat 2: Direct RFC 1918 Private Addresses & Encodings
- **Test File**: `tests/unit/test_phase16_6_dns_rebinding.py::test_direct_private_ips_blocked`
- **Tested Targets**: `127.0.0.1`, `10.0.0.5`, `172.16.0.1`, `192.168.1.100`, `169.254.169.254`, `::1`, `fc00::1`.
- **Observed Behavior**: All blocked before socket initialization.
- **Verdict**: **PASSED**.

### Threat 3: Hostname Allowlist Enforcement
- **Test File**: `tests/unit/test_phase16_6_dns_rebinding.py::test_allowed_hosts_enforcement`
- **Observed Behavior**: Whitelisted `api.example.com` allowed; non-whitelisted `other.example.com` raised `SSRFSecurityError`.
- **Verdict**: **PASSED**.

### Threat 4: Async HTTP Enterprise Connector Integration
- **Test File**: `tests/unit/test_phase16_6_dns_rebinding.py::test_async_http_enterprise_connector_uses_pinned_transport`
- **Observed Behavior**: `AsyncHttpEnterpriseConnector` client transport verified as `PinnedResolutionAsyncTransport`.
- **Verdict**: **PASSED**.

## 4. Audit Assessment & Closure Status

| Audit Criterion | Required Guarantee | Implementation Assessment | Status |
| :--- | :--- | :--- | :---: |
| **Connection-Time Enforcement** | No DNS resolution occurs after validation | Verified socket connect dials pinned IP string | **VERIFIED** |
| **All DNS Records Checked** | Mixed public/private DNS rejected | Loop iterates over all `addr_info` entries | **VERIFIED** |
| **TLS SNI Integrity** | Server certificate verified for domain name | `start_tls(server_hostname=host)` preserved | **VERIFIED** |
| **Cloud Metadata Block** | `169.254.169.254` blocked at TCP dial | Verified link-local check in `is_ip_blocked()` | **VERIFIED** |
| **IPv6 & Encodings** | IPv6 loopback and mapped ranges blocked | Verified `IPv6Address` and `_parse_raw_ip` | **VERIFIED** |

**FINDING-16.5-04 Final Status:** **VERIFIED CLOSED**
