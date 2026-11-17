# ATLAS Phase 16.3 Independent Audit: Finding Traceability Matrix

**Audit Target Branch:** `feat/phase-16-2-remediation`  
**Base Commit:** `88d077405dfe8e53eb9708434c594993b9ce96e0`  
**Audit Date:** November 17, 2026  
**Auditor:** ATLAS Independent Audit Team (Phase 16.3)  
**Status:** Complete

---

## 1. Traceability of Original Phase 16.1 Findings

| Finding ID | Title & Description | 16.1 Severity | Phase 16.2 Claim | Phase 16.3 Verified Status | Empirical Defect / Residual Risk |
| :--- | :--- | :---: | :--- | :---: | :--- |
| **REM-16.1-01** | Process State Entirely in Memory | **CRITICAL** | Persistent SQLite & PostgreSQL storage engines | **PARTIALLY REMEDIATED** | `complete_task` crashes on PostgreSQL due to missing column. Sagas & reconciliations are not persisted. |
| **REM-16.1-02** | Saga Compensation Reports False Success | **CRITICAL** | Honest rollback states and reconciliation queue | **PARTIALLY REMEDIATED** | Rollback logic is honest in memory, but `SagaCoordinator` is 100% in-memory; active sagas and reconciliations vanish on crash. |
| **REM-16.1-03** | API Lacks Auth & Tenant Isolation | **HIGH** | JWT/API Key auth and RBAC on all routes | **PARTIALLY REMEDIATED** | Route auth works, but keys/secrets are in-memory globals, no token revocation, no `iss`/`aud` validation. |
| **REM-16.1-04** | Conditional Evaluator Always True Stub | **HIGH** | Safe AST-based expression evaluator | **VERIFIED CLOSED** | Complete AST allowlisting, sandbox escape prevention, and resource limits verified. |
| **REM-16.1-05** | Approval Reversal & Inconsistent State | **HIGH** | Permanent veto, terminal state enforcement | **PARTIALLY REMEDIATED** | Permanent veto works in memory, but PostgreSQL drops all individual decisions on reload; no concurrency locks. |
| **REM-16.1-06** | Static Fallback Webhook HMAC Secret | **MEDIUM** | Strict per-tenant secret resolution | **PARTIALLY REMEDIATED** | Hardcoded secrets removed, but replay attacks succeed due to random `event_id` generation in `verify_webhook`. |
| **REM-16.1-07** | Lack of Distributed Lease Fencing | **CRITICAL** | Monotonic fencing tokens and expiry checks | **PARTIALLY REMEDIATED** | Fencing logic works in SQLite, but crashes on PostgreSQL due to missing `lease_token` column. |
| **REM-16.1-08** | Plaintext Connector Credentials | **MEDIUM** | `SecretCredential` string masking | **PARTIALLY REMEDIATED** | Masked in logs and `repr()`, but stored as unencrypted plaintext in heap memory and database JSON. |
| **REM-16.1-09** | Mock HTTP Connector Transports | **MEDIUM** | Real `HttpEnterpriseConnector` with backoff | **PARTIALLY REMEDIATED** | Uses synchronous `httpx.Client` and `time.sleep` (blocks asyncio loop); SSRF vulnerability; generic HTTP RPC only. |
| **REM-16.1-10** | Unbounded Memory Growth & No Archival | **HIGH** | Keyset pagination and cutoff archival | **PARTIALLY REMEDIATED** | Keyset pagination works, but `archive_completed_instances` cascades into pending manual reconciliation records. |

---

## 2. New Findings Identified in Phase 16.3 Audit

| Finding ID | Severity | Category | Description | Impact |
| :--- | :---: | :--- | :--- | :--- |
| **NEW-16.3-01** | **CRITICAL** | Database Schema | PostgreSQL `process_worker_leases` table lacks `lease_token` column. `verify_lease` crashes with `psycopg.errors.UndefinedColumn`. | Distributed workers cannot complete tasks on PostgreSQL; all workflows crash on completion. |
| **NEW-16.3-02** | **CRITICAL** | Transaction Integrity | `SagaCoordinator` is purely in-memory; `storage.save_saga()` drops steps and is never called by coordinator. | In-flight multi-step transactions and pending reconciliation records are lost on node restart. |
| **NEW-16.3-03** | **HIGH** | Data Persistence | `PostgresProcessStorage.save_approval()` fails to populate `process_approval_decisions`. | Partial quorum decisions are wiped out on server reload, permanently deadlocking approval workflows. |
| **NEW-16.3-04** | **HIGH** | Data Integrity | `process_reconciliation_records` has `ON DELETE CASCADE` from `process_saga_transactions` and `process_instances`. | Routine instance archival permanently deletes pending manual financial reconciliation records. |
| **NEW-16.3-05** | **HIGH** | Security / Replay | `verify_webhook()` generates a random UUID for `event_id` rather than deriving an idempotent hash. | Webhooks can be replayed within 300s window to spawn duplicate workflow instances and duplicate transactions. |
| **NEW-16.3-06** | **MEDIUM** | Concurrency / Perf | `HttpEnterpriseConnector` uses synchronous `httpx.Client` and blocking `time.sleep()`. | Blocks the entire asyncio event loop during network retries, starving concurrent tasks and heartbeats. |
| **NEW-16.3-07** | **MEDIUM** | Security / SSRF | `HttpEnterpriseConnector` lacks IP/hostname allowlisting and private IP/cloud metadata blocking. | Enterprise workflows can be manipulated to probe internal infrastructure or cloud metadata services. |
| **NEW-16.3-08** | **LOW** | Git Hygiene | Branch `feat/phase-16-2-remediation` has 34 uncommitted/untracked files; no Phase 16.2 commit was created. | Release tracking, rollback capability, and CI reproducible builds are compromised. |
| **NEW-16.3-09** | **LOW** | Code Quality | 6 static type errors reported by `mypy` in `evaluator.py` and `storage.py`. | Violates strict typing invariants; indicates incomplete type checking during Phase 16.2 delivery. |

---

## 3. Summary of Status Classifications

- **Original Findings Verified Closed:** 1 / 10 (10%)
- **Original Findings Partially Remediated:** 9 / 10 (90%)
- **Original Findings Open / Unaddressed:** 0 / 10 (0%)
- **Total New Audit Findings:** 9 (2 Critical, 3 High, 2 Medium, 2 Low)
- **Net Production Blockers:** 5 (NEW-16.3-01, NEW-16.3-02, NEW-16.3-03, NEW-16.3-04, NEW-16.3-05)
