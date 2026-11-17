# ATLAS Phase 16.5 — Saga Durability & Crash-Window Boundaries

## 1. Executive Summary

This audit evaluated saga durability, step status synchronization, compensation post-condition verification, and failure recovery across crash-window boundaries in `SagaCoordinator` (`packages/atlas-process/src/atlas_process/transactions.py`).

Finding `NEW-16.3-02` (in-memory sagas with zero database persistence) is **REMEDIATED**. Sagas now synchronize their state, steps, forward results, compensation history, and reconciliation references directly into PostgreSQL tables `process_saga_transactions`, `process_saga_steps`, and `process_reconciliation_records`.

However, the audit identified critical crash-recovery constraints that impact financial and irreversible workflows.

---

## 2. Durability Architecture & Schema Synchronization

In `SagaCoordinator`:
- Every call to `create_saga()`, `execute_step()`, `compensate_saga()`, and `reconcile_saga()` persists state changes to `self.storage.save_saga(saga)`.
- Step state transitions are tracked individually:
  `PENDING` -> `EXECUTING` -> `COMPLETED` | `FAILED` | `RECONCILIATION_REQUIRED` -> `COMPENSATING` -> `COMPENSATED` | `COMPENSATION_FAILED` | `COMPENSATION_UNAVAILABLE`.
- In `PostgresProcessStorage.save_saga()`, each step is inserted or updated in `process_saga_steps` with full JSON-serialized payload, result, compensation history, and execution timestamps.
- In `recover_saga(saga_id)`, the coordinator reconstructs the saga and its complete step execution history from persistent storage.

---

## 3. Analysis of the 7 Crash-Window Failure Boundaries

The audit evaluated behavior across seven potential crash windows during saga execution:

| Crash Window | Execution Point | Database State | Recovery Behavior | Risk Classification |
| :--- | :--- | :--- | :--- | :--- |
| **Window 1** | Prior to external invocation | Step: `EXECUTING` | Remains `EXECUTING`. External action was never invoked. | Low (Safe) |
| **Window 2** | During external HTTP invocation | Step: `EXECUTING` | Action may or may not have reached external service. State is ambiguous. | **HIGH (Ambiguous)** |
| **Window 3** | After external action returns, before DB commit | Step: `EXECUTING` | Action succeeded externally, but database records `EXECUTING`. | **CRITICAL (Desynchronization)** |
| **Window 4** | During forward step failure handling | Step: `FAILED`, Saga: `COMPENSATING` | Saga marked compensating; preceding steps require reverse execution. | Medium (Recoverable) |
| **Window 5** | During compensation execution | Step: `COMPENSATING` | Compensation handler was interrupted mid-flight. | **HIGH (Incomplete Rollback)** |
| **Window 6** | After compensation completes, before DB commit | Step: `COMPENSATING` | External compensation succeeded, but recorded as in-flight. | Medium (Idempotent replay safe) |
| **Window 7** | During manual reconciliation | Status: `PENDING` | Reconciliation record retained; operator must re-resolve. | Low (Auditable) |

---

## 4. Critical Findings for Irreversible & Financial Workflows

### Finding SAGA-16.5-01: In-Flight Saga Ambiguity on Process Crash
In `execute_step()`:
```python
step.status = SagaStepStatus.EXECUTING
self.storage.save_saga(saga) # Step persisted as EXECUTING

try:
    result = action_fn(step.forward_payload)
    step.status = SagaStepStatus.COMPLETED
    step.forward_result = result
    self.storage.save_saga(saga)
...
```
If a crash occurs during Windows 2 or 3, the database contains `status = EXECUTING`.
1. `SagaCoordinator` does **not** have an automated background sweeper to detect abandoned in-flight sagas. An interrupted saga remains in `EXECUTING` status indefinitely until an operator inspects it or calls `recover_saga()`.
2. When recovered, the system cannot distinguish whether `action_fn` completed or never executed.
3. If `step.is_idempotent` is `False` (e.g., initiating an external wire transfer), blind retry could cause a duplicate external transaction.

### Finding SAGA-16.5-02: Non-Saga Task Restart Replay Hazard
In `ProcessExecutionEngine.recover_after_restart()`:
```python
if t_inst.status == ProcessTaskStatus.RUNNING:
    if not t_inst.lease_expires_at or t_inst.lease_expires_at < now:
        t_inst.status = ProcessTaskStatus.READY
        t_inst.lease_token = None
        t_inst.lease_expires_at = None
        t_inst.assigned_to = None
        recovered_count += 1
```
For standard workflow tasks executed outside `SagaCoordinator`:
1. Any task found in `RUNNING` status whose lease has expired is automatically reset to `READY`.
2. Any available worker will pick up this `READY` task and execute it again.
3. The engine's idempotency deduplication cache (`self._task_idempotency_cache`) is held strictly **in RAM** (`dict[str, dict[str, Any]]`) and is lost on restart!
4. Consequently, if an automated process task was executing an irreversible non-idempotent operation when the host crashed, restarting the engine **will re-execute the task from scratch**, leading to duplicate external side effects.

### Impact on Production Readiness
Because of `SAGA-16.5-01` and `SAGA-16.5-02`, ATLAS Phase 16 is **NOT READY** for Scope E (financial or irreversible business workflows) without two-phase commit or transactional outbox guarantees.
