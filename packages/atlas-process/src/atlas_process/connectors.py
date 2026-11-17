"""ATLAS Enterprise Integration Framework and Connector SDK.

Provides secure connector execution contracts, per-tenant credential isolation using SecretStr,
least-privilege scopes, rate limiting, circuit breakers, real HTTP transport via httpx, and audit logging.
"""

from __future__ import annotations

import asyncio
import ipaddress
import random
import socket
import time
import urllib.parse
import uuid
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, Field, SecretStr


class SecretCredential(SecretStr):
    """Secure credential wrapper that redacts contents in logs/repr while preserving equality checks."""

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.get_secret_value() == other
        return super().__eq__(other)

    def __str__(self) -> str:
        return "**********"


class ConnectorType(StrEnum):
    """Categorization of supported enterprise systems."""

    ERP = "ERP"
    CRM = "CRM"
    PROCUREMENT = "PROCUREMENT"
    FINANCE = "FINANCE"
    HR = "HR"
    TICKETING = "TICKETING"
    EMAIL = "EMAIL"
    REST_API = "REST_API"


class CircuitState(StrEnum):
    """Circuit breaker states protecting enterprise endpoints."""

    CLOSED = "CLOSED"  # Normal operation
    OPEN = "OPEN"  # Tripped, rejecting calls fast
    HALF_OPEN = "HALF_OPEN"  # Testing recovery


class ConnectorError(Exception):
    """Base exception for connector operations."""


class ConnectorScopeViolationError(ConnectorError):
    """Raised when an operation requires permissions outside the connector's granted scopes."""


class ConnectorRateLimitExceededError(ConnectorError):
    """Raised when requests exceed tenant rate limits."""


class CircuitBreakerOpenError(ConnectorError):
    """Raised when calls are blocked by an open circuit breaker."""


class ConnectorHttpTransportError(ConnectorError):
    """Raised when an HTTP transport call fails permanently after bounded retries."""


class SSRFSecurityError(ConnectorError):
    """Raised when an outbound URL violates SSRF security boundaries (private IP, loopback, cloud metadata)."""


class SSRFValidator:
    """Enterprise firewall validating outbound HTTP/HTTPS destinations against SSRF vectors.

    Blocks:
    - IPv4 private networks (RFC 1918): 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
    - IPv4 loopback (127.0.0.0/8)
    - Link-local and cloud metadata endpoints (169.254.0.0/16, metadata.google.internal)
    - IPv6 private (fc00::/7), loopback (::1/128), link-local (fe80::/10), IPv4-mapped IPv6
    - Multicast, broadcast, unspecified addresses
    - Alternate representations (hex, octal, decimal integers)
    - DNS rebinding and redirection to internal subnets
    """

    BLOCKED_IPV4_NETWORKS = [
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("100.64.0.0/10"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.0.0.0/24"),
        ipaddress.ip_network("192.0.2.0/24"),
        ipaddress.ip_network("192.88.99.0/24"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("198.18.0.0/15"),
        ipaddress.ip_network("198.51.100.0/24"),
        ipaddress.ip_network("203.0.113.0/24"),
        ipaddress.ip_network("224.0.0.0/4"),
        ipaddress.ip_network("240.0.0.0/4"),
        ipaddress.ip_network("255.255.255.255/32"),
    ]

    BLOCKED_IPV6_NETWORKS = [
        ipaddress.ip_network("::/128"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("::ffff:0:0/96"),
        ipaddress.ip_network("64:ff9b::/96"),
        ipaddress.ip_network("100::/64"),
        ipaddress.ip_network("2001:db8::/32"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
        ipaddress.ip_network("ff00::/8"),
    ]

    BLOCKED_HOSTNAMES = {
        "localhost",
        "metadata.google.internal",
        "metadata",
        "instance-data",
    }

    @classmethod
    def is_ip_blocked(cls, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        """Check if an IP address belongs to any blocked private/reserved range."""
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
        ):
            return True
        if isinstance(ip, ipaddress.IPv4Address):
            for net in cls.BLOCKED_IPV4_NETWORKS:
                if ip in net:
                    return True
        elif isinstance(ip, ipaddress.IPv6Address):
            if ip.ipv4_mapped:
                return cls.is_ip_blocked(ip.ipv4_mapped)
            for net in cls.BLOCKED_IPV6_NETWORKS:
                if ip in net:
                    return True
        return False

    @classmethod
    def _parse_raw_ip(cls, host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
        """Parse standard, integer, hex, or octal IP representations."""
        # 1. Standard IP
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            pass

        # 2. Integer or Hex direct representation
        try:
            if host.startswith(("0x", "0X")):
                return ipaddress.ip_address(int(host, 16))
            if host.isdigit():
                return ipaddress.ip_address(int(host))
        except (ValueError, OverflowError):
            pass

        # 3. Dotted notation with octal/hex segments (e.g. 0177.0.0.1 or 127.0.0.0x1)
        parts = host.split(".")
        if len(parts) == 4:
            nums: list[int] = []
            for p in parts:
                try:
                    if p.startswith(("0x", "0X")):
                        nums.append(int(p, 16))
                    elif p.startswith("0") and len(p) > 1:
                        nums.append(int(p, 8))
                    else:
                        nums.append(int(p, 10))
                except (ValueError, OverflowError):
                    break
            if len(nums) == 4 and all(0 <= n <= 255 for n in nums):
                try:
                    return ipaddress.IPv4Address(bytes(nums))
                except ValueError:
                    pass

        return None

    @classmethod
    def validate_url(
        cls,
        url: str,
        allow_http: bool = False,
        allowed_hosts: list[str] | None = None,
        check_dns: bool = True,
    ) -> urllib.parse.ParseResult:
        """Validate destination URL against SSRF boundaries and DNS resolution."""
        parsed = urllib.parse.urlparse(url)
        scheme = parsed.scheme.lower()

        # 1. Protocol Scheme Validation
        if scheme not in ("http", "https"):
            raise SSRFSecurityError(
                f"Prohibited URL scheme '{scheme}'. Only HTTPS (or HTTP if enabled) is allowed."
            )
        if scheme == "http" and not allow_http:
            raise SSRFSecurityError(
                "Insecure HTTP scheme is blocked by default. Use HTTPS or explicitly enable allow_http."
            )

        hostname = parsed.hostname
        if not hostname:
            raise SSRFSecurityError(f"Missing hostname in URL: '{url}'")

        clean_host = hostname.lower().strip(".").strip("[]")

        # 2. Blocked Hostnames
        if clean_host in cls.BLOCKED_HOSTNAMES:
            raise SSRFSecurityError(
                f"Target hostname '{clean_host}' is blocked (internal/metadata host)."
            )

        # 3. Host allowlist check (if configured)
        if allowed_hosts and clean_host not in [h.lower() for h in allowed_hosts]:
            raise SSRFSecurityError(
                f"Target host '{clean_host}' is not in the configured allowed_hosts."
            )

        # 4. Direct IP address check (handles integer, octal, hex representations)
        direct_ip = cls._parse_raw_ip(clean_host)
        if direct_ip is not None:
            if cls.is_ip_blocked(direct_ip):
                raise SSRFSecurityError(
                    f"Direct IP address '{direct_ip}' belongs to blocked/private range."
                )
            return parsed

        # 5. DNS Pre-Resolution & Rebinding Protection
        if check_dns:
            try:
                port = parsed.port or (443 if scheme == "https" else 80)
                addr_info = socket.getaddrinfo(clean_host, port)
            except socket.gaierror as exc:
                raise SSRFSecurityError(
                    f"DNS resolution failed for host '{clean_host}': {exc}"
                ) from exc

            resolved_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
            for _, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                try:
                    ip_obj = ipaddress.ip_address(ip_str)
                    resolved_ips.append(ip_obj)
                except ValueError:
                    continue

            if not resolved_ips:
                raise SSRFSecurityError(f"No IP addresses resolved for host '{clean_host}'.")

            for resolved_ip in resolved_ips:
                if cls.is_ip_blocked(resolved_ip):
                    raise SSRFSecurityError(
                        f"SSRF violation: Host '{clean_host}' resolves to blocked private/internal IP {resolved_ip}."
                    )

        return parsed


class ConnectorExecutionResult(BaseModel):
    """Structured, audited outcome of an enterprise integration call."""

    operation_id: str = Field(default_factory=lambda: f"op_{uuid.uuid4().hex[:10]}")
    connector_id: str
    tenant_id: str
    action: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    duration_ms: float = 0.0
    idempotency_key: str | None = None


class BaseEnterpriseConnector:
    """Base contract for enterprise application connectors with security and resilience controls."""

    def __init__(
        self,
        connector_id: str,
        name: str,
        connector_type: ConnectorType,
        tenant_id: str,
        granted_scopes: list[str],
        max_requests_per_minute: int = 60,
        failure_threshold: int = 3,
        circuit_cooldown_seconds: float = 30.0,
    ) -> None:
        self.connector_id = connector_id
        self.name = name
        self.connector_type = connector_type
        self.tenant_id = tenant_id
        self.granted_scopes = set(granted_scopes)
        self.max_requests_per_minute = max_requests_per_minute
        self.failure_threshold = failure_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds

        # Resilience State
        self._circuit_state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._circuit_tripped_at: float = 0.0
        self._request_timestamps: list[float] = []

        # Secure Credential Storage using SecretStr
        self._credentials: dict[str, SecretStr] = {}

    def __repr__(self) -> str:
        masked_keys = list(self._credentials.keys())
        return (
            f"<{self.__class__.__name__} id='{self.connector_id}' "
            f"tenant='{self.tenant_id}' circuit='{self._circuit_state.value}' "
            f"credentials_stored={masked_keys} (values redacted)>"
        )

    def set_credentials(self, credentials: dict[str, str | SecretStr]) -> None:
        """Securely store per-tenant connector credentials as SecretCredential."""
        self._credentials = {
            k: v
            if isinstance(v, SecretCredential)
            else SecretCredential(v.get_secret_value() if isinstance(v, SecretStr) else str(v))
            for k, v in credentials.items()
        }

    def get_credential_value(self, key: str) -> str | None:
        """Retrieve plain secret string strictly at execution time without logging."""
        secret = self._credentials.get(key)
        return secret.get_secret_value() if secret else None

    def _check_rate_limit(self, now: float) -> None:
        """Enforce sliding window rate limit."""
        cutoff = now - 60.0
        self._request_timestamps = [t for t in self._request_timestamps if t > cutoff]
        if len(self._request_timestamps) >= self.max_requests_per_minute:
            raise ConnectorRateLimitExceededError(
                f"Rate limit exceeded on connector '{self.connector_id}': max {self.max_requests_per_minute} req/min."
            )
        self._request_timestamps.append(now)

    def _check_circuit_breaker(self, now: float) -> None:
        """Enforce circuit breaker state machine."""
        if self._circuit_state == CircuitState.OPEN:
            if now - self._circuit_tripped_at > self.circuit_cooldown_seconds:
                self._circuit_state = CircuitState.HALF_OPEN
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN for connector '{self.connector_id}'. Fast-failing."
                )

    def execute(
        self,
        action: str,
        required_scope: str,
        parameters: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> ConnectorExecutionResult:
        """Execute an operation with least-privilege, rate-limiting, and circuit protection."""
        now = time.time()

        # 1. Scope Enforcement Invariant
        if required_scope not in self.granted_scopes:
            raise ConnectorScopeViolationError(
                f"Scope violation: Action '{action}' requires scope '{required_scope}', "
                f"but connector only has {sorted(self.granted_scopes)}."
            )

        # 2. Rate Limit Enforcement
        self._check_rate_limit(now)

        # 3. Circuit Breaker Enforcement
        self._check_circuit_breaker(now)

        start_time = time.time()
        try:
            output = self._perform_call(action, parameters, idempotency_key)
            duration_ms = (time.time() - start_time) * 1000.0

            # Success resets circuit
            self._consecutive_failures = 0
            self._circuit_state = CircuitState.CLOSED

            return ConnectorExecutionResult(
                connector_id=self.connector_id,
                tenant_id=self.tenant_id,
                action=action,
                success=True,
                data=output,
                duration_ms=duration_ms,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000.0
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._circuit_state = CircuitState.OPEN
                self._circuit_tripped_at = time.time()

            # Sanitize error message to ensure no secrets leaked
            err_msg = str(exc)
            for secret in self._credentials.values():
                val = secret.get_secret_value()
                if val and len(val) > 3 and val in err_msg:
                    err_msg = err_msg.replace(val, "[REDACTED]")

            return ConnectorExecutionResult(
                connector_id=self.connector_id,
                tenant_id=self.tenant_id,
                action=action,
                success=False,
                error_message=err_msg,
                duration_ms=duration_ms,
                idempotency_key=idempotency_key,
            )

    async def execute_async(
        self,
        action: str,
        required_scope: str,
        parameters: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> ConnectorExecutionResult:
        """Asynchronously execute an operation with least-privilege, rate-limiting, and circuit protection."""
        now = time.time()

        # 1. Scope Enforcement Invariant
        if required_scope not in self.granted_scopes:
            raise ConnectorScopeViolationError(
                f"Scope violation: Action '{action}' requires scope '{required_scope}', "
                f"but connector only has {sorted(self.granted_scopes)}."
            )

        # 2. Rate Limit Enforcement
        self._check_rate_limit(now)

        # 3. Circuit Breaker Enforcement
        self._check_circuit_breaker(now)

        start_time = time.time()
        try:
            output = await self._perform_call_async(action, parameters, idempotency_key)
            duration_ms = (time.time() - start_time) * 1000.0

            # Success resets circuit
            self._consecutive_failures = 0
            self._circuit_state = CircuitState.CLOSED

            return ConnectorExecutionResult(
                connector_id=self.connector_id,
                tenant_id=self.tenant_id,
                action=action,
                success=True,
                data=output,
                duration_ms=duration_ms,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000.0
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._circuit_state = CircuitState.OPEN
                self._circuit_tripped_at = time.time()

            # Sanitize error message to ensure no secrets leaked
            err_msg = str(exc)
            for secret in self._credentials.values():
                val = secret.get_secret_value()
                if val and len(val) > 3 and val in err_msg:
                    err_msg = err_msg.replace(val, "[REDACTED]")

            return ConnectorExecutionResult(
                connector_id=self.connector_id,
                tenant_id=self.tenant_id,
                action=action,
                success=False,
                error_message=err_msg,
                duration_ms=duration_ms,
                idempotency_key=idempotency_key,
            )

    async def _perform_call_async(
        self,
        action: str,
        parameters: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        """Async implementation of perform call. Defaults to delegating to sync _perform_call in thread."""
        return await asyncio.to_thread(self._perform_call, action, parameters, idempotency_key)

    def _perform_call(
        self,
        action: str,
        parameters: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        """Override in concrete connector subclasses to interact with external API."""
        return {"result": f"Executed {action} successfully"}

    def check_health(self) -> dict[str, Any]:
        """Return connector operational health."""
        return {
            "connector_id": self.connector_id,
            "status": "HEALTHY" if self._circuit_state == CircuitState.CLOSED else "DEGRADED",
            "circuit_state": self._circuit_state.value,
            "consecutive_failures": self._consecutive_failures,
        }


class HttpEnterpriseConnector(BaseEnterpriseConnector):
    """Production-grade HTTP enterprise connector with connection pooling, TLS, retries, backoff, and SSRF firewall."""

    def __init__(
        self,
        connector_id: str,
        name: str,
        connector_type: ConnectorType,
        tenant_id: str,
        granted_scopes: list[str],
        base_url: str = "",
        max_requests_per_minute: int = 60,
        failure_threshold: int = 3,
        circuit_cooldown_seconds: float = 30.0,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        allow_http: bool = False,
        allowed_hosts: list[str] | None = None,
        check_dns: bool = True,
        max_response_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        super().__init__(
            connector_id=connector_id,
            name=name,
            connector_type=connector_type,
            tenant_id=tenant_id,
            granted_scopes=granted_scopes,
            max_requests_per_minute=max_requests_per_minute,
            failure_threshold=failure_threshold,
            circuit_cooldown_seconds=circuit_cooldown_seconds,
        )
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._custom_transport = transport
        self.allow_http = allow_http
        self.allowed_hosts = allowed_hosts
        self.check_dns = check_dns if transport is None else False
        self.max_response_bytes = max_response_bytes

        if self.base_url:
            SSRFValidator.validate_url(
                self.base_url,
                allow_http=self.allow_http,
                allowed_hosts=self.allowed_hosts,
                check_dns=self.check_dns,
            )

    def _create_client(self) -> httpx.Client:
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
        timeout = httpx.Timeout(self.timeout_seconds, connect=5.0)
        return httpx.Client(
            base_url=self.base_url,
            limits=limits,
            timeout=timeout,
            transport=self._custom_transport,
        )

    def call_http_endpoint(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Execute HTTP request with connection pooling, exponential backoff, SSRF validation, and idempotency headers."""
        target_url = f"{self.base_url}/{path.lstrip('/')}" if self.base_url else path
        SSRFValidator.validate_url(
            target_url,
            allow_http=self.allow_http,
            allowed_hosts=self.allowed_hosts,
            check_dns=self.check_dns,
        )

        req_headers = dict(headers or {})
        if idempotency_key:
            req_headers["Idempotency-Key"] = idempotency_key

        api_key = self.get_credential_value("api_key")
        bearer_token = self.get_credential_value("token") or self.get_credential_value(
            "bearer_token"
        )
        if bearer_token:
            req_headers["Authorization"] = f"Bearer {bearer_token}"
        elif api_key:
            req_headers["X-API-Key"] = api_key

        attempt = 0
        last_error: Exception | None = None

        with self._create_client() as client:
            while attempt <= self.max_retries:
                try:
                    current_url = path
                    redirects_followed = 0
                    max_redirects = 5

                    while True:
                        resp = client.request(
                            method=method,
                            url=current_url,
                            json=payload if redirects_followed == 0 else None,
                            headers=req_headers,
                            follow_redirects=False,
                        )

                        if (
                            resp.status_code in (301, 302, 303, 307, 308)
                            and "location" in resp.headers
                        ):
                            redirects_followed += 1
                            if redirects_followed > max_redirects:
                                raise ConnectorHttpTransportError(
                                    f"Too many redirects (max {max_redirects})"
                                )
                            loc = resp.headers["location"]
                            resolved_url = str(resp.url.join(loc))
                            SSRFValidator.validate_url(
                                resolved_url,
                                allow_http=self.allow_http,
                                allowed_hosts=self.allowed_hosts,
                                check_dns=self.check_dns,
                            )
                            current_url = resolved_url
                            continue
                        break

                    content_length = resp.headers.get("Content-Length")
                    if content_length and int(content_length) > self.max_response_bytes:
                        raise ConnectorHttpTransportError(
                            f"Response size {content_length} bytes exceeds limit of {self.max_response_bytes} bytes"
                        )
                    if len(resp.content) > self.max_response_bytes:
                        raise ConnectorHttpTransportError(
                            f"Response content size {len(resp.content)} bytes exceeds limit of {self.max_response_bytes} bytes"
                        )

                    resp.raise_for_status()
                    return resp.json() if resp.content else {}

                except SSRFSecurityError:
                    raise
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in (429, 502, 503, 504):
                        raise ConnectorHttpTransportError(
                            f"HTTP {exc.response.status_code} client/server error calling '{path}': {exc}"
                        ) from exc
                    attempt += 1
                    last_error = exc
                    if attempt > self.max_retries:
                        break
                    backoff = min(0.05 * (2 ** (attempt - 1)) + random.uniform(0.01, 0.05), 1.0)
                    time.sleep(backoff)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    attempt += 1
                    last_error = exc
                    if attempt > self.max_retries:
                        break
                    backoff = min(0.05 * (2 ** (attempt - 1)) + random.uniform(0.01, 0.05), 1.0)
                    time.sleep(backoff)

        raise ConnectorHttpTransportError(
            f"HTTP call to '{path}' failed after {self.max_retries} retries: {last_error}"
        )

    def _perform_call(
        self,
        action: str,
        parameters: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        return self.call_http_endpoint(
            method="POST",
            path=f"/actions/{action}",
            payload=parameters,
            idempotency_key=idempotency_key,
        )


class AsyncHttpEnterpriseConnector(BaseEnterpriseConnector):
    """Production-grade Asynchronous HTTP enterprise connector with connection pooling, TLS, retries, backoff, and SSRF firewall."""

    def __init__(
        self,
        connector_id: str,
        name: str,
        connector_type: ConnectorType,
        tenant_id: str,
        granted_scopes: list[str],
        base_url: str = "",
        max_requests_per_minute: int = 60,
        failure_threshold: int = 3,
        circuit_cooldown_seconds: float = 30.0,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
        allow_http: bool = False,
        allowed_hosts: list[str] | None = None,
        check_dns: bool = True,
        max_response_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        super().__init__(
            connector_id=connector_id,
            name=name,
            connector_type=connector_type,
            tenant_id=tenant_id,
            granted_scopes=granted_scopes,
            max_requests_per_minute=max_requests_per_minute,
            failure_threshold=failure_threshold,
            circuit_cooldown_seconds=circuit_cooldown_seconds,
        )
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._custom_transport = transport
        self.allow_http = allow_http
        self.allowed_hosts = allowed_hosts
        self.check_dns = check_dns if transport is None else False
        self.max_response_bytes = max_response_bytes

        if self.base_url:
            SSRFValidator.validate_url(
                self.base_url,
                allow_http=self.allow_http,
                allowed_hosts=self.allowed_hosts,
                check_dns=self.check_dns,
            )

    def _create_async_client(self) -> httpx.AsyncClient:
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
        timeout = httpx.Timeout(self.timeout_seconds, connect=5.0)
        return httpx.AsyncClient(
            base_url=self.base_url,
            limits=limits,
            timeout=timeout,
            transport=self._custom_transport,
        )

    async def call_http_endpoint_async(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Asynchronously execute HTTP request with non-blocking backoff and SSRF validation."""
        target_url = f"{self.base_url}/{path.lstrip('/')}" if self.base_url else path
        SSRFValidator.validate_url(
            target_url,
            allow_http=self.allow_http,
            allowed_hosts=self.allowed_hosts,
            check_dns=self.check_dns,
        )

        req_headers = dict(headers or {})
        if idempotency_key:
            req_headers["Idempotency-Key"] = idempotency_key

        api_key = self.get_credential_value("api_key")
        bearer_token = self.get_credential_value("token") or self.get_credential_value(
            "bearer_token"
        )
        if bearer_token:
            req_headers["Authorization"] = f"Bearer {bearer_token}"
        elif api_key:
            req_headers["X-API-Key"] = api_key

        attempt = 0
        last_error: Exception | None = None

        async with self._create_async_client() as client:
            while attempt <= self.max_retries:
                try:
                    current_url = path
                    redirects_followed = 0
                    max_redirects = 5

                    while True:
                        resp = await client.request(
                            method=method,
                            url=current_url,
                            json=payload if redirects_followed == 0 else None,
                            headers=req_headers,
                            follow_redirects=False,
                        )

                        if (
                            resp.status_code in (301, 302, 303, 307, 308)
                            and "location" in resp.headers
                        ):
                            redirects_followed += 1
                            if redirects_followed > max_redirects:
                                raise ConnectorHttpTransportError(
                                    f"Too many redirects (max {max_redirects})"
                                )
                            loc = resp.headers["location"]
                            resolved_url = str(resp.url.join(loc))
                            SSRFValidator.validate_url(
                                resolved_url,
                                allow_http=self.allow_http,
                                allowed_hosts=self.allowed_hosts,
                                check_dns=self.check_dns,
                            )
                            current_url = resolved_url
                            continue
                        break

                    content_length = resp.headers.get("Content-Length")
                    if content_length and int(content_length) > self.max_response_bytes:
                        raise ConnectorHttpTransportError(
                            f"Response size {content_length} bytes exceeds limit of {self.max_response_bytes} bytes"
                        )
                    if len(resp.content) > self.max_response_bytes:
                        raise ConnectorHttpTransportError(
                            f"Response content size {len(resp.content)} bytes exceeds limit of {self.max_response_bytes} bytes"
                        )

                    resp.raise_for_status()
                    return resp.json() if resp.content else {}

                except SSRFSecurityError:
                    raise
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in (429, 502, 503, 504):
                        raise ConnectorHttpTransportError(
                            f"HTTP {exc.response.status_code} client/server error calling '{path}': {exc}"
                        ) from exc
                    attempt += 1
                    last_error = exc
                    if attempt > self.max_retries:
                        break
                    backoff = min(0.05 * (2 ** (attempt - 1)) + random.uniform(0.01, 0.05), 1.0)
                    await asyncio.sleep(backoff)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    attempt += 1
                    last_error = exc
                    if attempt > self.max_retries:
                        break
                    backoff = min(0.05 * (2 ** (attempt - 1)) + random.uniform(0.01, 0.05), 1.0)
                    await asyncio.sleep(backoff)

        raise ConnectorHttpTransportError(
            f"HTTP call to '{path}' failed after {self.max_retries} retries: {last_error}"
        )

    async def _perform_call_async(
        self,
        action: str,
        parameters: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        return await self.call_http_endpoint_async(
            method="POST",
            path=f"/actions/{action}",
            payload=parameters,
            idempotency_key=idempotency_key,
        )

    def _perform_call(
        self,
        action: str,
        parameters: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        return asyncio.run(self._perform_call_async(action, parameters, idempotency_key))


class ERPConnector(BaseEnterpriseConnector):
    """Enterprise Resource Planning (SAP / NetSuite) connector with HTTP transport support."""

    def __init__(
        self,
        connector_id: str,
        name: str,
        connector_type: ConnectorType,
        tenant_id: str,
        granted_scopes: list[str],
        base_url: str = "",
        transport: httpx.BaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            connector_id=connector_id,
            name=name,
            connector_type=connector_type,
            tenant_id=tenant_id,
            granted_scopes=granted_scopes,
            **kwargs,
        )
        self.base_url = base_url
        self.transport = transport

    def _perform_call(
        self,
        action: str,
        parameters: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        if self.base_url:
            http_conn = HttpEnterpriseConnector(
                connector_id=self.connector_id,
                name=self.name,
                connector_type=self.connector_type,
                tenant_id=self.tenant_id,
                granted_scopes=list(self.granted_scopes),
                base_url=self.base_url,
                transport=self.transport,
            )
            http_conn._credentials = self._credentials
            return http_conn.call_http_endpoint(
                method="POST",
                path=f"/actions/{action}",
                payload=parameters,
                idempotency_key=idempotency_key,
            )

        # Mock fallback for offline integration testing
        if action == "create_purchase_order":
            return {
                "po_number": f"PO-{int(time.time() * 1000)}",
                "vendor": parameters.get("vendor"),
                "total_usd": parameters.get("total_usd", 0.0),
                "status": "APPROVED_IN_ERP",
            }
        elif action == "get_invoice":
            return {
                "invoice_id": parameters.get("invoice_id"),
                "status": "PAID",
            }
        return super()._perform_call(action, parameters, idempotency_key)


class CRMConnector(BaseEnterpriseConnector):
    """Customer Relationship Management (Salesforce) connector with HTTP transport support."""

    def __init__(
        self,
        connector_id: str,
        name: str,
        connector_type: ConnectorType,
        tenant_id: str,
        granted_scopes: list[str],
        base_url: str = "",
        transport: httpx.BaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            connector_id=connector_id,
            name=name,
            connector_type=connector_type,
            tenant_id=tenant_id,
            granted_scopes=granted_scopes,
            **kwargs,
        )
        self.base_url = base_url
        self.transport = transport

    def _perform_call(
        self,
        action: str,
        parameters: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        if self.base_url:
            http_conn = HttpEnterpriseConnector(
                connector_id=self.connector_id,
                name=self.name,
                connector_type=self.connector_type,
                tenant_id=self.tenant_id,
                granted_scopes=list(self.granted_scopes),
                base_url=self.base_url,
                transport=self.transport,
            )
            http_conn._credentials = self._credentials
            return http_conn.call_http_endpoint(
                method="POST",
                path=f"/actions/{action}",
                payload=parameters,
                idempotency_key=idempotency_key,
            )

        if action == "create_lead":
            return {
                "lead_id": f"LEAD-{uuid.uuid4().hex[:8]}",
                "company": parameters.get("company"),
                "stage": "QUALIFIED",
            }
        return super()._perform_call(action, parameters, idempotency_key)


class TicketingConnector(BaseEnterpriseConnector):
    """IT Service Management & Ticketing (Jira / ServiceNow) connector with HTTP transport support."""

    def __init__(
        self,
        connector_id: str,
        name: str,
        connector_type: ConnectorType,
        tenant_id: str,
        granted_scopes: list[str],
        base_url: str = "",
        transport: httpx.BaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            connector_id=connector_id,
            name=name,
            connector_type=connector_type,
            tenant_id=tenant_id,
            granted_scopes=granted_scopes,
            **kwargs,
        )
        self.base_url = base_url
        self.transport = transport

    def _perform_call(
        self,
        action: str,
        parameters: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        if self.base_url:
            http_conn = HttpEnterpriseConnector(
                connector_id=self.connector_id,
                name=self.name,
                connector_type=self.connector_type,
                tenant_id=self.tenant_id,
                granted_scopes=list(self.granted_scopes),
                base_url=self.base_url,
                transport=self.transport,
            )
            http_conn._credentials = self._credentials
            return http_conn.call_http_endpoint(
                method="POST",
                path=f"/actions/{action}",
                payload=parameters,
                idempotency_key=idempotency_key,
            )

        if action == "create_ticket":
            return {
                "ticket_key": f"OPS-{int(time.time() % 10000)}",
                "title": parameters.get("title"),
                "priority": parameters.get("priority", "HIGH"),
                "status": "OPEN",
            }
        return super()._perform_call(action, parameters, idempotency_key)
