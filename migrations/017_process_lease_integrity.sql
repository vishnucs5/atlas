-- Migration 017: Process Worker Lease Integrity & Reconciliation Preservation
-- Purpose: Remediate Phase 16.3 findings NEW-16.3-01 (lease_token) and NEW-16.3-04 (reconciliation cascade).

-- 1. Add lease_token column to process_worker_leases
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'process_worker_leases' AND column_name = 'lease_token'
    ) THEN
        ALTER TABLE process_worker_leases ADD COLUMN lease_token VARCHAR(64);
        UPDATE process_worker_leases SET lease_token = lease_id WHERE lease_token IS NULL;
        ALTER TABLE process_worker_leases ALTER COLUMN lease_token SET NOT NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_worker_leases_token ON process_worker_leases(lease_token);
CREATE INDEX IF NOT EXISTS idx_worker_leases_task_token ON process_worker_leases(task_instance_id, lease_token);

-- 2. Prevent cascade deletion of pending reconciliation records
-- Drop the ON DELETE CASCADE constraint and replace with ON DELETE RESTRICT
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'process_reconciliation_records_saga_id_fkey'
    ) THEN
        ALTER TABLE process_reconciliation_records DROP CONSTRAINT process_reconciliation_records_saga_id_fkey;
        ALTER TABLE process_reconciliation_records ADD CONSTRAINT process_reconciliation_records_saga_id_fkey
            FOREIGN KEY (saga_id) REFERENCES process_saga_transactions(saga_id) ON DELETE RESTRICT;
    END IF;
END $$;

-- 3. Add index on reconciliation status to support fast unresolved queries
CREATE INDEX IF NOT EXISTS idx_reconciliation_status ON process_reconciliation_records(status);

-- 4. Event Inbox deduplication index
CREATE INDEX IF NOT EXISTS idx_event_inbox_tenant_event ON process_event_inbox(tenant_id, event_id);

-- 5. Preserve saga transactions and reconciliation history across process instance archival
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'process_saga_transactions_process_instance_id_fkey'
    ) THEN
        ALTER TABLE process_saga_transactions ALTER COLUMN process_instance_id DROP NOT NULL;
        ALTER TABLE process_saga_transactions DROP CONSTRAINT process_saga_transactions_process_instance_id_fkey;
        ALTER TABLE process_saga_transactions ADD CONSTRAINT process_saga_transactions_process_instance_id_fkey
            FOREIGN KEY (process_instance_id) REFERENCES process_instances(instance_id) ON DELETE SET NULL;
    END IF;
END $$;
