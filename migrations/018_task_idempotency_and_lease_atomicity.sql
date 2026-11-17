-- Migration 018: Task Operation Idempotency & Distributed Lease Atomicity
-- Purpose: Remediate Phase 16.5 findings FINDING-16.5-02 (durable task idempotency) and FINDING-16.5-03 (lease race).

-- 1. Create process_operation_idempotency table
CREATE TABLE IF NOT EXISTS process_operation_idempotency (
    tenant_id VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    process_instance_id VARCHAR(64) NOT NULL,
    task_def_id VARCHAR(64) NOT NULL,
    operation_name VARCHAR(128) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'CREATED',
    provider_idempotency_key VARCHAR(128),
    provider_name VARCHAR(64),
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload JSONB,
    error_message TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    completed_at DOUBLE PRECISION,
    expires_at DOUBLE PRECISION,
    PRIMARY KEY (tenant_id, idempotency_key),
    CONSTRAINT fk_operation_idempotency_instance
        FOREIGN KEY (process_instance_id) REFERENCES process_instances(instance_id) ON DELETE CASCADE
);

-- 2. Indexes for fast lookup by instance/task and status
CREATE INDEX IF NOT EXISTS idx_operation_idempotency_instance_task
    ON process_operation_idempotency (tenant_id, process_instance_id, task_def_id);

CREATE INDEX IF NOT EXISTS idx_operation_idempotency_status
    ON process_operation_idempotency (status);

CREATE INDEX IF NOT EXISTS idx_operation_idempotency_provider_key
    ON process_operation_idempotency (tenant_id, provider_idempotency_key);

-- 3. Enhance worker leases table with index for returning conflict resolution
CREATE INDEX IF NOT EXISTS idx_worker_leases_conflict_target
    ON process_worker_leases (task_instance_id, fencing_token);
