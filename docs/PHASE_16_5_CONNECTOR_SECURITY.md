# ATLAS Phase 16.5 — Connector Security, SSRF & Network Transport Audit

## 1. Executive Summary

This audit evaluated outbound enterprise integration security, SSRF firewall validation, non-blocking asynchronous transport, retry discrimination, and DNS rebinding protections in `SSRFValidator` and `AsyncHttpEnterpriseConnector` (`packages/atlas-process/src/atlas_process/connectors.py`).

Findings `NEW-16.3-06` (SSRF vulnerability in outbound HTTP connectors) and `NEW-16.3-07` (synchronous blocking network transport stalling the event loop) are **GENUINELY REMEDIATED**. Outbound connections now utilize asynchronous non-blocking transport with comprehensive IP, scheme, redirect, and payload size controls.

The audit also analyzed the residual Time-of-Check to Time-of-Use (TOCTOU) DNS rebinding surface.

---

## 2. SSRF Firewall Architecture (`SSRFValidator`)

`SSRFValidator.validate_url()` enforces strict perimeter defense prior to outbound connection establishment:

### 1. Protocol Scheme Enforcement
- **Default**: Only `https://` is permitted.
- `http://` is blocked by default unless `allow_http=True` is explicitly configured.
- Dangerous schemes (`file://`, `gopher://`, `ftp://`, `ldap://`) raise `SSRFSecurityError`.

### 2. Private, Reserved & Cloud Metadata IP Filtering
- **RFC 1918 Private Subnets**: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`.
- **Loopback**: `127.0.0.0/8`, `::1/128`.
- **Cloud Metadata Services**: `169.254.0.0/16`, `metadata.google.internal`, `instance-data`.
- **IPv6 Private & Mapped**: `fc00::/7`, `fe80::/10`, `::ffff:0:0/96` (IPv4-mapped IPv6 ranges unwrapped and evaluated against IPv4 rules).

### 3. Alternative IP Encoding Defense
Attackers often bypass simple regex filters using alternative integer, octal, or hexadecimal IP notations. `_parse_raw_ip()` detects and normalizes:
- **Dword / Integer**: `http://2130706433/` -> Normalized to `127.0.0.1` (BLOCKED).
- **Hexadecimal**: `http://0x7f000001/` or `http://0x7f.0.0.1/` -> Normalized to `127.0.0.1` (BLOCKED).
- **Octal**: `http://0177.0.0.1/` -> Normalized to `127.0.0.1` (BLOCKED).

### 4. Redirect Validation
When following HTTP redirects (301, 302, 303, 307, 308):
- `follow_redirects=False` is set on the HTTP client.
- Each redirect `Location` header is resolved against the original URL and re-submitted to `SSRFValidator.validate_url()`.
- Maximum redirects are capped at 5 to prevent redirect loops and amplification attacks.

---

## 3. Asynchronous Transport & Backoff (`AsyncHttpEnterpriseConnector`)

### 1. Non-Blocking Execution
- Uses `httpx.AsyncClient` with connection pooling (`max_keepalive_connections=20`, `max_connections=100`).
- Replaced synchronous `time.sleep()` with `await asyncio.sleep(backoff)`, ensuring the main event loop is never blocked during retry delays.

### 2. Status Code Discrimination
Only transient infrastructure errors trigger retries:
- **Retryable Statuses**: `429` (Rate Limited), `502` (Bad Gateway), `503` (Service Unavailable), `504` (Gateway Timeout).
- **Non-Retryable Statuses**: `400`, `401`, `403`, `404`, `422`, `500` fail immediately without retry.

### 3. Memory Bomb & Resource Bounds
- Enforces `max_response_bytes` (default 10 MB) via both `Content-Length` header inspection and response content length verification, preventing out-of-memory (OOM) crashes from oversized responses.

---

## 4. Architectural Analysis: DNS Rebinding (TOCTOU Surface)

### Mechanism Analysis
In `AsyncHttpEnterpriseConnector.call_http_endpoint_async()`:
1. `SSRFValidator.validate_url(target_url)` resolves DNS using `socket.getaddrinfo(clean_host, port)`. All resolved IPs are checked against blocked ranges.
2. If validation passes, `resp = await client.request(url=current_url, ...)` is called.
3. `httpx.AsyncClient` issues a **second, independent DNS lookup** when opening the TCP socket connection.

### Threat Scenario
If an external target points to a domain under attacker control (`rebind.attacker.com`) with DNS TTL set to 0 seconds:
- Query 1 (Validation): Returns public IP `93.184.216.34` -> Validation passes.
- Query 2 (Connection): Returns `169.254.169.254` (AWS/GCP metadata) or `10.0.0.1` -> `httpx` connects to internal resource!

### Residual Risk & Deployment Safeguards
1. **Application-Level Mitigation**: For strict host environments, configure `allowed_hosts` allowlisting in connector definitions.
2. **Infrastructure-Level Requirement**: Enterprise deployments must enforce network-layer egress filtering (e.g., Kubernetes `NetworkPolicy`, AWS security groups, or egress HTTP proxies like Envoy/Squid) to block traffic destined for internal subnets and cloud metadata endpoints regardless of DNS resolution.
