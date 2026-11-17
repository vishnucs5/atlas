# ATLAS Phase 16.3 Independent Audit: Distributed Concurrency & Fencing Report

**Audit Target Branch:** `feat/phase-16-2-remediation`  
**Base Commit:** `88d077405dfe8e53eb9708434c594993b9ce96e0`  
**Target Module:** `packages/atlas-process/src/atlas_process/storage.py`, `engine.py`, `approvals.py`  
**Audit Date:** November 17, 2026  
**Auditor:** ATLAS Independent Audit Team (Phase 16.3)  
**Status:** SQLite Functional; PostgreSQL Broken (Finding REM-16.1-07 Partially Remediated)

---

## 1. Executive Summary

Phase 16.1 identified the absence of distributed worker lease fencing, making ATLAS vulnerable to split-brain execution, zombie worker overwrites, and state corruption in multi-node clusters. Phase 16.2 introduced monotonic fencing tokens and lease timeouts in `WorkerLease` and `ProcessStorage`.

While the algorithmic fencing protocol was successfully verified on SQLite, independent empirical testing against native PostgreSQL 18.6 revealed that **distributed fencing on PostgreSQL is broken in production**. Due to a database schema mismatch (`lease_token` column missing), workers cannot verify leases or complete tasks, causing all distributed workflows to fail during task completion.

---

## 2. Distributed Fencing Architecture

The ATLAS process engine implements Martin Kleppmann's fencing token protocol for distributed task execution:
1. **Lease Acquisition:** When Worker A claims Task $T$, the storage engine generates an incrementing `fencing_token` (e.g., $Token = 1$) with an `expires_at` timestamp.
2. **Zombie Detection & Reassignment:** If Worker A stalls (network partition, GC pause), the lease expires. The coordinator reassigns Task $T$ to Worker B with an incremented fencing token ($Token = 2$).
3. **Commit Barrier:** When Worker A recovers and attempts to commit state using $Token = 1$, the storage engine rejects the write because $1 < 2$.

---

## 3. Empirical Concurrency & Fencing Test Results

### 3.1 SQLite Implementation (Verified Functional)
- **Monotonicity:** In `test_sqlite_fencing_token_monotonicity`, successive leases on the same task increment the fencing token monotonically ($1 \to 2 \to 3$).
- **Stale Write Rejection:** When a stale worker attempts to complete a task using an expired lease token or an outdated fencing token, `complete_task()` rejects the operation with `StaleLeaseError`.
- **Status on SQLite:** PASSED.

### 3.2 PostgreSQL Implementation (Broken in Production)
- **Empirical Test:** Tested in `scratch/test_postgres_14_experiments.py` against active PostgreSQL 18.6:
  1. Worker 1 acquired lease on Task 1 (`fencing_token=1`). Lease acquired successfully.
  2. Worker 1 completed task and called `complete_task()`.
  3. **FATAL CRASH:**
     ```text
     psycopg.errors.UndefinedColumn: column "lease_token" does not exist
     LINE 1: SELECT lease_token, fencing_token, expires_at FROM process_worker_leases WHERE task_id = %s
     ```
- **Root Cause (NEW-16.3-01):**
  - Schema `migrations/016_enterprise_process.sql` defined column `lease_id`, but omitted `lease_token`.
  - In `PostgresProcessStorage.record_lease()`, `token = str(uuid.uuid4())` was generated in Python memory but never written to PostgreSQL.
  - In `PostgresProcessStorage.verify_lease()`, the SQL query attempted to read `lease_token`, failing immediately.
- **Status on PostgreSQL:** FAILED (Production Blocker).

---

## 4. Race Conditions in Multi-Party Approvals

### 4.1 Missing Concurrency Locks
In `packages/atlas-process/src/atlas_process/approvals.py`:
- `HumanApprovalEngine.submit_decision()` performs an in-place update of `ApprovalRequest.decisions` and updates the request status.
- The engine has no `asyncio.Lock` or `threading.Lock`.
- In a multi-worker API deployment where two managers submit approval decisions simultaneously (e.g., within milliseconds of each other):
  1. Worker 1 reads approval request from storage (decisions: 0).
  2. Worker 2 reads approval request from storage (decisions: 0).
  3. Worker 1 appends Decision 1 and writes back to storage.
  4. Worker 2 appends Decision 2 and writes back to storage (overwriting Decision 1).
- **Impact:** Lost updates in approval quorum decisions.

### 4.2 Decision Loss on Process Restart (NEW-16.3-03)
Even without race conditions, `PostgresProcessStorage.save_approval()` fails to write individual decisions to `process_approval_decisions`. Upon server reload, all previously recorded votes are wiped out, reverting the request to zero recorded decisions.

---

## 5. Webhook Replay & Duplicate Workflow Concurrency (NEW-16.3-05)

### 5.1 Replay Window Vulnerability
In `packages/atlas-process/src/atlas_process/triggers.py`:
```python
def verify_webhook(self, payload: bytes, signature: str, timestamp_str: str) -> ProcessEvent:
    ...
    # Validates HMAC signature and timestamp within 300s window
    ...
    return ProcessEvent(
        event_id=str(uuid.uuid4()), # Generates a NEW random UUID on every invocation!
        ...
    )
```

### 5.2 Exploit Scenario
1. An attacker intercepts a legitimate, signed webhook request sent to ATLAS.
2. The attacker replays the exact same payload, signature, and timestamp 50 times within the 300-second acceptance window.
3. Because `verify_webhook` creates a fresh `event_id` (random UUID) each time, the deduplication cache in `ingest_event(event.event_id)` fails to identify the replay.
4. **Impact:** ATLAS spawns 50 duplicate workflow instances for a single business event, executing redundant financial orders or customer shipments concurrently.

---

## 6. Distributed Concurrency Verdict

| Concurrency Vector | SQLite Status | PostgreSQL Status | Production Risk |
| :--- | :---: | :---: | :---: |
| **Worker Lease Acquisition** | PASS | PASS | Low |
| **Fencing Token Monotonicity** | PASS | PASS | Low |
| **Lease Verification & Completion** | PASS | **CRASH (`UndefinedColumn`)** | **CRITICAL** |
| **Zombie Worker Rejection** | PASS | UNTESTABLE (Crashes before check) | **CRITICAL** |
| **Approval Quorum Concurrency** | WARN (No lock) | **FAIL (Votes wiped on reload)** | **HIGH** |
| **Webhook Replay Deduplication** | FAIL | FAIL | **HIGH** |

**Summary:** While the architectural design of the fencing token protocol is theoretically sound, the PostgreSQL implementation has not been completed or tested end-to-end. It cannot be used in a production multi-worker deployment until the schema divergence is fixed and webhook deduplication is keyed on payload hashes.
