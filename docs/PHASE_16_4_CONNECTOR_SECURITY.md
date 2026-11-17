# Phase 16.4 — Enterprise Connector Security, SSRF Firewall & Async Transport

## 1. Executive Summary

This document details the architectural remediation of **NEW-16.3-06** (Outbound Connector SSRF Vulnerability) and **NEW-16.3-07** (Async Connectors Blocking Event Loop).

In Phase 16.2, `HttpEnterpriseConnector` used synchronous `httpx.Client` and `time.sleep()`, blocking the async event loop during process engine step executions. Furthermore, connector destinations lacked validation against Server-Side Request Forgery (SSRF), allowing outbound requests to reach cloud metadata endpoints (`169.254.169.254`), loopback addresses (`127.0.0.1`), or private subnets via direct IP representations or HTTP redirects.

## 2. Root Cause Analysis

1. **Absence of SSRF Filtering**: Target URLs were passed directly to HTTP clients without inspecting schemes, hostnames, IP allocations, or DNS resolutions.
2. **Redirect Bypasses**: Standard HTTP clients that follow redirects automatically could be lured from an external URL to internal endpoints.
3. **Blocking I/O in Async Coroutines**: Sync HTTP client and sleep calls forced the async thread to freeze during external retry loops.
4. **Blind Retries on Client Errors**: The retry loop caught general `HTTPStatusError` without discriminating status codes, leading to blind retries on 400 Bad Request, 401 Unauthorized, and 403 Forbidden.

## 3. Implemented Remediation

### 3.1 `SSRFValidator` Firewall
- Enforces strict URL validation before any network connection:
  - **Scheme**: Restricts to `https` (or `http` if explicitly configured). Blocks `file://`, `ftp://`, `gopher://`, `dict://`, `data:`.
  - **Reserved Hostnames**: Blocks `localhost`, `metadata.google.internal`, `metadata`, `instance-data`.
  - **Private & Link-Local IPs**: Blocks RFC 1918 ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.0/8`), link-local metadata (`169.254.0.0/16`), broadcast, multicast.
  - **Alternate Representations**: Parses integer IPs (`2130706433`), hex (`0x7f000001`), and octal dotted quad notation (`0177.0.0.1`).
  - **IPv6 Protection**: Blocks loopback (`::1`), private (`fc00::/7`), link-local (`fe80::/10`), and IPv4-mapped IPv6 addresses (`::ffff:127.0.0.1`).
  - **DNS Rebinding Prevention**: Performs DNS pre-resolution via `socket.getaddrinfo` and verifies every resolved IP address against blocked network boundaries.
  - **Redirect Revalidation**: Intercepts 3xx redirects, computes the resolved location URL, and re-validates the target with `SSRFValidator.validate_url` before following.
  - **Payload Limits**: Rejects responses exceeding `max_response_bytes` (default 10MB) to mitigate denial-of-service memory exhaustion.

### 3.2 Non-Blocking `AsyncHttpEnterpriseConnector`
- Implements `AsyncHttpEnterpriseConnector` using `httpx.AsyncClient` and `await asyncio.sleep(backoff)` with random jitter.
- Provides `execute_async` and `call_http_endpoint_async`.
- `BaseEnterpriseConnector` provides `execute_async` and `_perform_call_async` (delegating to thread pool if synchronous), preventing event loop blocking.

### 3.3 Status Code Discrimination
- Retries are restricted exclusively to transient errors:
  - Status codes `429 Too Many Requests`, `502 Bad Gateway`, `503 Service Unavailable`, `504 Gateway Timeout`.
  - Network timeouts (`httpx.TimeoutException`) and transport errors (`httpx.NetworkError`).
- Non-transient 4xx errors (`400`, `401`, `403`, `404`) and 5xx errors (`500`, `501`) fail immediately without retry.
- Security exceptions (`SSRFSecurityError`, `ConnectorScopeViolationError`) are never retried.

## 4. Verification Evidence

- `tests/unit/test_phase16_4_ssrf.py`: 8/8 passed.
- `tests/unit/test_phase16_4_connectors.py`: 5/5 passed.
