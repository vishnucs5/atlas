# ATLAS Phase 16.9 — Database Architecture & Durability Audit

## 1. Database Engineering Overview

The ATLAS process persistence layer supports both embedded SQLite (for edge and single-node development) and native PostgreSQL 18.6+ (for clustered enterprise deployment).

---

## 2. Schema Migrations Audit (001 through 018)

- **Migration System:** Declarative forward SQL migrations executed sequentially.
- **Migration 018:**
  - Added table `process_operation_idempotency` with composite primary key `(tenant_id, idempotency_key)`, SHA-256 fingerprint, status check constraint, and update trigger.
  - Added unique conflict target index `idx_worker_leases_conflict_target` on `process_worker_leases(task_instance_id, fencing_token)`.
- **Integrity Constraints:**
  - Foreign keys enabled with cascading deletes on child executions where appropriate.
  - Enforced `NOT NULL` constraints on tenant identifiers, process IDs, and creation timestamps.
- **Verification:** Verified against live PostgreSQL 18.6 in `test_pg_16_4_01_migrations_and_schema_integrity` and `test_pg_16_6_01_migration_018_schema_verification`.

---

## 3. Concurrency, Locking, and ACID Semantics

### 3.1 Approval Quorum Resolution Under Contention
To prevent stale in-memory race conditions across multi-worker clusters:
- `storage.decide_approval()` opens a dedicated transaction.
- Executes `SELECT ... FROM process_approval_requests WHERE tenant_id = ? AND approval_id = ? FOR UPDATE`.
- Calculates decision from durable records and commits atomically.
- **Empirical Proof:** Verified under multi-threaded concurrency in `test_pg_16_6_02_approval_concurrency_row_locking`.

### 3.2 Atomic Worker Lease Upsert
To eliminate initial lease race conditions on newly queued tasks:
- Executes single-statement atomic upsert:
  ```sql
  INSERT INTO process_worker_leases (tenant_id, task_instance_id, worker_id, lease_token, fencing_token, expires_at)
  VALUES (?, ?, ?, ?, 1, ?)
  ON CONFLICT (task_instance_id) DO UPDATE
  SET fencing_token = process_worker_leases.fencing_token + 1,
      lease_token = EXCLUDED.lease_token,
      worker_id = EXCLUDED.worker_id,
      expires_at = EXCLUDED.expires_at
  RETURNING fencing_token, lease_token;
  ```
- **Empirical Proof:** Verified with 10 concurrent threads in `test_pg_16_6_03_concurrent_initial_worker_leases_in_postgres`.

---

## 4. Backup, Restore, and Disaster Recovery

1. **Physical Backup:** PostgreSQL Point-In-Time-Recovery (PITR) with WAL archiving (`pg_dump` and continuous archiving).
2. **Migration Rollbacks:** Every migration script maintains a documented rollback counterpart in `migrations/rollback/`.
3. **Connection Pool Sizing:**
   - Minimum connections: 5
   - Maximum connections: 20 per engine pod
   - Connection timeout: 10s
   - Idle connection reclaim: 300s
