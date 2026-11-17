# ATLAS Database Disaster Recovery Runbook

## 1. Scope & Objective

Procedures for recovering ATLAS persistence stores (PostgreSQL and SQLite) from storage failure, database node crash, transaction deadlock storms, or data loss incidents.

---

## 2. Recovery Objectives

- **Recovery Point Objective (RPO):** < 5 minutes (via continuous WAL archiving).
- **Recovery Time Objective (RTO):** < 30 minutes for complete cluster restore.

---

## 3. Step-by-Step Restoration Protocol

### 3.1 Point-In-Time-Recovery (PITR) Restoration
1. Stop all ATLAS API and Worker services to prevent writes to the target database:
   ```bash
   kubectl scale deployment/atlas-api --replicas=0 -n atlas-staging
   kubectl scale deployment/atlas-worker --replicas=0 -n atlas-staging
   ```
2. Provision a clean PostgreSQL instance with matching major version (18.6).
3. Restore base backup:
   ```bash
   pg_basebackup -h $BACKUP_HOST -D /var/lib/postgresql/data -U replicator -v -P -X stream
   ```
4. Configure `recovery.signal` and `postgresql.conf`:
   ```ini
   restore_command = 'cp /mnt/wal_archive/%f %p'
   recovery_target_time = '2026-11-17 12:00:00 UTC'
   ```
5. Start PostgreSQL and verify recovery completion:
   ```bash
   pg_ctl start -D /var/lib/postgresql/data
   tail -n 50 /var/log/postgresql/postgresql.log
   ```

### 3.2 Post-Recovery State Alignment
Once database is restored:
1. Identify all operations that were in `IN_PROGRESS` at recovery target time:
   ```sql
   UPDATE process_operation_idempotency
   SET status = 'UNKNOWN_OUTCOME',
       error_message = 'Database restored via PITR; outcome ambiguous at restore timestamp'
   WHERE status = 'IN_PROGRESS';
   ```
2. Update corresponding tasks to `SUSPENDED`:
   ```sql
   UPDATE process_task_instances
   SET status = 'SUSPENDED',
       error = 'Restored via PITR; manual reconciliation required'
   WHERE status = 'RUNNING';
   ```
3. Restart ATLAS services:
   ```bash
   kubectl scale deployment/atlas-api --replicas=3 -n atlas-staging
   kubectl scale deployment/atlas-worker --replicas=5 -n atlas-staging
   ```
