# ATLAS Phase 16.1 — Prioritized Remediation Backlog

**Target Branch:** `feat/phase-16-enterprise-process-execution`  
**Target Commit:** `88d0774`  
**Audit Date:** 2026-11-17  
**Planning Horizon:** Phase 16.2 Enterprise Hardening  

---

## 1. Overview & Prioritization Matrix

This remediation backlog defines the mandatory tasks required to elevate ATLAS Phase 16 from a verified local prototype to a robust, fault-tolerant, secure, and production-ready enterprise execution platform.

Tasks are prioritized according to enterprise risk severity:
- **P0 (Blocker):** Immediate deployment blockers. Must be remediated before any production or multi-tenant pilot.
- **P1 (High):** High-priority security and reliability issues required before general production release.
- **P2 (Medium):** Operational hardening and realism enhancements.
- **P3 (Low):** Performance optimizations and telemetry improvements.

---

## 2. Remediation Backlog Items

### P0 — Immediate Deployment Blockers

| ID | Title & Component | Description & Remediation Requirements | Effort | Invariant |
| :--- | :--- | :--- | :--- | :--- |
| **REM-16.1-01** | **PostgreSQL Persistence Layer**<br>`atlas-process/engine.py`<br>`atlas-storage` | 1. Create SQL migrations in `migrations/` for `process_definitions`, `process_instances`, `checkpoints`, and `approvals`.<br>2. Wire `atlas-storage` drivers into `ProcessExecutionEngine`.<br>3. Ensure true crash recovery by reconstructing state from database WAL and checkpoints on restart. | 16h | AGENTS.md Rule 8 |
| **REM-16.1-02** | **Deterministic Saga Compensation**<br>`atlas-process/transactions.py` | 1. In `compensate_saga`, if `handlers.get(step.name)` is None, set `success = False` and status to `SagaStepStatus.FAILED`.<br>2. Never report phantom compensation success when no rollback logic executed.<br>3. Raise operational reconciliation alert. | 4h | AGENTS.md Rules 5 & 7 |
| **REM-16.1-03** | **API Authentication & RBAC**<br>`atlas-process/api.py` | 1. Inject FastAPI security dependencies (`Depends(get_current_identity)`) on all routes.<br>2. Enforce tenant ownership (`caller.tenant_id == instance.tenant_id`).<br>3. Disallow arbitrary caller injection in `decided_by`. | 8h | AGENTS.md Rule 2 |
| **REM-16.1-04** | **Conditional Branching AST**<br>`atlas-process/engine.py` | 1. Replace placeholder `pass; return True` in `_evaluate_conditions` with a secure AST expression evaluator.<br>2. Evaluate variables against condition expressions (e.g., `amount > 10000`, `status == "APPROVED"`).<br>3. Block branch execution when condition evaluates to false. | 6h | AGENTS.md Rule 4 |

---

### P1 — High Priority (Production Release Criteria)

| ID | Title & Component | Description & Remediation Requirements | Effort | Invariant |
| :--- | :--- | :--- | :--- | :--- |
| **REM-16.1-05** | **Approval Terminal State Lock**<br>`atlas-process/approvals.py` | 1. Reject incoming decisions if `req.status != ApprovalStatus.PENDING`.<br>2. Enforce permanent veto: if rejection threshold is reached, permanently lock request as `REJECTED`.<br>3. Prevent subsequent votes from inverting rejected status to approved. | 4h | AGENTS.md Rule 7 |
| **REM-16.1-06** | **Remove Static Default HMAC Secret**<br>`atlas-process/triggers.py` | 1. Remove `"atlas-process-trigger-secret-v16"` default parameter.<br>2. Require explicit tenant secret retrieval from vault/secrets manager.<br>3. Reject webhook calls if tenant webhook secret is unconfigured. | 4h | AGENTS.md Rule 6 |
| **REM-16.1-07** | **Distributed Leases & Fencing**<br>`atlas-process/engine.py` | 1. Replace single-process `asyncio.Lock()` with PostgreSQL advisory locks or distributed Redis redlocks.<br>2. Increment and verify fencing tokens in database rows on every state transition. | 8h | AGENTS.md Rule 1 |

---

### P2 — Medium Priority (Operational Hardening)

| ID | Title & Component | Description & Remediation Requirements | Effort | Invariant |
| :--- | :--- | :--- | :--- | :--- |
| **REM-16.1-08** | **Encrypted Connector Credentials**<br>`atlas-process/connectors.py` | 1. Store credentials using `SecretStr` and envelope encryption.<br>2. Integrate with `atlas-enterprise` vault to fetch short-lived OAuth2 tokens. | 6h | AGENTS.md Rule 6 |
| **REM-16.1-09** | **Real Connector Transports**<br>`atlas-process/connectors.py` | 1. Replace mock dictionary returns with production `httpx.AsyncClient` transport.<br>2. Configure connection pooling, keep-alives, timeouts, and exponential backoff retry. | 12h | AGENTS.md Rule 4 |
| **REM-16.1-10** | **State Pruning & Retention**<br>`atlas-process/engine.py`<br>`analytics.py` | 1. Implement archival daemon for completed instances.<br>2. Add pagination and date-range filtering for analytics and history lookups. | 6h | AGENTS.md Rule 8 |

---

### P3 — Low Priority (Optimizations & Enhancements)

| ID | Title & Component | Description & Remediation Requirements | Effort | Invariant |
| :--- | :--- | :--- | :--- | :--- |
| **REM-16.1-11** | **Async Crypto Hashing**<br>`atlas-process/approvals.py` | Offload heavy JSON serialization and SHA-256 hashing to `asyncio.to_thread` to prevent event-loop stalls. | 2h | - |
| **REM-16.1-12** | **OpenTelemetry Semantic Spans**<br>`atlas-process/observability.py` | Add OpenTelemetry traces for saga compensation phases and approval escalations. | 4h | AGENTS.md Rule 8 |

---

## 3. Total Remediation Effort Estimate

- **Total P0 Effort:** 34 Engineering Hours
- **Total P1 Effort:** 16 Engineering Hours
- **Total P2 Effort:** 24 Engineering Hours
- **Total P3 Effort:** 6 Engineering Hours
- **Aggregate Remediation Estimate:** 80 Engineering Hours (~2 engineer-weeks)
