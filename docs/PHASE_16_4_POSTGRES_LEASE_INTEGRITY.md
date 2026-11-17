# Phase 16.4 — PostgreSQL Worker Lease Integrity & Fencing Tokens

## 1. Executive Summary

This document details the architectural remediation of **NEW-16.3-01** (Worker Lease Token Column Missing) and the formal verification of distributed fencing token monotonicity under PostgreSQL and SQLite storage engines.

Prior to Phase 16.4, the schema for `process_worker_leases` lacked an explicit `lease_token` column, causing runtime lease acquisition and completion verifications to fail or rely on unverified lease identifiers. Furthermore, lease releases previously deleted database rows, destroying fencing token sequence state and resetting counters back to generation 1 on re-acquisition.

## 2. Root Cause Analysis

1. **Schema Divergence**: Migration `016_enterprise_process.sql` defined `process_worker_leases` with `(lease_id, task_instance_id, process_instance_id, worker_id, expires_at, fencing_token)`. However, `ProcessExecutionEngine` and `PostgresProcessStorage` generated cryptographically secure random tokens `lease_tok_<uuid>` and attempted to persist them into `lease_token`.
2. **Fencing Token Erasure on Release**: Calling `release_lease` issued `DELETE FROM process_worker_leases WHERE task_instance_id = ?`. If another worker subsequently acquired a lease on the same task instance, the absence of an existing row caused the fencing counter to re-initialize to 1 rather than incrementing monotonically to `N + 1`. This violated the distributed consensus invariant that fencing tokens must be strictly monotonic across worker epochs.

## 3. Implemented Remediation

### 3.1 Migration `017_process_lease_integrity.sql`
- Added `lease_token VARCHAR(64) NOT NULL` to table `process_worker_leases`.
- Populated existing rows from `lease_id` and added indices:
  - `idx_worker_leases_token` ON `process_worker_leases(lease_token)`
  - `idx_worker_leases_task_token` ON `process_worker_leases(task_instance_id, lease_token)`

### 3.2 Row-Level Locking & Monotonic Increments
- In `PostgresProcessStorage.acquire_lease`:
  ```sql
  SELECT worker_id, expires_at, fencing_token 
  FROM process_worker_leases 
  WHERE task_instance_id = %s FOR UPDATE;
  ```
  Fencing token is computed as `(row[2] + 1) if row else 1`.
  The update is performed atomically via `ON CONFLICT (task_instance_id) DO UPDATE`.

### 3.3 Lease Release Invariant Preservation
- In `PostgresProcessStorage.release_lease` and `SqliteProcessStorage.release_lease`:
  Releasing a lease no longer deletes the row. Instead, it marks the lease as expired and clears the active token:
  ```sql
  UPDATE process_worker_leases 
  SET expires_at = 0.0, lease_token = '' 
  WHERE task_instance_id = %s;
  ```
  This preserves the historical row and ensures any subsequent lease acquisition strictly increments the fencing counter monotonically.

### 3.4 Verification & Completion Handshake
- `verify_lease(task_instance_id, lease_token, fencing_token)` checks:
  1. `lease_token` matches the active token.
  2. `fencing_token` matches `expected_fencing_token`.
  3. Current timestamp does not exceed `expires_at`.
- Stale workers attempting task completion with outdated tokens are immediately rejected with `StaleWorkerFencingError`.

## 4. Verification Evidence

- `tests/unit/test_phase16_4_leases.py`: 8/8 passed.
- `tests/integration/test_phase16_4_postgres_full.py`:
  - `test_pg_16_4_01_migrations_and_schema_integrity`: PASSED
  - `test_pg_16_4_02_task_lease_and_completion_lifecycle`: PASSED
  - `test_pg_16_4_03_fencing_token_staleness_rejection`: PASSED
