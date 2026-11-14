# ATLAS Phase 10 Enterprise Risk Register

| Risk ID | Category | Description | Severity | Likelihood | Mitigation Strategy | Status |
|---|---|---|:---:|:---:|---|:---:|
| **ER-01** | Multi-Tenancy | Tenant boundary leakage in shared database pools | Critical | Low | Enforce mandatory tenant predicates on all repository queries; adversarial unit tests. | Open |
| **ER-02** | Security | Rogue agent executes unauthorized enterprise integration | High | Medium | Explicit permission scopes (`integration:invoke`) gated by `ActionFirewall`. | Open |
| **ER-03** | Compliance | Audit log tampering or truncation by privileged insider | High | Low | SHA-256 cryptographic hash-chaining across all audit ledger entries. | Open |
| **ER-04** | Governance | Single-approver compromise bypassing dual custody | High | Medium | State machine requires distinct principal IDs for multi-party approvals. | Open |
| **ER-05** | Financial | Runaway model invocation leading to budget overruns | High | Medium | Hard departmental spending caps with automatic scheduling halts upon breach. | Open |
| **ER-06** | Identity | Expired or revoked sessions remaining active in memory | Medium | Low | Centralized token blacklist checked on every API request. | Open |
| **ER-07** | Integration | Inbound webhook spoofing triggering unauthorized tasks | High | Low | Timing-safe HMAC-SHA256 signature verification on all inbound payloads. | Open |
| **ER-08** | Operations | High latency in third-party integrations stalling DAGs | Medium | High | Configurable timeouts, circuit breakers, and exponential backoff retry policies. | Open |
| **ER-09** | Architecture | Uncontrolled policy inheritance creating security gaps | High | Low | Deterministic inheritance: root organization constraints strictly override local rules. | Open |
| **ER-10** | Usability | Complex enterprise dashboard overwhelming operators | Low | Medium | Streamlined tabbed UI with clear role-based feature gating and diagnostic metrics. | Open |
