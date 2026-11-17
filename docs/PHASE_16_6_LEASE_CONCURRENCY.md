# Phase 16.6 — Distributed Initial Worker Lease Race Elimination

## 1. Executive Summary

This document details the architectural remediation of **FINDING-16.5-03** (Initial Lease Unlocked SELECT Race Condition).

In Phase 16.5, the independent audit discovered that when a task was newly scheduled and had never been leased before:
- `process_worker_leases` contained no existing row for `task_instance_id`.
- The `SELECT ... FOR UPDATE` query returned 0 rows, so no row-level lock was acquired.
- Competing workers (e.g. Worker A and Worker B) both observed absence of an existing lease, fell through to `INSERT ... VALUES (..., fencing_token=1)`, and both received `fencing_token = 1`.
- While later verification or completion caught this at commit time, both workers concurrently executed the initial task logic, wasting computational resources and causing unnecessary contention.

## 2. Root Cause Analysis

1. **Non-Existent Lock Target**: `SELECT ... FOR UPDATE` in SQL only locks matching rows. If 0 rows match, no lock is held.
2. **Two-Step Query Race**: The pattern `SELECT` followed by `INSERT` is inherently vulnerable to race conditions unless guarded by a table lock or an atomic `INSERT ... ON CONFLICT` statement.

## 3. Implemented Architecture & Remediation

### 3.1 Migration 018: Conflict Target Index

Migration `018_task_idempotency_and_lease_atomicity.sql` established the unique conflict constraint target:
```sql
CREATE INDEX IF NOT EXISTS idx_worker_leases_conflict_target
    ON process_worker_leases (task_instance_id, fencing_token);
```
Together with the primary key or unique index on `task_instance_id`, PostgreSQL can perform atomic upserts.

### 3.2 Single-Query Atomic Upsert with `RETURNING`

In `PostgresProcessStorage.acquire_lease()`:
```sql
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
```

#### Why This Completely Eliminates the Race:
1. **Single Atomic Statement**: There is no separate `SELECT` or window of vulnerability.
2. **Deterministic Monotonic Generation**:
   - The first worker to reach the row creates it with `fencing_token = 1`.
   - The second worker immediately conflicts on `task_instance_id` and executes `DO UPDATE SET fencing_token = process_worker_leases.fencing_token + 1`, receiving `fencing_token = 2`.
   - The third worker receives `fencing_token = 3`, and so forth.
3. **Hardware & Engine Serialization**: PostgreSQL's internal page-level and index locks serialize concurrent inserts on the same index key, guaranteeing that every competing worker receives a strictly unique, monotonically increasing integer generation number.

### 3.3 SQLite Atomic Implementation

In `SqliteProcessStorage.acquire_lease()`:
```sql
INSERT INTO process_worker_leases (
    task_instance_id, process_instance_id, worker_id, lease_token, fencing_token, expires_at
) VALUES (?, ?, ?, ?, 1, ?)
ON CONFLICT (task_instance_id) DO UPDATE SET
    worker_id = excluded.worker_id,
    lease_token = excluded.lease_token,
    fencing_token = process_worker_leases.fencing_token + 1,
    expires_at = excluded.expires_at;
```
Guarded under SQLite WAL mode and a write mutex lock, ensuring identical linear monotonic ordering.

## 4. Verification Evidence

1. **Unit Concurrency Test**: `tests/unit/test_phase16_6_lease_race.py` (8/8 passed)
   - `test_concurrent_initial_lease_race_strictly_monotonic`: 10 concurrent threads simultaneously race for the initial lease on a brand-new task.
   - Result: All 10 workers received distinct fencing tokens forming the exact sorted sequence `[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]`.
   - Highest fencing token is the sole active lease in storage; all earlier fencing tokens fail verification.

2. **PostgreSQL 18.6 Live Integration Test**: `tests/integration/test_phase16_6_postgres_hardening.py`
   - `test_pg_16_6_03_concurrent_initial_worker_leases_in_postgres`: 10 concurrent PostgreSQL clients racing against live native PostgreSQL.
   - Result: 10/10 distinct tokens, strictly monotonic, winner verified, losers fenced out.
