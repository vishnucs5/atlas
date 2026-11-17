# ATLAS Phase 16.5 — Reconciliation Retention & Archival Guardrails Audit

## 1. Executive Summary

This audit evaluated the persistence, retention, and lifecycle guardrails of reconciliation records and saga transactions during operational maintenance and instance archival.

Finding `NEW-16.3-04` (cascade deletion of unresolved reconciliation records and permanent data loss upon instance archival) is **GENUINELY REMEDIATED**. Unresolved reconciliation records are protected from deletion at both the application query level and the database foreign-key constraint level.

---

## 2. Foreign Key Constraint Hardening

In Migration 017 (`migrations/017_process_lease_integrity.sql`), foreign key cascades were severed and replaced with restrictive invariants:

### 1. `process_reconciliation_records` Protection:
```sql
ALTER TABLE process_reconciliation_records DROP CONSTRAINT process_reconciliation_records_saga_id_fkey;
ALTER TABLE process_reconciliation_records ADD CONSTRAINT process_reconciliation_records_saga_id_fkey
    FOREIGN KEY (saga_id) REFERENCES process_saga_transactions(saga_id) ON DELETE RESTRICT;
```
If any administrative process or manual query attempts to delete a `process_saga_transactions` record while reconciliation records exist, PostgreSQL immediately blocks the deletion with `psycopg.errors.RestrictViolation`.

### 2. `process_saga_transactions` Retention on Archival:
```sql
ALTER TABLE process_saga_transactions ALTER COLUMN process_instance_id DROP NOT NULL;
ALTER TABLE process_saga_transactions DROP CONSTRAINT process_saga_transactions_process_instance_id_fkey;
ALTER TABLE process_saga_transactions ADD CONSTRAINT process_saga_transactions_process_instance_id_fkey
    FOREIGN KEY (process_instance_id) REFERENCES process_instances(instance_id) ON DELETE SET NULL;
```
When historical process instances are archived or purged from `process_instances`, the referencing saga transactions are **not deleted**. Instead, `process_instance_id` is set to `NULL`, retaining the permanent transaction history and forensic audit trail.

---

## 3. Archival Query Protection Verification

In both `PostgresProcessStorage.archive_completed_instances()` and `SqliteProcessStorage.archive_completed_instances()`:

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
  )
```

### Empirical Verification:
1. **Pending Reconciliation Protection**:
   An instance older than the cutoff threshold possessing an unresolved reconciliation record (`status = 'PENDING'`) was submitted to `archive_completed_instances()`.
   **Result**: The instance was excluded from deletion; row remained intact in `process_instances`.
2. **Resolved Reconciliation Archival**:
   The reconciliation record was updated to `status = 'RESOLVED'`. `archive_completed_instances()` was invoked again.
   **Result**: The operational instance was purged from `process_instances`, but `process_saga_transactions` and `process_reconciliation_records` were retained with `process_instance_id = NULL`.
3. **Audit Compliance**:
   Financial and regulatory compliance standards (SOX, SOC 2, HIPAA) require immutable retention of exception reconciliation records. The database constraints guarantee that unresolved business discrepancies cannot be lost or purged during routine database maintenance.
