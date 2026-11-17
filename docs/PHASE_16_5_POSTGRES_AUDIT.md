# ATLAS Phase 16.5 — PostgreSQL Lease Integrity & Concurrency Audit

## 1. Executive Summary

This audit evaluated PostgreSQL worker leases, distributed fencing token generation, migration idempotency, and multi-process concurrency against native PostgreSQL 18.6.

The critical defect identified in Phase 16.3 (`NEW-16.3-01`: missing `lease_token` column crashing task completion with `psycopg.errors.UndefinedColumn`) is **GENUINELY REMEDIATED**. Tasks now successfully complete in PostgreSQL with valid lease tokens and monotonic fencing checks.

However, empirical multi-process concurrency testing revealed an edge case in initial lease generation when two distributed workers compete simultaneously on a newly created task instance.

---

## 2. Migration 017 Verification

`migrations/017_process_lease_integrity.sql` was evaluated against an active PostgreSQL instance:
1. **Idempotency**: Repeated execution executes cleanly (`DO $$ ... IF NOT EXISTS ... END $$;`).
2. **Schema Alterations**:
   - Added column `lease_token VARCHAR(64) NOT NULL` to table `process_worker_leases`.
   - Created performance indexes: `idx_worker_leases_token` and `idx_worker_leases_task_token`.
   - Replaced foreign key cascade on `process_reconciliation_records` with `ON DELETE RESTRICT`.
   - Added index `idx_reconciliation_status` on `process_reconciliation_records(status)`.
   - Severed cascade deletion on `process_saga_transactions` by making `process_instance_id` nullable with `ON DELETE SET NULL`.
3. **Empty Database Migration**:
   Running migrations from scratch against an empty PostgreSQL database initializes all 11 tables cleanly without foreign key violations.

---

## 3. Worker Lease & Fencing Token Mechanics

In `packages/atlas-process/src/atlas_process/storage.py`:

```python
def acquire_lease(
    self,
    task_instance_id: str,
    process_instance_id: str,
    worker_id: str,
    lease_duration_seconds: float = 60.0,
) -> tuple[str, int]:
    pool = self._ensure_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fencing_token FROM process_worker_leases WHERE task_instance_id = %s FOR UPDATE",
                (task_instance_id,),
            )
            existing = cur.fetchone()
            current_fencing = (existing[0] if existing else 0) + 1
            token = f"lease_{uuid.uuid4().hex[:12]}"
            now = time.time()
            expires_at = now + lease_duration_seconds

            cur.execute(
                """
                INSERT INTO process_worker_leases (
                    lease_id, task_instance_id, process_instance_id, worker_id, lease_token, fencing_token, status, acquired_at, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, 'ACTIVE', %s, %s)
                ON CONFLICT (task_instance_id) DO UPDATE SET
                    worker_id = EXCLUDED.worker_id,
                    lease_token = EXCLUDED.lease_token,
                    fencing_token = EXCLUDED.fencing_token,
                    status = 'ACTIVE',
                    acquired_at = EXCLUDED.acquired_at,
                    expires_at = EXCLUDED.expires_at;
                """,
                ...,
            )
        conn.commit()
        return token, current_fencing
```

### Monotonicity on Release
In Phase 16.3, `release_lease()` executed `DELETE FROM process_worker_leases`, resetting the fencing counter to zero on subsequent acquisition. In Phase 16.4, `release_lease()` updates `expires_at = 0.0, lease_token = ''` while keeping the row intact.
Empirical verification:
- Acquire 1: `fencing_token = 1`
- Release 1: Row kept with `expires_at = 0.0`
- Acquire 2: `fencing_token = 2` (monotonic increment confirmed).

---

## 4. Multi-Process Concurrency Findings (Independent Probe 1)

An independent concurrency probe was executed where two separate OS processes (`worker_A` and `worker_B`) attempted to acquire a lease simultaneously on a newly created task instance in PostgreSQL.

### Probe Results
```text
=== PROBE 1: Multi-Process Lease Acquisition on New Task ===
Lease results: [
    ('success', 'worker_A', 'lease_7fdca2ef5aad', 1),
    ('success', 'worker_B', 'lease_f442524b3878', 1)
]
DB Lease row: ('worker_B', 'lease_f442524b3878', 1)
```

### Analysis
1. **Race Condition Window**:
   When a task instance is newly created, no row exists yet in `process_worker_leases`.
   `SELECT fencing_token FROM process_worker_leases WHERE task_instance_id = %s FOR UPDATE` matches 0 rows, so row-level locking cannot lock a non-existent row.
   Both workers execute the query concurrently, both receive `existing = None`, and both calculate `current_fencing = 1`.
2. **Resolution via `lease_token`**:
   Worker B's `INSERT ... ON CONFLICT DO UPDATE` commits last, overwriting Worker A's `lease_token`.
   When Worker A later calls `verify_lease(task_inst_id, 'lease_7fdca2ef5aad', 1)`, `row[0] != lease_token` triggers, correctly rejecting Worker A with `StaleWorkerFencingError`.
3. **Residual Inefficiency**:
   While data corruption is prevented because Worker A is fenced out by its invalidated `lease_token`, Worker A runs its execution under the assumption that it holds valid lease `fencing_token = 1`, only discovering it was fenced out at completion time.
4. **Architectural Recommendation**:
   Initialize lease placeholder rows upon task creation or calculate fencing token in PostgreSQL via atomic SQL:
   `fencing_token = COALESCE(process_worker_leases.fencing_token, 0) + 1` directly within the `ON CONFLICT DO UPDATE` clause.
