# Phase 16.4 — Reconciliation Record Retention & Archival Guardrails

## 1. Executive Summary

This document details the architectural remediation of **NEW-16.3-04** (Archival Cascade Deletion of Reconciliation Records).

In Phase 16.2, scheduled archival of completed or failed process instances (`archive_completed_instances`) executed `DELETE FROM process_instances WHERE status IN ('COMPLETED', 'FAILED')`. Because foreign keys between `process_instances`, `process_saga_transactions`, and `process_reconciliation_records` had `ON DELETE CASCADE`, archiving an instance silently deleted active, unresolved financial discrepancies from the audit ledger.

## 2. Root Cause Analysis

1. **Foreign Key Cascade Hierarchy**:
   `process_instances` -> (CASCADE) -> `process_saga_transactions` -> (CASCADE) -> `process_reconciliation_records`.
2. **Missing Application-Level Exclusion**: The archival deletion query lacked a subquery check to verify whether any associated sagas had unresolved reconciliation records (`status = 'PENDING'`).

## 3. Implemented Remediation

### 3.1 Migration `017_process_lease_integrity.sql`
- **Constraint Severing**: Altered `process_reconciliation_records_saga_id_fkey` from `ON DELETE CASCADE` to `ON DELETE RESTRICT`. A saga transaction can never be deleted while any reconciliation record references it.
- **Nullified Instance Archival**: Altered `process_saga_transactions.process_instance_id` to allow `NULL` with `ON DELETE SET NULL`. When a completed process instance with historical (resolved) reconciliations is archived, the process instance row is cleaned up, but the saga transaction and all reconciliation records remain permanently in the database for compliance and financial auditing.
- **Index**: Created index `idx_reconciliation_status` ON `process_reconciliation_records(status)`.

### 3.2 SQL Archival Protection Query
In `PostgresProcessStorage.archive_completed_instances` and `SqliteProcessStorage.archive_completed_instances`:
```sql
DELETE FROM process_instances
WHERE status IN ('COMPLETED', 'FAILED')
  AND completed_at IS NOT NULL
  AND completed_at < %s
  AND instance_id NOT IN (
      SELECT pst.process_instance_id
      FROM process_saga_transactions pst
      JOIN process_reconciliation_records prr ON prr.saga_id = pst.saga_id
      WHERE prr.status = 'PENDING'
  );
```

### 3.3 Storage Protocol Methods
Added the following lifecycle methods across `InMemoryProcessStorage`, `SqliteProcessStorage`, and `PostgresProcessStorage`:
- `record_reconciliation(saga_id, step_id, reason, notes) -> int`
- `list_reconciliations(status=None) -> list[dict]`
- `resolve_reconciliation(record_id, resolved_by, notes) -> bool`

## 4. Verification Evidence

- `tests/unit/test_phase16_4_archival.py`: 2/2 passed (memory and SQLite).
- `tests/integration/test_phase16_4_postgres_full.py::test_pg_16_4_06_archival_retention_and_event_inbox`: PASSED against native PostgreSQL.
