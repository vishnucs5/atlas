"""ATLAS Enterprise Integration Framework and Connector SDK.

Provides secure connector execution contracts, per-tenant credential isolation,
least-privilege scopes, rate limiting, circuit breakers, and audit logging.
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


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
        self._credentials: dict[str, str] = {}  # In-memory per-tenant vault

    def set_credentials(self, credentials: dict[str, str]) -> None:
        """Securely store per-tenant connector credentials."""
        self._credentials = dict(credentials)

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
                f"Scope violation: Action '{action}' requires scope '{required_scope}', but connector only has {list(self.granted_scopes)}."
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

            return ConnectorExecutionResult(
                connector_id=self.connector_id,
                tenant_id=self.tenant_id,
                action=action,
                success=False,
                error_message=str(exc),
                duration_ms=duration_ms,
                idempotency_key=idempotency_key,
            )

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


class ERPConnector(BaseEnterpriseConnector):
    """Simulated Enterprise Resource Planning (SAP / NetSuite) connector."""

    def _perform_call(
        self,
        action: str,
        parameters: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
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
    """Simulated Customer Relationship Management (Salesforce) connector."""

    def _perform_call(
        self,
        action: str,
        parameters: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        if action == "create_lead":
            return {
                "lead_id": f"LEAD-{uuid.uuid4().hex[:8]}",
                "company": parameters.get("company"),
                "stage": "QUALIFIED",
            }
        return super()._perform_call(action, parameters, idempotency_key)


class TicketingConnector(BaseEnterpriseConnector):
    """Simulated IT Service Management & Ticketing (Jira / ServiceNow) connector."""

    def _perform_call(
        self,
        action: str,
        parameters: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        if action == "create_ticket":
            return {
                "ticket_key": f"OPS-{int(time.time() % 10000)}",
                "title": parameters.get("title"),
                "priority": parameters.get("priority", "HIGH"),
                "status": "OPEN",
            }
        return super()._perform_call(action, parameters, idempotency_key)
