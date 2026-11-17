# ATLAS Phase 16.7 — Security & Architectural Vulnerability Findings

## 1. Executive Summary

This report catalogues all newly discovered and legacy security, architectural, and operational findings evaluated during the Phase 16.7 Independent Audit of commit `c309ec4e5be6cf438aa7ee038e5a34c2d8e37d57`.

---

## 2. Status of Phase 16.5 Mandatory Findings

### FINDING-16.5-01: Multi-Worker Approval In-Memory Cache Divergence
- **Original Severity:** Critical
- **Remediation Invariant:** Approval decisions must be evaluated inside database row locks (`SELECT ... FOR UPDATE`), and `HumanApprovalEngine` must perform cache-through reads from storage.
- **Audit Verification:** Verified in `tests/unit/test_phase16_6_approvals_concurrency.py` and `tests/integration/test_phase16_6_postgres_hardening.py::test_pg_16_6_02`.
- **Verdict:** **VERIFIED CLOSED**

### FINDING-16.5-02: Ephemeral Idempotency & Duplicate Irreversible Execution
- **Original Severity:** Critical
- **Remediation Invariant:** Migration 018 `process_operation_idempotency` table; operation state machine; `recover_after_restart()` marks in-flight tasks `UNKNOWN_OUTCOME` and suspends them rather than resetting to `READY`.
- **Audit Verification:** Verified in `tests/unit/test_phase16_6_idempotency.py` (15/15) and `tests/integration/test_phase16_6_postgres_hardening.py::test_pg_16_6_04`.
- **Verdict:** **VERIFIED CLOSED**

### FINDING-16.5-03: Initial Worker Lease Acquisition Race Condition
- **Original Severity:** Medium
- **Remediation Invariant:** Single-query atomic `INSERT ... ON CONFLICT (task_instance_id) DO UPDATE SET fencing_token = process_worker_leases.fencing_token + 1 RETURNING fencing_token, lease_token`.
- **Audit Verification:** Verified in `tests/unit/test_phase16_6_lease_race.py` (8/8) and `tests/integration/test_phase16_6_postgres_hardening.py::test_pg_16_6_03` (10 concurrent workers on native PostgreSQL).
- **Verdict:** **VERIFIED CLOSED**

### FINDING-16.5-04: Connection-Time SSRF & DNS Rebinding TOCTOU
- **Original Severity:** Medium
- **Remediation Invariant:** `PinnedResolutionNetworkBackend` & `PinnedResolutionAsyncTransport` dial the pre-validated IP address directly at socket creation time, defeating DNS rebinding while preserving TLS SNI and certificate verification.
- **Audit Verification:** Verified in `tests/unit/test_phase16_6_dns_rebinding.py` (7/7).
- **Verdict:** **VERIFIED CLOSED**

---

## 3. Newly Discovered Audit Findings in Phase 16.7

### FINDING-16.7-01: Exception Shadowing & Class Collision on `ReconciliationRequiredError`
- **Severity:** **Medium** (Functional Acceptance Regression)
- **Category:** Architecture / Package Namespace
- **Affected Files:**
  - `packages/atlas-process/src/atlas_process/__init__.py:59`
  - `packages/atlas-process/src/atlas_process/idempotency.py:47`
  - `packages/atlas-process/src/atlas_process/transactions.py:56`
  - `tests/acceptance/test_phase16_acceptance.py:53, 871`
- **Root Cause:**
  Both `atlas_process.idempotency` and `atlas_process.transactions` define an exception named `ReconciliationRequiredError`, but with completely different base classes:
  - `atlas_process.idempotency.ReconciliationRequiredError(IdempotencyError)`
  - `atlas_process.transactions.ReconciliationRequiredError(SagaError)`
  When `packages/atlas-process/src/atlas_process/__init__.py` was modified in Phase 16.6 to resolve duplicate import warnings, the root package exported the `IdempotencyError` subclass. Acceptance scenario `PROC-29` (`test_proc29_unknown_outcome_reconciliation`) imports `ReconciliationRequiredError` from `atlas_process` root and expects `SagaCoordinator.execute_step()` to raise it. Because `SagaCoordinator` raises `atlas_process.transactions.ReconciliationRequiredError` (a `SagaError`), the `pytest.raises` assertion fails, causing an acceptance test regression.
- **Reproduction:**
  ```bash
  uv run pytest tests/acceptance/test_phase16_acceptance.py -k "test_proc29"
  # Output: FAILED tests/acceptance/test_phase16_acceptance.py::test_proc29_unknown_outcome_reconciliation
  ```
- **Operational & Architectural Impact:**
  Callers importing `ReconciliationRequiredError` from `atlas_process` root will fail to catch saga-level timeout and reconciliation exceptions in `except ReconciliationRequiredError:` blocks, causing unhandled exceptions in business workflows.
- **Remediation Recommendation:**
  In `packages/atlas-process/src/atlas_process/transactions.py`, import `ReconciliationRequiredError` directly from `atlas_process.idempotency`, or have `atlas_process.idempotency.ReconciliationRequiredError` inherit from both `IdempotencyError` and `SagaError`, ensuring complete backward and cross-module compatibility.
- **Status:** **OPEN** (Requires mechanical remediation in Phase 16.8 / pre-pilot).

---

### FINDING-16.7-02: Markdown Code Block Formatting in `PHASE_16_6_DURABLE_IDEMPOTENCY.md`
- **Severity:** **Low** (Code Quality / Documentation)
- **Affected File:** `docs/PHASE_16_6_DURABLE_IDEMPOTENCY.md:105`
- **Root Cause:**
  `ruff format --check .` flags a line length formatting difference within a Python code fence inside `docs/PHASE_16_6_DURABLE_IDEMPOTENCY.md`.
- **Reproduction:**
  ```bash
  uv run ruff format --check .
  # Output: 1 file would be reformatted (docs\PHASE_16_6_DURABLE_IDEMPOTENCY.md:105:54)
  ```
- **Remediation Recommendation:**
  Reformat `docs/PHASE_16_6_DURABLE_IDEMPOTENCY.md` using `uv run ruff format .`.
- **Status:** **OPEN**
