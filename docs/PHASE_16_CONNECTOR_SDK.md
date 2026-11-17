# ATLAS Phase 16 Enterprise Connector SDK

Specifies enterprise connector execution contracts, security boundaries, rate limiting, and circuit breakers.

## 1. Connector Capabilities
- **Supported Systems**: ERP, CRM, Procurement, Finance, HR, Ticketing, Email, REST API.
- **Tenant Credential Isolation**: Secure in-memory vault per tenant.
- **Least-Privilege Scoping**: Calls outside granted scopes raise `ConnectorScopeViolationError`.
- **Sliding-Window Rate Limiting**: Enforces max requests per minute.
- **Three-State Circuit Breaker**: `CLOSED`, `OPEN`, `HALF_OPEN`. Consecutive failures trip circuit fast.
