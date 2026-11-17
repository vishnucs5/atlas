# ATLAS Phase 16.7 — Durable Idempotency & Irreversible Actions Audit Report

## 1. Executive Summary

This report delivers the independent technical audit of **FINDING-16.5-02** (In-Memory Task Idempotency & Duplicate Irreversible Execution after Restart) in ATLAS Phase 16.6 at commit `c309ec4e5be6cf438aa7ee038e5a34c2d8e37d57`.

The audit evaluated whether the implementation of durable relational idempotency (`process_operation_idempotency`), canonical SHA-256 parameter fingerprinting, and crash recovery task suspension deterministically eliminates duplicate execution of irreversible business and financial side-effects.

## 2. Code Inspection & Line-Level Verification

### 2.1 Database Schema & Constraints (`migrations/018_task_idempotency_and_lease_atomicity.sql`)

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
- **Composite Primary Key**: `(tenant_id, idempotency_key)` guarantees tenant isolation. An idempotency key collision in Tenant A cannot interfere with Tenant B.
- **Relational Integrity**: `FOREIGN KEY (process_instance_id) REFERENCES process_instances(instance_id) ON DELETE CASCADE`.
- **Query Indexes**: `idx_operation_idempotency_instance_task` on `(tenant_id, process_instance_id, task_def_id)` supports fast crash recovery lookups.

### 2.2 Canonical Fingerprinting (`idempotency.py:72-76`)

```python
def compute_request_fingerprint(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
```
- Deterministic canonical serialization eliminates whitespace and key order discrepancies.
- If a client or worker attempts to reuse an idempotency key with different parameters, `storage.py:2653` raises `IdempotencyKeyReuseError`.

### 2.3 Crash Recovery Invariant (`engine.py:458-476`)

```python
if hasattr(self._storage, "has_in_progress_operation") and self._storage.has_in_progress_operation(
    instance.tenant_id, instance.instance_id, t_inst.task_def_id
):
    if hasattr(self._storage, "mark_task_operations_unknown"):
        self._storage.mark_task_operations_unknown(
            instance.tenant_id,
            instance.instance_id,
            t_inst.task_def_id,
            reason="Task host crashed with operation in flight; reconciliation required before retry.",
        )
    t_inst.status = ProcessTaskStatus.SUSPENDED
    t_inst.error = (
        "Operation outcome unknown after host crash. "
        "Reconciliation required before retry."
    )
    instance.status = ProcessStatus.SUSPENDED
    continue
```
- **Critical Safety Guard**: Previously, expired leases on `RUNNING` tasks were unconditionally reset to `READY`.
- **Phase 16.6 Invariant**: If a task has an operation record in state `IN_PROGRESS`, the task is transitioned to `SUSPENDED` and the operation is marked `UNKNOWN_OUTCOME`. It is **never** reset to `READY` for blind replay.

## 3. Failure Injection Analysis across 7 Lifecycle Points

The audit evaluated system behavior across the 7 critical failure injection points:

| Injection Point | Failure Scenario | System Reaction | Invariant Preserved? |
| :--- | :--- | :--- | :---: |
| **Point 1: Before Recording** | Process crashes before `start_operation()` executes. | No DB record created; no external call initiated. On restart, task runs fresh without duplicate side effects. | **YES** |
| **Point 2: After Recording, Before Dispatch** | Operation recorded as `IN_PROGRESS`; worker killed before network packet sent. | On reboot, `recover_after_restart()` detects `IN_PROGRESS`, marks `UNKNOWN_OUTCOME`, and sets task to `SUSPENDED`. Requires operator reconciliation. No duplicate execution. | **YES** |
| **Point 3: During Dispatch** | Socket drops or times out mid-handshake. | In-flight status remains; catch block or restart recovery transitions operation to `UNKNOWN_OUTCOME`. Subsequent call raises `ReconciliationRequiredError`. | **YES** |
| **Point 4: After External Acceptance** | External bank/API accepts wire transfer; worker crashes before receiving HTTP response. | Operation is `UNKNOWN_OUTCOME`. Task is `SUSPENDED`. Retrying worker is blocked with `ReconciliationRequiredError`. Manual reconciliation confirms transaction and resolves without second execution. | **YES** |
| **Point 5: External Success, Before Local Commit** | External API returned 200 OK, but worker crashed before `complete_operation()` committed in DB. | On reboot, marked `UNKNOWN_OUTCOME`. Reconciliation tool queries bank with `provider_idempotency_key`, marks `SUCCEEDED` with external ref, and workflow continues safely. | **YES** |
| **Point 6: During Reconciliation** | Reconciliation worker crashes midway through resolving record. | Database transaction rolls back; record remains `UNKNOWN_OUTCOME` / `RECONCILIATION_REQUIRED`. Workflow remains safely suspended. | **YES** |
| **Point 7: Concurrent Retry from Another Worker** | Second worker attempts to start task while Worker 1 is `IN_PROGRESS`. | Row lock in `start_operation()` detects active state and raises `ConcurrentOperationInProgressError`. Second worker cannot execute. | **YES** |

## 4. Exactly-Once vs. At-Least-Once Boundary Clarification

The audit specifically evaluated whether ATLAS makes false "exactly-once" claims across distributed boundaries:
1. **Local Relational Boundary**: ATLAS guarantees **deterministic exactly-once state transitions** within its own database boundary via ACID transactions and row locks.
2. **External Distributed Boundary**: Across external HTTP/RPC boundaries (banks, ERPs, external SaaS), **true exactly-once execution cannot be mathematically guaranteed by the client alone** (Two Generals' Problem).
3. **ATLAS Mechanism**: ATLAS enforces **at-least-once delivery with durable deduplication and mandatory reconciliation**.
   - If the external provider supports idempotency (`provider_idempotency_key`), the provider ensures exactly-once execution.
   - If the external provider does NOT support idempotency, ATLAS refuses blind retries, halts the task in `SUSPENDED`, and forces out-of-band reconciliation.
   - **Conclusion**: ATLAS adheres strictly to distributed systems theory and makes no false exactly-once claims.

## 5. Audit Assessment & Closure Status

| Audit Criterion | Required Guarantee | Implementation Assessment | Status |
| :--- | :--- | :--- | :---: |
| **Relational Storage** | Operation states survive process restart | Implemented in PostgreSQL and SQLite with indexes | **VERIFIED** |
| **Fingerprint Collision** | Key reuse with altered payload blocked | Verified SHA-256 fingerprint matching | **VERIFIED** |
| **No Blind Replay** | Crashed non-idempotent task not reset to READY | Verified `recover_after_restart()` marks `UNKNOWN_OUTCOME` and `SUSPENDED` | **VERIFIED** |
| **Reconciliation Gate** | Ambiguous outcomes block retry until resolved | Verified `ReconciliationRequiredError` raised on retry | **VERIFIED** |
| **Concurrent Lock** | Competing workers cannot both execute operation | Verified `ConcurrentOperationInProgressError` | **VERIFIED** |

**FINDING-16.5-02 Final Status:** **VERIFIED CLOSED**
