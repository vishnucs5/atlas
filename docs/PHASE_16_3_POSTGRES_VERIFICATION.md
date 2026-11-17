# ATLAS Phase 16.3 Independent Audit: PostgreSQL 18.6 Empirical Verification

**Audit Target Branch:** `feat/phase-16-2-remediation`  
**Base Commit:** `88d077405dfe8e53eb9708434c594993b9ce96e0`  
**PostgreSQL Version:** PostgreSQL 18.6 (x86_64-pc-mingw64) via `embedded-postgres`  
**Audit Date:** November 17, 2026  
**Auditor:** ATLAS Independent Audit Team (Phase 16.3)  
**Status:** Defect Discovered — CRITICAL PERSISTENCE DIVERGENCE

---

## 1. Environment & Target Verification

Empirical verification was conducted against a genuine native PostgreSQL database server running on localhost:
- **Server Version:** `PostgreSQL 18.6, 64-bit`
- **Driver:** `psycopg` (v3) async/sync client
- **Database Schema:** `migrations/016_enterprise_process.sql`
- **Tables Applied:** 16 relational tables

```sql
process_instances
process_definition_records
process_task_executions
process_saga_transactions
process_saga_steps
process_reconciliation_records
process_approval_requests
process_approval_decisions
process_worker_leases
process_events
process_worker_nodes
process_webhooks
process_metrics
process_tenant_configs
process_connector_definitions
process_connector_invocations
```

All 16 tables were verified present in PostgreSQL's `information_schema.tables`.

---

## 2. 14 Empirical Experiments on Real PostgreSQL

To independently verify the claims of persistence and crash recovery, 14 targeted experiments were executed directly against the active PostgreSQL instance:

| # | Experiment Focus | Expected Behavior | Observed Result | Status |
| :--- | :--- | :--- | :--- | :---: |
| **01** | Database Ping & TLS Handshake | Valid connection & timestamp | `SELECT NOW()` returned timestamp | **PASS** |
| **02** | DDL Schema Integrity | All 16 tables exist | 16 tables confirmed in `information_schema` | **PASS** |
| **03** | Tenant Data Isolation | Tenant B cannot read Tenant A records | Query with non-matching `tenant_id` returns 0 rows | **PASS** |
| **04** | Fencing Token Monotonicity | Increments monotonically per task/instance | Sequence incremented 1 -> 2 -> 3 without regression | **PASS** |
| **05** | Instance State Roundtrip | Save & retrieve full instance | Complete state JSON preserved and parsed | **PASS** |
| **06** | Lease Acquisition | Worker records active lease with expiry | Lease inserted with valid expiry | **PASS** |
| **07** | Lease Verification & Completion | Worker completes task using lease token | **FATAL CRASH**: `UndefinedColumn` on `lease_token` | **CRITICAL FAIL** |
| **08** | Multi-Approver Quorum Reload | In-flight quorum decisions persist | Decisions list empty (`[]`); votes dropped | **HIGH FAIL** |
| **09** | Saga Transaction Persistence | Saga states and step rollbacks saved | `process_saga_steps` table remains completely empty | **CRITICAL FAIL** |
| **10** | Event Audit Log Immutability | Events written sequentially with timestamps | Append-only log intact with strict order | **PASS** |
| **11** | Worker Node Registration | Heartbeats update worker metadata | Heartbeat timestamp and node load updated | **PASS** |
| **12** | Archival & Foreign Key Integrity | Archiving instances cleans dependencies | Cascades delete unresolved manual reconciliation items | **HIGH FAIL** |
| **13** | Process Crash & Restart Recovery | Incomplete instance recovered after restart | Instance marked for recovery and reassigned | **PASS\*** |
| **14** | Large Payload Persistence | Store 100KB complex JSON execution context | Full serialization and deserialization successful | **PASS** |

*\*Note on Experiment 13: Succeeded only because the recovery test did not exercise task completion via `complete_task`.*

---

## 3. Dissection of Critical Finding NEW-16.3-01: Undefined Column `lease_token`

### 3.1 Defect Demonstration & Exact Stack Trace

When `PostgresProcessStorage.complete_task` was executed with a worker lease, the following crash occurred:

```text
psycopg.errors.UndefinedColumn: column "lease_token" does not exist
LINE 1: SELECT lease_token, fencing_token, expires_at FROM process_w...
               ^
HINT:  Perhaps you meant to reference the column "process_worker_leases.lease_id".
  File "packages\atlas-process\src\atlas_process\storage.py", line 905, in verify_lease
    cur.execute(
        "SELECT lease_token, fencing_token, expires_at FROM process_worker_leases WHERE task_id = %s",
        (task_id,),
    )
```

### 3.2 Root Cause Analysis

1. **Schema DDL Definition (`migrations/016_enterprise_process.sql`):**
   ```sql
   CREATE TABLE IF NOT EXISTS process_worker_leases (
       lease_id VARCHAR(64) PRIMARY KEY,
       task_id VARCHAR(64) NOT NULL,
       worker_id VARCHAR(64) NOT NULL,
       instance_id VARCHAR(64) NOT NULL REFERENCES process_instances(instance_id) ON DELETE CASCADE,
       tenant_id VARCHAR(64) NOT NULL,
       fencing_token BIGINT NOT NULL DEFAULT 1,
       acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
       expires_at TIMESTAMPTZ NOT NULL,
       renewed_at TIMESTAMPTZ
   );
   ```
   The column is named `lease_id`, not `lease_token`.

2. **Storage Implementation (`packages/atlas-process/src/atlas_process/storage.py`):**
   - In `record_lease` (line ~880):
     ```python
     token = str(uuid.uuid4())
     cur.execute(
         """
         INSERT INTO process_worker_leases (lease_id, task_id, worker_id, instance_id, tenant_id, fencing_token, expires_at)
         VALUES (%s, %s, %s, %s, %s, %s, %s)
         """,
         (lease_id, task_id, worker_id, instance_id, tenant_id, fencing_token, expires_at)
     )
     return WorkerLease(lease_token=token, ...)
     ```
     The generated `token` is returned in memory to the caller, but **never persisted to the database**!

   - In `verify_lease` (line ~905):
     ```python
     cur.execute(
         "SELECT lease_token, fencing_token, expires_at FROM process_worker_leases WHERE task_id = %s",
         (task_id,),
     )
     ```
     The SQL query queries a column `lease_token` that does not exist in the PostgreSQL schema.

3. **Why Unit & Acceptance Tests Missed It:**
   - In `tests/unit/`, mocks or SQLite were used for storage testing.
   - In `tests/acceptance/`, in-memory execution engines were used.
   - In `tests/integration/test_phase16_2_persistence.py`, the only PostgreSQL test `test_process_crash_and_restart_recovery_postgres` asserted that an instance in `RUNNING` status was recovered upon restart; it **never called `engine.complete_task` or `storage.verify_lease` against PostgreSQL**!

### 3.3 Impact Assessment
Any distributed worker attempting to submit a completed task against a production PostgreSQL cluster will trigger an unhandled database exception (`UndefinedColumn`), resulting in task failure, indefinite retry loops, or orphaned leases.

---

## 4. Dissection of High Finding NEW-16.3-03: Multi-Party Approval Decision Loss

### 4.1 Defect Demonstration
When multiple approvers cast votes on an approval request, each decision is represented by an `ApprovalRecord(approver_id, decision, comment, decided_at)`.
- When an approval request is saved to PostgreSQL via `storage.save_approval(approval)`, the request row is updated in `process_approval_requests`.
- However, `storage.save_approval` **never inserts or updates individual records in `process_approval_decisions`**!
- When `storage.get_approval(approval_id)` is invoked after a service restart:
  ```python
  return ApprovalRequest(
      ...
      decisions=[], # Always returns empty list!
  )
  ```
- **Consequence:** If an approval requires a quorum of 3 managers, and 2 managers have already approved before a container restart, both prior approvals are permanently lost. The process remains deadlocked waiting for approvals that were already granted.

---

## 5. Dissection of High Finding NEW-16.3-04: Reconciliation Cascade Deletion

### 5.1 Defect Demonstration
In `migrations/016_enterprise_process.sql`:
```sql
CREATE TABLE IF NOT EXISTS process_reconciliation_records (
    record_id VARCHAR(64) PRIMARY KEY,
    transaction_id VARCHAR(64) NOT NULL REFERENCES process_saga_transactions(transaction_id) ON DELETE CASCADE,
    tenant_id VARCHAR(64) NOT NULL,
    ...
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```
`process_saga_transactions` references `process_instances(instance_id) ON DELETE CASCADE`.

When `storage.archive_completed_instances(cutoff_days=30)` executes, it deletes aged rows from `process_instances`.
Due to `ON DELETE CASCADE`, PostgreSQL automatically deletes:
1. `process_instances`
2. `process_saga_transactions`
3. `process_reconciliation_records`

**Impact:** Unresolved manual reconciliation records (e.g., an uncompensated wire transfer or ERP write that failed and requires human intervention) are permanently deleted from the database without trace, destroying enterprise financial auditability.

---

## 6. Audit Verdict on PostgreSQL Persistence

While basic table creation and simple instance roundtrips succeed, **PostgreSQL persistence cannot be certified for production deployment**. Critical worker lease operations crash deterministically on schema mismatch, approval quorum state is dropped on reload, and data retention queries cascade into active financial reconciliation queues.
