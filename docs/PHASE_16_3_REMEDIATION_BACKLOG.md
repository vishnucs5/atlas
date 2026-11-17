# ATLAS Phase 16.3 Independent Audit: Engineering Remediation Backlog

**Audit Target Branch:** `feat/phase-16-2-remediation`  
**Base Commit:** `88d077405dfe8e53eb9708434c594993b9ce96e0`  
**Audit Date:** November 17, 2026  
**Auditor:** ATLAS Independent Audit Team (Phase 16.3)  
**Status:** Actionable Specifications for Engineering Remediation

---

## 1. Overview

This engineering backlog provides precise technical instructions, code paths, and database migrations required to resolve the 9 findings identified during the Phase 16.3 independent audit before Phase 16 can be certified for enterprise pilot deployment.

---

## 2. Priority 1: Critical Production Blockers

### Item 1: Fix PostgreSQL `process_worker_leases` Schema Mismatch (NEW-16.3-01)
- **Target Files:**
  - `migrations/017_fix_worker_lease_token.sql` (New Migration)
  - `packages/atlas-process/src/atlas_process/storage.py`
  - `tests/integration/test_phase16_2_persistence.py`
- **Actions Required:**
  1. Author migration `017_fix_worker_lease_token.sql`:
     ```sql
     ALTER TABLE process_worker_leases ADD COLUMN IF NOT EXISTS lease_token VARCHAR(64);
     UPDATE process_worker_leases SET lease_token = lease_id WHERE lease_token IS NULL;
     ALTER TABLE process_worker_leases ALTER COLUMN lease_token SET NOT NULL;
     CREATE INDEX IF NOT EXISTS idx_worker_leases_token ON process_worker_leases(lease_token);
     ```
  2. In `PostgresProcessStorage.record_lease()` (`storage.py:880`):
     - Update the `INSERT INTO process_worker_leases` statement to include `lease_token`.
     - Pass `token` into both the SQL parameter tuple and the return `WorkerLease`.
  3. In `tests/integration/test_phase16_2_persistence.py`:
     - Add `test_postgres_worker_lease_complete_task_lifecycle` executing lease acquisition, lease verification, and `complete_task` on native PostgreSQL.

### Item 2: Implement Durable Saga & Reconciliation Storage (NEW-16.3-02)
- **Target Files:**
  - `packages/atlas-process/src/atlas_process/transactions.py`
  - `packages/atlas-process/src/atlas_process/storage.py`
  - `tests/unit/test_phase16_2_transactions.py`
- **Actions Required:**
  1. In `SagaCoordinator.__init__(self, storage: ProcessStorage | None = None)`:
     - Accept an optional `storage` engine reference.
  2. In `PostgresProcessStorage.save_saga()`:
     - Iterate through `saga.steps` and perform upserts on `process_saga_steps` table (recording `step_id`, `step_name`, `status`, `compensation_action`, `output`).
  3. In `PostgresProcessStorage.get_saga()`:
     - Query `process_saga_steps WHERE transaction_id = %s ORDER BY sequence_number ASC` to reconstruct full step history.
  4. In `SagaCoordinator.record_reconciliation()`:
     - When compensation fails, immediately invoke `self.storage.record_reconciliation(record)` to persist the item to `process_reconciliation_records` before returning.

---

## 3. Priority 2: High Severity Integrity & Security Deficiencies

### Item 3: Persist Multi-Party Approval Decisions on PostgreSQL (NEW-16.3-03)
- **Target Files:**
  - `packages/atlas-process/src/atlas_process/storage.py`
  - `packages/atlas-process/src/atlas_process/approvals.py`
- **Actions Required:**
  1. In `PostgresProcessStorage.save_approval()`:
     - Insert or update each `ApprovalRecord` from `approval.decisions` into `process_approval_decisions` (`decision_id`, `request_id`, `approver_id`, `decision`, `comment`, `decided_at`).
  2. In `PostgresProcessStorage.get_approval()`:
     - Query `process_approval_decisions WHERE request_id = %s` and populate `decisions: list[ApprovalRecord]`.
  3. In `HumanApprovalEngine`:
     - Introduce an `asyncio.Lock` or database row-level lock (`SELECT ... FOR UPDATE`) in `submit_decision` to prevent race conditions during concurrent voting.

### Item 4: Sever Cascade Deletion of Unresolved Reconciliation Records (NEW-16.3-04)
- **Target Files:**
  - `migrations/017_sever_reconciliation_cascade.sql`
- **Actions Required:**
  1. Modify foreign key relationship on `process_reconciliation_records`:
     ```sql
     ALTER TABLE process_reconciliation_records DROP CONSTRAINT IF EXISTS process_reconciliation_records_transaction_id_fkey;
     ALTER TABLE process_reconciliation_records ADD CONSTRAINT process_reconciliation_records_transaction_id_fkey
         FOREIGN KEY (transaction_id) REFERENCES process_saga_transactions(transaction_id) ON DELETE RESTRICT;
     ```
  2. In `PostgresProcessStorage.archive_completed_instances()`:
     - Explicitly verify that no pending/unresolved reconciliation records reference the instances being purged:
       `WHERE status NOT IN ('RECONCILED', 'DISMISSED')`.

### Item 5: Prevent Webhook Replay Attacks via Deterministic Event Hashing (NEW-16.3-05)
- **Target Files:**
  - `packages/atlas-process/src/atlas_process/triggers.py`
  - `tests/unit/test_phase16_2_triggers.py`
- **Actions Required:**
  1. In `WebhookTriggerHandler.verify_webhook()`:
     - Replace `event_id=str(uuid.uuid4())` with a deterministic hash:
       ```python
       idempotency_key = hashlib.sha256(
           f"{tenant_id}:{webhook_id}:{timestamp_str}:{payload.decode('utf-8', errors='ignore')}".encode()
       ).hexdigest()
       ```
     - Pass `event_id=idempotency_key` into `ProcessEvent`.
  2. Add unit test verifying that submitting the identical webhook payload and signature a second time within the validity window is rejected with `DuplicateEventError` or 409 Conflict.

---

## 4. Priority 3: Medium Severity Performance & Safety Improvements

### Item 6: Convert `HttpEnterpriseConnector` to Non-Blocking Async Transport (NEW-16.3-06)
- **Target Files:**
  - `packages/atlas-process/src/atlas_process/connectors.py`
- **Actions Required:**
  1. Refactor `HttpEnterpriseConnector.invoke()` to `async def invoke()`:
     - Replace `httpx.Client()` with `httpx.AsyncClient()`.
     - Replace `time.sleep()` with `await asyncio.sleep()`.
  2. Ensure all upstream caller paths in `atlas_process.engine` await the connector invocation.

### Item 7: Add SSRF Guardrails to Enterprise HTTP Connectors (NEW-16.3-07)
- **Target Files:**
  - `packages/atlas-process/src/atlas_process/connectors.py`
- **Actions Required:**
  1. Implement IP sanitization before issuing requests:
     - Parse host from URL.
     - Resolve DNS to IP addresses.
     - Reject requests if IP falls within private or reserved ranges:
       - Loopback (`127.0.0.0/8`, `::1`)
       - RFC 1918 Private (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`)
       - Link-Local / Cloud Metadata (`169.254.0.0/16`)

---

## 5. Priority 4: Code Quality & Repository Hygiene

### Item 8: Resolve Mypy Type Checking Errors (NEW-16.3-09)
- **Target Files:**
  - `packages/atlas-process/src/atlas_process/evaluator.py`
  - `packages/atlas-process/src/atlas_process/storage.py`
- **Actions Required:**
  1. In `evaluator.py`: Correct type annotations for comparator and boolean operator lookup tables. Add internal helper `_eval_node(node: ast.AST)` separate from `evaluate(expression: str)`.
  2. In `storage.py`: Add `is not None` guards before accessing `.status` and filter list comprehensions to exclude `None`.

### Item 9: Formalize Git Commit on Remediation Branch (NEW-16.3-08)
- **Actions Required:**
  1. Verify working tree is clean of scratch files.
  2. Stage modified files and new Phase 16.2 source and test files.
  3. Create atomic commit with descriptive summary referencing Phase 16.2 and Phase 16.3 audit.
