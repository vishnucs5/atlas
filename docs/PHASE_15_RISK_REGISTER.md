# ATLAS Phase 15 Risk Register & Operational Mitigations

---

## Risk Matrix

| Risk ID | Description | Severity | Probability | Mitigation Strategy | Owner |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RSK-FED-01** | Malicious federation participant attempts to bypass local Action Firewall by delegating dangerous tasks. | CRITICAL | LOW | Receiving node independently executes `ActionFirewall.evaluate()`; denied actions are rejected immediately. | Security Lead |
| **RSK-FED-02** | Replayed or duplicated federation messages trigger unintended duplicate financial or system actions. | CRITICAL | MEDIUM | Unique message nonces cached with 60s TTL; idempotency keys enforced on all task handlers. | Protocol Lead |
| **RSK-FED-03** | Compromised remote worker returns fabricated success status without executing work. | HIGH | MEDIUM | Sending installation requires deterministic post-condition verification evidence before completion. | QA Lead |
| **RSK-FED-04** | Remote peer attempts cross-tenant data access across federation boundary. | CRITICAL | LOW | Strict tenant scoping in all message handlers; cross-tenant references raise `CrossTenantViolation`. | Architecture Lead |
| **RSK-FED-05** | Network partition causes split-brain or duplicate retries on external side-effect tasks. | HIGH | MEDIUM | Durable outbox, exponential backoff, and mandatory remote state reconciliation before any retry. | Network Lead |
| **RSK-FED-06** | Compromised credential used to access private capability registries. | HIGH | LOW | Immediate broadcast of signed revocation events to in-memory `RevocationList`. | Identity Lead |
| **RSK-FED-07** | Untrusted remote skill package inherits local system permissions upon installation. | CRITICAL | LOW | Remote packages run in sandboxed containers with zero local permission inheritance (Phase 8 model). | Marketplace Lead |
