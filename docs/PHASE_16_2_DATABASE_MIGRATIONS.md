# ATLAS Phase 16.2 Database Schema & Migrations
## Relational Durability for Enterprise Business Processes

**Migration File:** `migrations/016_enterprise_process.sql`  
**Compatibility:** PostgreSQL 14+ and SQLite 3.35+  
**Date:** 2026-11-17  

---

## 1. Schema Architecture & Tables

The Phase 16.2 persistence layer introduces 15 relational tables designed for multi-tenant isolation, auditability, and worker lease fencing:

| Table Name | Primary Key | Key Invariants & Constraints | Purpose |
| :--- | :--- | :--- | :--- |
| `process_definitions` | `definition_id` | `UNIQUE(name, version, tenant_id)` | Master process definition registry |
| `process_definition_versions` | `version_id` | Foreign key to `process_definitions` | Content-addressed definition history |
| `process_instances` | `instance_id` | Indexed on `tenant_id`, `status` | Process execution instance state |
| `process_task_instances` | `task_instance_id` | Foreign key to `process_instances` | Individual task execution state |
| `process_execution_events` | `event_id` | Append-only event store | Audit trail of all process transitions |
| `process_checkpoints` | `checkpoint_id` | Monotonic `sequence_number` | Full serialized state snapshots |
| `process_worker_leases` | `lease_id` | `UNIQUE(task_instance_id)` | Monotonic fencing & lease expiration |
| `process_idempotency_records` | `idempotency_key` | `UNIQUE(idempotency_key, tenant_id)` | Prevents duplicate task executions |
| `process_approval_requests` | `approval_id` | Cryptographic parameter hash | Human approval requests & quorum rules |
| `process_approval_decisions` | `decision_id` | Foreign key to `process_approval_requests` | Audit log of individual approver votes |
| `process_saga_transactions` | `saga_id` | State progression & terminal locks | Long-running multi-step sagas |
| `process_saga_steps` | `step_id` | Step status & compensation tracking | Forward execution & rollback steps |
| `process_compensation_records`| `record_id` | Failure context & outcome | Historical record of rollbacks |
| `process_reconciliation_records`| `reconciliation_id` | Manual intervention required items | Unresolvable saga compensation queue |
| `process_event_inbox` / `outbox`| `event_id` | Transactional outbox pattern | Reliable cross-system event delivery |

---

## 2. Worker Lease Fencing Tokens

To eliminate distributed split-brain conditions where two workers concurrently attempt to commit results for the same task:
- `process_worker_leases` maintains `fencing_token BIGINT NOT NULL`.
- Every lease acquisition or renewal monotonically increments `fencing_token`.
- On completion (`complete_task`), the worker's submitted fencing token is checked against both in-memory state and the database lease record (`ON CONFLICT (task_instance_id) DO UPDATE SET fencing_token = process_worker_leases.fencing_token + 1`).
- Any attempt to commit with an outdated token is rejected with `StaleWorkerFencingError`.

---

## 3. Storage Engine Implementations

1. **`PostgresProcessStorage` (`packages/atlas-process/src/atlas_process/storage.py`):**
   - Configured with `psycopg_pool.ConnectionPool`.
   - All transactions are executed with parameterized queries, preventing SQL injection.
   - Leverages `JSONB` for deep querying of process variables, task inputs/outputs, and serialized checkpoint state.

2. **`SqliteProcessStorage` (`packages/atlas-process/src/atlas_process/storage.py`):**
   - Single-file embedded storage suitable for edge workers, desktop runtime, and isolated local development.
   - Automatically executes schema migration on initialization with `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON`.
   - Thread-safe synchronization enforced via `threading.RLock()`.
