# ATLAS Phase 16.2 — Remediation Plan: Critical Durability & Security Hardening

**Branch:** `feat/phase-16-2-remediation`  
**Base Commit:** `88d077405dfe8e53eb9708434c594993b9ce96e0`  
**Execution Date:** 2026-11-17  
**Objective:** Remediate all confirmed P0, P1, and P2 findings from the Phase 16.1 independent audit to establish durable, authenticated, secure, transactionally honest, and crash-resilient enterprise process execution.

---

## 1. Executive Remediation Strategy

Phase 16.2 is organized into two sequential execution gates with strict verification invariants:

### Gate A: P0 Safety Blockers (Mandatory for any pilot)
1. **REM-16.1-01: Durable PostgreSQL Persistence & Crash Recovery**
   - Provide SQL migrations and durable schema for process definitions, instances, checkpoints, approvals, sagas, and leases.
   - Implement `ProcessStorageProtocol` and `PostgresProcessStorage` with transaction safety and WAL durability.
   - Reconstruct active processes from durable storage on restart in `recover_after_restart()`.
2. **REM-16.1-02: Saga Compensation Integrity**
   - Correct `transactions.py` so missing compensation handlers never report success.
   - Transition to `COMPENSATION_FAILED` / `RECONCILIATION_REQUIRED` and raise structured errors.
3. **REM-16.1-03: API Authentication & Tenant Authorization**
   - Secure all endpoints in `atlas-process/api.py` with FastAPI security dependencies (`Depends(verify_caller_identity)`).
   - Enforce tenant isolation and role permissions (`PermissionAction`).
4. **REM-16.1-04: Safe Conditional Expression Evaluator**
   - Implement `SafeExpressionEvaluator` using Python AST parsing with strict allowlists (no `eval`, `exec`, attribute traversal, or OS access).
   - Integrate with `_evaluate_conditions()` in `engine.py`.

### Gate B: P1/P2 Security, Reliability & Operational Hardening
5. **REM-16.1-05: Approval Terminal-State Enforcement**
   - Enforce immutability on resolved requests (`APPROVED`, `REJECTED`, `EXPIRED`).
   - Prevent state inversion (rejection permanently seals request).
6. **REM-16.1-06: Elimination of Static Default HMAC Secret**
   - Remove `"atlas-process-trigger-secret-v16"` default fallback; require explicitly configured tenant webhook secrets.
7. **REM-16.1-07: Distributed Coordination & Fencing**
   - Implement database row-level / advisory locks and monotonic fencing tokens across worker nodes.
8. **REM-16.1-08: Encrypted Connector Credential Storage**
   - Replace plaintext strings with `SecretStr` / envelope encryption in `connectors.py`.
9. **REM-16.1-09: Real HTTP Connector Transport**
   - Wire `httpx.AsyncClient` with connection pooling, timeouts, exponential backoff, and circuit breakers.
10. **REM-16.1-10: Process Archival & Pagination**
    - Implement paginated instance queries and historical archival retention policies.

---

## 2. Milestone Execution Roadmap

| Milestone | Target Scope | Key Deliverables & Code Changes | Verification Target |
| :--- | :--- | :--- | :--- |
| **M0** | Reproduce & Trace | `scratch/reproduce_findings.py`, `PHASE_16_2_FINDING_TRACEABILITY.md` | 10/10 findings reproduced |
| **M1** | Durable Persistence | `atlas_process/storage.py`, migrations `016_enterprise_process.sql`, `engine.py` integration | State survives restart; crash-recovery tests pass |
| **M2** | Saga Compensation | `atlas_process/transactions.py` state machine overhaul | Missing handler fails deterministically; 10 scenarios pass |
| **M3** | API Security & Auth | `atlas_process/api.py`, `atlas_process/auth.py` | 401/403 on unauthenticated and cross-tenant calls |
| **M4** | Safe Evaluator | `atlas_process/evaluator.py`, `engine.py` | AST validator blocks unsafe code; evaluates logic safely |
| **M5** | Approval Integrity | `atlas_process/approvals.py` | Terminal state locked; rejection irreversible |
| **M6** | Webhook Security | `atlas_process/triggers.py` | Missing secret raises error; constant-time check |
| **M7** | Distributed Leases | `atlas_process/engine.py`, `storage.py` | Fencing tokens increment; stale worker rejected |
| **M8** | Credential Vault | `atlas_process/connectors.py` | `SecretStr` prevents exposure in logs/dumps |
| **M9** | HTTP Transport | `atlas_process/connectors.py` | `httpx.AsyncClient` with mock server integration tests |
| **M10** | Archival & Pagination | `atlas_process/engine.py`, `storage.py` | Bounded memory; paginated search |

---

## 3. Architecture Invariant Compliance

All code written in Phase 16.2 must strictly conform to `AGENTS.md`:
1. **Architecture Ownership:** Core contracts remain owned by `atlas-core`; `atlas-process` consumes core primitives.
2. **Action Firewall:** All process actions must pass through `ActionFirewall` authorization.
3. **Zero-Dependency Core:** `packages/atlas-core` must not import `atlas-process`, PostgreSQL, or OS drivers.
4. **No Placeholders:** All placeholder stubs (e.g. `pass; return True`) are replaced with verified production logic.
5. **No Swallowing Exceptions:** Errors are logged with context and transition to structured failure states.
6. **No Secret Leaks:** No credentials or tokens logged, displayed in errors, or embedded in prompts.
7. **Verification Invariant:** Deterministic post-condition verification required for every state transition.
8. **Durable Continuity:** Document all progress in `docs/PHASE_16_2_*.md`.
