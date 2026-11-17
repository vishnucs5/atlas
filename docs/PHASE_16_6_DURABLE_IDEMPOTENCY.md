# Phase 16.6 — Durable Task Idempotency & Irreversible Operation Safety

## 1. Executive Summary

This document details the architectural remediation of **FINDING-16.5-02** (In-Memory Idempotency Cache & Blind Restart Duplicate Execution).

In Phase 16.5, the independent audit discovered that:
- Task idempotency was cached strictly in process memory (`_task_idempotency_cache`).
- When a process engine host crashed during execution of a non-idempotent operation (such as an external bank wire, card charge, or partner ERP update), `recover_after_restart()` observed an expired lease and unconditionally reset the task status from `RUNNING` back to `READY`.
- Upon worker pickup, the task would be executed a second time, resulting in catastrophic double execution of financial and irreversible side effects.

## 2. Root Cause Analysis

1. **Ephemeral Idempotency Cache**: Process-level RAM caches do not survive process restarts or container recycling.
2. **Blind Lease Re-Queueing**: The recovery routine treated all unfinished `RUNNING` tasks identically, failing to distinguish between safe read-only operations and non-idempotent operations with unknown external outcomes.
3. **Missing Operation Fingerprinting**: Reusing an idempotency key with modified arguments was not systematically detected or persisted.

## 3. Implemented Architecture & Remediation

### 3.1 Migration 018: `process_operation_idempotency` Table

Implemented in `migrations/018_task_idempotency_and_lease_atomicity.sql` (PostgreSQL) and `SqliteProcessStorage._create_tables()`:

```sql
CREATE TABLE IF NOT EXISTS process_operation_idempotency (
    tenant_id VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    process_instance_id VARCHAR(64) NOT NULL,
    task_def_id VARCHAR(64) NOT NULL,
    operation_name VARCHAR(128) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'CREATED',
    provider_idempotency_key VARCHAR(128),
    provider_name VARCHAR(64),
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload JSONB,
    error_message TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    completed_at DOUBLE PRECISION,
    expires_at DOUBLE PRECISION,
    PRIMARY KEY (tenant_id, idempotency_key),
    CONSTRAINT fk_operation_idempotency_instance
        FOREIGN KEY (process_instance_id) REFERENCES process_instances(instance_id) ON DELETE CASCADE
);
```

### 3.2 Operation Lifecycle State Machine

Implemented in `packages/atlas-process/src/atlas_process/idempotency.py`:

```
        ┌─────────────┐
        │   CREATED   │
        └──────┬──────┘
               ▼
       ┌───────────────┐
       │  IN_PROGRESS  │
       └───┬───┬───┬───┘
           │   │   └──────────────────────┐
           │   ▼                          ▼
           │ ┌──────────────────┐    ┌─────────────────┐
           │ │ FAILED_RETRYABLE │    │ UNKNOWN_OUTCOME │
           │ └────────┬─────────┘    └────────┬────────┘
           │          │                       │ (Reconcile)
           ▼          ▼ (Retry)               ▼
       ┌───────────┐  │              ┌─────────────────┐
       │ SUCCEEDED │◄─┘              │  RECONCILED /   │
       └───────────┘                 │  FAILED_FINAL   │
                                     └─────────────────┘
```

- `CREATED / IN_PROGRESS`: Atomic reservation in storage. Prevents concurrent workers from launching duplicate executions.
- `SUCCEEDED`: Holds cached `response_payload`. Subsequent calls with identical key and fingerprint return cached response immediately.
- `FAILED_RETRYABLE`: Transient failure (network timeout before dial); permits subsequent retry attempts.
- `FAILED_FINAL`: Business or validation rejection; permanently rejects retry attempts with `OperationPreviouslyFailedError`.
- `UNKNOWN_OUTCOME`: Ambiguous state after host crash or mid-flight disconnect. Requires manual or automated reconciliation before retry.
- `RECONCILIATION_REQUIRED`: Intercepts calls and raises `ReconciliationRequiredError`.

### 3.3 Request Fingerprint Determinism

All payloads are fingerprinted via canonical SHA-256 JSON hashing:
```python
def compute_request_fingerprint(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
```
If an idempotency key is submitted with conflicting payload arguments, `IdempotencyKeyReuseError` is raised immediately.

### 3.4 Crash Recovery Invariant in `ProcessExecutionEngine`

In `packages/atlas-process/src/atlas_process/engine.py` (`recover_after_restart()`):
```python
if hasattr(self._storage, "has_in_progress_operation") and self._storage.has_in_progress_operation(
    instance.tenant_id, instance.instance_id, t_inst.task_def_id
):
    self._storage.mark_task_operations_unknown(
        instance.tenant_id,
        instance.instance_id,
        t_inst.task_def_id,
        reason="Task host crashed with operation in flight; reconciliation required before retry.",
    )
    t_inst.status = ProcessTaskStatus.SUSPENDED
    t_inst.error = (
        "Operation outcome unknown after host crash. Reconciliation required before retry."
    )
    instance.status = ProcessStatus.SUSPENDED
    continue
```
**Critical Guarantee:** An interrupted non-idempotent task is NEVER reset to `READY`. It transitions to `SUSPENDED` until explicitly reconciled.

## 4. Verification Evidence

1. **Unit Test Suite**: `tests/unit/test_phase16_6_idempotency.py` (15/15 passed)
   - Tested deterministic fingerprinting.
   - Tested full success lifecycle with cached response return.
   - Tested rejection of concurrent in-progress duplicate submissions.
   - Tested rejection of conflicting payload key reuse.
   - Tested retryable vs final failure behavior.
   - Tested ambiguous outcome suspension and reconciliation.
   - Tested restart recovery suspension on SQLite and in-memory storage.

2. **PostgreSQL Integration Test**: `tests/integration/test_phase16_6_postgres_hardening.py`
   - `test_pg_16_6_04_durable_idempotency_and_crash_recovery_in_postgres`: PASSED against native PostgreSQL 18.6 with simulated crash and swift reconciliation.
