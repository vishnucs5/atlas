# ATLAS Phase 16.6 — Targeted Hardening & Distributed Execution Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all four critical security and reliability findings identified in the Phase 16.5 independent audit (`FINDING-16.5-01` through `FINDING-16.5-04`), establishing verifiable distributed execution safety under real PostgreSQL concurrency.

**Architecture:**
1. **Approval Consistency**: Delegate approval quorum evaluation and state updates to transactional row-level locked PostgreSQL queries (`SELECT ... FOR UPDATE`), eliminating reliance on process-local caches.
2. **Durable Task Idempotency**: Implement `process_operation_idempotency` in PostgreSQL/SQLite to record operation states (`CREATED`, `IN_PROGRESS`, `SUCCEEDED`, `UNKNOWN_OUTCOME`, `RECONCILIATION_REQUIRED`), preventing blind restart replays of irreversible operations.
3. **Atomic Lease Acquisition**: Transition `acquire_lease()` to an atomic `INSERT ... ON CONFLICT DO UPDATE SET fencing_token = process_worker_leases.fencing_token + 1 RETURNING fencing_token`, guaranteeing strictly monotonic, unique generation tokens across simultaneous workers.
4. **SSRF DNS Rebinding Immunity**: Implement `PinnedResolutionAsyncTransport` in `httpx` to connect directly to validated IP addresses while preserving TLS certificate hostname validation (SNI), eliminating connection-time TOCTOU DNS rebinding.

**Tech Stack:** Python 3.11, PostgreSQL 18.6 (`psycopg`), SQLite 3 (WAL mode), `httpx`, `pytest`, `pytest-asyncio`.

---

## Global Constraints

- Preserve all existing 865 monorepo regression tests, 45 Phase 16 acceptance tests, and 6 PostgreSQL integration tests.
- Base branch: `feat/phase-16-4-critical-remediation` at commit `d1b01b2`.
- Work strictly on branch: `feat/phase-16-6-distributed-safety-hardening`.
- Do not modify `master`.
- AUDIT & HARDENING: Do not introduce unrelated features.
- Zero external dependencies in `packages/atlas-core`.
- Zero compiler/mypy type errors in `packages/atlas-process`.
- 100% compliance with `ruff check` and `ruff format`.

---

## Task Decomposition

### Task 1: Database Migration 018 (Schema & Constraints)
**Files:**
- Create: `migrations/018_task_idempotency_and_lease_atomicity.sql`
- Modify: `packages/atlas-process/src/atlas_process/storage.py` (SQLite schema init)
- Test: `tests/integration/test_phase16_6_postgres_hardening.py`

**Interfaces:**
- Produces: `process_operation_idempotency` table with composite primary key `(tenant_id, idempotency_key)`, request fingerprint hash, status constraints, and foreign key relations.

- [ ] **Step 1: Write failing test for Migration 018 schema creation and table constraints.**
- [ ] **Step 2: Create `migrations/018_task_idempotency_and_lease_atomicity.sql`.**
- [ ] **Step 3: Update SQLite schema in `SqliteProcessStorage._create_tables()`.**
- [ ] **Step 4: Verify migration applies cleanly and idempotently.**

---

### Task 2: P0 — Approval Consistency Across Independent Nodes (`FINDING-16.5-01`)
**Files:**
- Modify: `packages/atlas-process/src/atlas_process/storage.py` (Add `decide_approval()` with `SELECT ... FOR UPDATE`)
- Modify: `packages/atlas-process/src/atlas_process/approvals.py` (`HumanApprovalEngine.decide()` delegates to storage)
- Test: `tests/unit/test_phase16_6_approvals_concurrency.py`
- Test: `tests/integration/test_phase16_6_postgres_hardening.py`

**Interfaces:**
- Consumes: `ApprovalRequest`, `ApprovalDecision`, `ApprovalRecord`
- Produces: `storage.decide_approval(approval_id, approver_id, decision, comments, parameter_hash)` returning atomically resolved `ApprovalRequest`.

- [ ] **Step 1: Write failing unit and multi-process concurrency tests for multi-node approval voting.**
- [ ] **Step 2: Implement `PostgresProcessStorage.decide_approval()` with row-level `FOR UPDATE` lock and atomic quorum calculation.**
- [ ] **Step 3: Implement `SqliteProcessStorage.decide_approval()` with transactional mutex lock.**
- [ ] **Step 4: Update `HumanApprovalEngine.decide()` to delegate directly to authoritative storage.**
- [ ] **Step 5: Run tests and verify the two-node cache probe passes without stalled `PENDING` states.**

---

### Task 3: P0 — Durable Task Idempotency & Irreversible Execution Safety (`FINDING-16.5-02`)
**Files:**
- Create: `packages/atlas-process/src/atlas_process/idempotency.py` (Idempotency manager & state machine)
- Modify: `packages/atlas-process/src/atlas_process/storage.py` (Methods for `process_operation_idempotency`)
- Modify: `packages/atlas-process/src/atlas_process/engine.py` (`recover_after_restart()` and `complete_task()`)
- Modify: `packages/atlas-process/src/atlas_process/transactions.py` (Saga step idempotency binding)
- Test: `tests/unit/test_phase16_6_idempotency.py`
- Test: `tests/integration/test_phase16_6_postgres_hardening.py`

**Interfaces:**
- Produces: `OperationStatus` enum (`CREATED`, `IN_PROGRESS`, `SUCCEEDED`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `UNKNOWN_OUTCOME`, `RECONCILIATION_REQUIRED`, `CANCELLED`).
- Produces: `DurableOperationIdempotencyManager` with `start_operation()`, `complete_operation()`, `fail_operation()`, `mark_unknown_outcome()`.

- [ ] **Step 1: Write failing tests for durable task idempotency, restart recovery prevention, and request fingerprint conflict detection.**
- [ ] **Step 2: Implement `OperationStatus` state machine and `DurableOperationIdempotencyManager`.**
- [ ] **Step 3: Implement PostgreSQL and SQLite storage methods for operation idempotency.**
- [ ] **Step 4: Update `ProcessExecutionEngine.recover_after_restart()` to inspect operation status and mark interrupted non-idempotent tasks `UNKNOWN_OUTCOME` / `RECONCILIATION_REQUIRED` instead of resetting to `READY`.**
- [ ] **Step 5: Verify tests pass across failure injection and simulated crashes.**

---

### Task 4: P1 — Initial Worker Lease Acquisition Race (`FINDING-16.5-03`)
**Files:**
- Modify: `packages/atlas-process/src/atlas_process/storage.py` (`PostgresProcessStorage.acquire_lease()`)
- Modify: `packages/atlas-process/src/atlas_process/storage.py` (`SqliteProcessStorage.acquire_lease()`)
- Test: `tests/unit/test_phase16_6_lease_race.py`
- Test: `tests/integration/test_phase16_6_postgres_hardening.py`

**Interfaces:**
- Consumes: `task_instance_id`, `process_instance_id`, `worker_id`, `lease_duration_seconds`
- Produces: `(lease_token, fencing_token)` where `fencing_token` is guaranteed strictly monotonic and unique per task instance.

- [ ] **Step 1: Write failing test with 10 concurrent workers competing for the initial lease on a brand-new task.**
- [ ] **Step 2: Update `PostgresProcessStorage.acquire_lease()` to use atomic `INSERT ... ON CONFLICT DO UPDATE SET fencing_token = process_worker_leases.fencing_token + 1 RETURNING fencing_token, lease_token`.**
- [ ] **Step 3: Update `SqliteProcessStorage.acquire_lease()` with equivalent atomic monotonic generation.**
- [ ] **Step 4: Verify all concurrent workers receive distinct, monotonically increasing fencing generations (`1, 2, 3, ...`).**

---

### Task 5: P1 — Connection-Time SSRF & DNS Rebinding Protection (`FINDING-16.5-04`)
**Files:**
- Modify: `packages/atlas-process/src/atlas_process/connectors.py` (Add `PinnedResolutionAsyncTransport`)
- Test: `tests/unit/test_phase16_6_dns_rebinding.py`

**Interfaces:**
- Produces: `PinnedResolutionAsyncTransport` ensuring TCP socket connects directly to validated IP addresses while preserving TLS certificate validation for the original hostname.

- [ ] **Step 1: Write failing tests for connection-time DNS rebinding (TTL=0 alternating DNS answers) and TLS SNI preservation.**
- [ ] **Step 2: Implement `PinnedResolutionAsyncTransport` in `connectors.py`.**
- [ ] **Step 3: Configure `AsyncHttpEnterpriseConnector` to use `PinnedResolutionAsyncTransport`.**
- [ ] **Step 4: Verify tests pass with public DNS, blocked private IPs, rebinding attacks, and redirect chains.**

---

### Task 6: Full Monorepo Regression & Documentation Delivery
**Files:**
- Create: Required Phase 16.6 documentation reports (`docs/PHASE_16_6_*.md`).
- Run full regression suite (`pytest`), linting (`ruff`), and typing (`mypy`).

- [ ] **Step 1: Run complete 865+ monorepo test suite.**
- [ ] **Step 2: Run all Phase 16.6 unit and integration test suites.**
- [ ] **Step 3: Author required Phase 16.6 documentation files.**
- [ ] **Step 4: Review `git diff` for secret leaks and commit to branch.**
