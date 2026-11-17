# ATLAS Release Notes — Version 0.16.8 (Enterprise Process Execution)

**Release Date:** 2026-11-17  
**Build Target:** v0.16.8  
**Stability:** Production-Ready Release Candidate  

---

## Highlights of Version 0.16.8

ATLAS 0.16.8 delivers an autonomous, model-agnostic enterprise process execution engine designed for critical, long-running, and distributed workflows.

### 1. Durable Task Idempotency & Irreversible Action Safety
- Database-backed operation state machine (`CREATED`, `IN_PROGRESS`, `SUCCEEDED`, `FAILED`, `UNKNOWN_OUTCOME`, `RECONCILIATION_REQUIRED`).
- Host crash recovery guarantees: tasks interrupted mid-flight are suspended with ambiguous status and placed in an operator reconciliation queue. Double-execution of irreversible wire transfers, credit charges, and ERP modifications is eliminated.
- Canonical SHA-256 fingerprinting prevents key reuse with conflicting arguments.

### 2. Multi-Worker Concurrency & Distributed Fencing
- Atomic `SELECT ... FOR UPDATE` row locks eliminate stale in-memory voting across application pods.
- Monotonically increasing generation tokens eliminate race conditions during initial task lease acquisition.
- Expired and stale workers are fenced out deterministically.

### 3. Outbound SSRF & DNS Rebinding Immunity
- Direct socket dial-time IP pinning (`PinnedResolutionAsyncTransport`) validates IP addresses before opening sockets.
- Eliminates TOCTOU DNS rebinding attacks while strictly preserving TLS SNI and public certificate verification.

### 4. Canonical Exception Hierarchy
- Unified `ReconciliationRequiredError` inheriting from both `IdempotencyError` and `SagaError`.
- Clean polymorphic exception catching across distributed saga compensations and durable task retries.

---

## Upgrade & Compatibility Guide

- **Database Migrations:** Forward migrations `001` through `018` must be applied prior to starting worker pods.
- **Python Compatibility:** Python 3.11+ required.
- **PostgreSQL Compatibility:** Native PostgreSQL 18.6+ supported with `psycopg` 3.2+. SQLite WAL supported for single-host edge deployments.
