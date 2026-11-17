# ATLAS Phase 16.7 — Distributed Worker Lease Concurrency Audit Report

## 1. Executive Summary

This report delivers the independent technical audit of **FINDING-16.5-03** (Initial Lease Unlocked SELECT Race Condition) in ATLAS Phase 16.6 at commit `c309ec4e5be6cf438aa7ee038e5a34c2d8e37d57`.

The audit evaluated whether replacing the two-step `SELECT ... FOR UPDATE` + `INSERT` lease acquisition sequence with a single atomic `INSERT ... ON CONFLICT (task_instance_id) DO UPDATE SET fencing_token = process_worker_leases.fencing_token + 1 RETURNING fencing_token, lease_token` deterministically eliminates the initial lease acquisition race under multi-threaded and multi-process concurrency against native PostgreSQL 18.6.

## 2. Code Inspection & Line-Level Verification

### 2.1 Atomic Upsert in PostgreSQL (`storage.py:2284-2335`)

```python
with pool.connection() as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO process_worker_leases (
                lease_id, task_instance_id, process_instance_id, worker_id, lease_token, fencing_token, status, acquired_at, expires_at
            ) VALUES (%s, %s, %s, %s, %s, 1, 'ACTIVE', %s, %s)
            ON CONFLICT (task_instance_id) DO UPDATE SET
                worker_id = EXCLUDED.worker_id,
                lease_token = EXCLUDED.lease_token,
                fencing_token = process_worker_leases.fencing_token + 1,
                status = 'ACTIVE',
                acquired_at = EXCLUDED.acquired_at,
                expires_at = EXCLUDED.expires_at
            RETURNING fencing_token, lease_token;
            """,
            (lease_id, task_instance_id, process_instance_id, worker_id, token, now, expires_at),
        )
        row = cur.fetchone()
        fencing_token = row[0]
        lease_token = row[1]
    conn.commit()
    return lease_token, fencing_token
```

#### Why This Statement Eliminates the Race Condition:
1. **Zero Unlocked Window**: There is no separate `SELECT` statement that can return 0 rows when a lease row does not yet exist.
2. **PostgreSQL Engine-Level Index Mutex**: PostgreSQL uses index-level locking on the conflict target (`task_instance_id`). When concurrent transactions attempt to insert the same `task_instance_id`, one transaction acquires the insert lock while all others wait on the conflict queue.
3. **Monotonic Counter Serialization**: The waiting transactions proceed to the `DO UPDATE` branch sequentially, incrementing `process_worker_leases.fencing_token + 1`.
4. **Immediate Output via `RETURNING`**: The statement returns the exact `fencing_token` and `lease_token` assigned by the database engine within the same atomic operation.

### 2.2 Verification Invariant (`storage.py:2337-2365`)

```python
def verify_lease(
    self,
    task_instance_id: str,
    lease_token: str,
    fencing_token: int,
) -> bool:
    pool = self._ensure_pool()
    now = time.time()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT lease_token, fencing_token, status, expires_at
                FROM process_worker_leases
                WHERE task_instance_id = %s
                """,
                (task_instance_id,),
            )
            row = cur.fetchone()
            if not row:
                return False
            active_lease_token, active_fencing, status, expires_at = row
            if status != "ACTIVE":
                return False
            if active_fencing != fencing_token:
                return False
            if active_lease_token != lease_token:
                return False
            if expires_at is not None and expires_at < now:
                return False
            return True
```
- Only the worker possessing the **exact matching active fencing token** AND **exact matching active lease token** passes verification.
- Any worker possessing an older fencing generation (`worker_fencing < active_fencing`) is immediately rejected.

## 3. Concurrency & Stress Verification Scenarios

### Scenario 1: 10 Concurrent Workers Racing on Initial Task Lease (PostgreSQL 18.6)
- **Test File**: `tests/integration/test_phase16_6_postgres_hardening.py::test_pg_16_6_03_concurrent_initial_worker_leases_in_postgres`
- **Environment**: Native PostgreSQL 18.6, 10 concurrent threads simultaneously invoking `acquire_lease()` on a newly scheduled task with 0 existing lease rows.
- **Observed Behavior**:
  - Worker fencing tokens returned: `{1, 2, 3, 4, 5, 6, 7, 8, 9, 10}`.
  - Number of unique fencing tokens: **10 of 10** (zero duplicates).
  - Number of unique lease tokens: **10 of 10**.
  - Winner verification: Worker with `fencing_token = 10` verified as active in PostgreSQL.
  - Loser fencing: Workers 1 through 9 all failed `verify_lease()` (`False`).
- **Verdict**: **PASSED**.

### Scenario 2: Initial Lease Race on SQLite (WAL Mode)
- **Test File**: `tests/unit/test_phase16_6_lease_race.py::test_concurrent_initial_lease_race_strictly_monotonic[sqlite]`
- **Environment**: SQLite WAL mode with mutex lock.
- **Observed Behavior**: 10 concurrent workers all received unique sequential tokens `1..10`. Highest token verified active; earlier tokens fenced out.
- **Verdict**: **PASSED**.

### Scenario 3: Lease Expiry, Renewal, and Fencing Progression
- **Test File**: `tests/unit/test_phase16_6_lease_race.py::test_lease_expiry_and_reacquisition`
- **Observed Behavior**:
  - Lease acquired with duration = 0.01s (token 1).
  - After expiry, second worker acquires lease (token 2).
  - Worker 1 attempt to verify or complete fails immediately. Worker 2 succeeds.
- **Verdict**: **PASSED**.

## 4. Audit Assessment & Closure Status

| Audit Criterion | Required Guarantee | Implementation Assessment | Status |
| :--- | :--- | :--- | :---: |
| **Initial Upsert Atomicity** | No two workers receive fencing token 1 | Verified via `INSERT ... ON CONFLICT DO UPDATE` | **VERIFIED** |
| **Strict Monotonicity** | Fencing generations strictly increment | 10 concurrent workers produced exact sequence 1..10 | **VERIFIED** |
| **Stale Worker Fencing** | Older generations cannot commit | `active_fencing != fencing_token` check verified | **VERIFIED** |
| **Relational Integrity** | Task FK validated in PostgreSQL | Foreign key references `process_task_instances` | **VERIFIED** |

**FINDING-16.5-03 Final Status:** **VERIFIED CLOSED**
