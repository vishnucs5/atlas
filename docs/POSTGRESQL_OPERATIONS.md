# ATLAS PostgreSQL Production Operations Guide
## Enterprise Storage Architecture, Administration, Backup & Disaster Recovery

**Version:** 1.0  
**Target Environment:** PostgreSQL 16+ (Alpine / Enterprise Linux / Cloud Managed RDS)  
**Supported Drivers:** `psycopg` 3.2+ with `psycopg_pool`  

---

## 1. Overview & Architecture

ATLAS supports PostgreSQL as its primary distributed enterprise persistence engine. `PostgresStorage` implements all five core storage protocols defined by the ATLAS architecture:
1. `TaskStoreProtocol` — Materialized task records, state machine projection, and optimistic concurrency locking.
2. `EventStoreProtocol` — Immutable append-only event stream with strict monotonic sequence numbering and collision prevention.
3. `CheckpointStoreProtocol` — Sealed execution snapshots with cryptographic SHA-256 integrity verification.
4. `ActionLedgerStoreProtocol` — Action deduplication, idempotency tracking, and side-effect safety against blind retries of `UNKNOWN` actions.
5. `WorkerStoreProtocol` — Worker registration, capability advertising, heartbeats, and fencing generation tokens.

```mermaid
flowchart TD
    API["atlas-api (FastAPI)"] -->|psycopg_pool| PG[(PostgreSQL 16 Cluster)]
    Worker["atlas-worker (Daemon)"] -->|psycopg_pool| PG
    Dashboard["atlas-dashboard"] -->|REST / SSE| API
    Backup["atlas-backup cron"] -->|pg_dump + SHA256| Storage[(Encrypted Backup S3/Volume)]
```

---

## 2. Configuration & Connection Pooling

### Connection String Format
Set the standard PostgreSQL URL in `.env` or system environment:
```bash
ATLAS_DATABASE_URL=postgresql://atlas:atlas_password_production@localhost:5432/atlas_production
```

### Connection Pool Sizing
`PostgresStorage` manages pooled connections via `psycopg_pool.ConnectionPool`.

| Parameter | Recommended Default | Production High-Load | Notes |
|---|---|---|---|
| `min_pool_size` | 1 | 5 | Pre-warmed idle connections |
| `max_pool_size` | 20 | 50 | Upper limit per process |
| `timeout` | 10.0s | 15.0s | Max wait time before pool exhaustion error |
| `ssl_mode` | `prefer` | `verify-full` | Enforce TLS in cloud VPC |

---

## 3. Schema DDL & Migration

### Schema Tables & Constraints
The relational schema is auto-initialized idempotently on startup.

| Table Name | Primary Key | Key Indexes & Constraints | Purpose |
|---|---|---|---|
| `tasks` | `task_id` | `idx_tasks_status`, `idx_tasks_created_at` | Task lifecycle state machine projection |
| `execution_events` | `event_id` | `CONSTRAINT uq_task_sequence UNIQUE (task_id, sequence)` | Immutable execution log |
| `checkpoints` | `checkpoint_id` | `idx_checkpoints_task (task_id, created_at)` | State snapshots with SHA-256 seal |
| `action_ledger` | `(task_id, idempotency_key, attempt)` | `idx_ledger_action_id`, `idx_ledger_task_status` | Idempotency and unknown-outcome gating |
| `worker_registry` | `worker_id` | `status`, `last_heartbeat_at` | Worker node discovery & health |
| `worker_leases` | `lease_id` | `UNIQUE(task_id)`, `generation` | Monotonic fencing token locks |

### Manual Schema Migration Verification
To verify or inspect schema definitions using `psql`:
```bash
psql -U atlas -d atlas_production -c "\dt+"
psql -U atlas -d atlas_production -c "\di+"
```

---

## 4. Backup & Disaster Recovery Procedures

ATLAS provides built-in utilities in `packages/atlas-storage/src/atlas_storage/backup.py` with cryptographic checksum sidecars.

### A. Creating an Online Backup
Execute `create_postgres_backup()` via Python or CLI:
```python
from atlas_storage.backup import create_postgres_backup
from atlas_storage.postgres import PostgresStorage

storage = PostgresStorage("postgresql://atlas:secret@localhost:5432/atlas_production")
backup_path = create_postgres_backup(storage, "/var/backups/atlas/backup_20261113.sql")
print("Backup created at:", backup_path)
```

The backup procedure:
1. Calls `pg_dump` with `--clean --if-exists --no-owner --no-privileges`.
2. Computes SHA-256 checksum of the generated archive.
3. Queries row counts across `tasks`, `execution_events`, `checkpoints`, `worker_leases`, and `action_ledger`.
4. Generates `<dest>.meta.json` sidecar with password-scrubbed DSN metadata.

### B. Verifying Backup Integrity
Before any restore, verify the cryptographic seal:
```python
from atlas_storage.backup import verify_postgres_backup

meta = verify_postgres_backup("/var/backups/atlas/backup_20261113.sql")
print("Verified SHA-256:", meta["sha256_checksum"])
print("Recorded row counts:", meta["table_counts"])
```
If the archive was altered or corrupted, `BackupIntegrityError` is raised.

### C. Restoring into a Clean Database
To restore into a fresh database instance:
```python
from atlas_storage.backup import restore_postgres_backup

restore_postgres_backup(
    backup_path="/var/backups/atlas/backup_20261113.sql",
    target="postgresql://atlas:secret@localhost:5432/atlas_restored",
)
```
The restore procedure:
1. Verifies the SHA-256 checksum and header markers.
2. Restores tables and data using `psql`.
3. Deterministically queries target database row counts and asserts they match or exceed the metadata counts.

### D. Backup Retention Policy
Prune backups older than $N$ days while keeping at least $K$ most recent copies:
```python
from atlas_storage.backup import clean_old_backups

removed = clean_old_backups("/var/backups/atlas", max_age_days=14, min_retained=5)
print("Pruned old backups:", [str(p) for p in removed])
```

---

## 5. Security & Operational Hardening

1. **Credential Scrubbing:** Passwords in connection strings are masked as `***REDACTED***` in all log messages, error messages, and metadata sidecars.
2. **Fencing Protection:** Worker commits verify monotonic `lease_generation`. Any superseded worker attempting an action commit is rejected with `StaleWorkerError`.
3. **Optimistic Locking:** Task transitions require expected state checks; concurrent updates raise `OptimisticLockError`.
4. **Side-Effect Safety:** Non-idempotent actions (`CLICK`, `EXECUTE_COMMAND`) interrupted during worker failure remain in `UNKNOWN` status and cannot be retried without manual or physical environment reconciliation.
