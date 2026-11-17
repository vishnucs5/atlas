# ATLAS Phase 16 Risk Register

Tracks identified operational, security, and architectural risks and their mitigations.

| Risk ID | Risk Description | Severity | Mitigation Strategy | Status |
| :--- | :--- | :---: | :--- | :---: |
| **RSK-01** | External side effects during process simulation | HIGH | Simulation engine executes DAG purely against synthetic models with 0 external calls. | MITIGATED |
| **RSK-02** | Agent self-approval on sensitive financial actions | CRITICAL | Separation of duties invariant rejects requests where requestor == approver. | MITIGATED |
| **RSK-03** | Stale worker overwriting completed task | HIGH | Monotonic fencing tokens reject commits with outdated tokens (`StaleWorkerFencingError`). | MITIGATED |
| **RSK-04** | Blind retry of failed payments | CRITICAL | Non-idempotent operations fail-fast into `RECONCILIATION_REQUIRED` queue. | MITIGATED |
| **RSK-05** | Connector credential leakage | HIGH | In-memory per-tenant credential vault; tokens never emitted to logs or telemetry. | MITIGATED |
