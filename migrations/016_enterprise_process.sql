-- ATLAS Phase 16.2: Autonomous Enterprise Process Execution & Digital Workforce Platform
-- Relational Schema & Durable Persistence Migration for PostgreSQL 16+

-- 1. Process Definitions
CREATE TABLE IF NOT EXISTS process_definitions (
    definition_id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    version VARCHAR(32) NOT NULL DEFAULT '1.0',
    status VARCHAR(32) NOT NULL DEFAULT 'VALIDATED',
    tasks_schema JSONB NOT NULL DEFAULT '[]'::jsonb,
    definition_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_proc_defs_tenant ON process_definitions(tenant_id);

-- 2. Process Definition Versions
CREATE TABLE IF NOT EXISTS process_definition_versions (
    id BIGSERIAL PRIMARY KEY,
    definition_id VARCHAR(64) NOT NULL REFERENCES process_definitions(definition_id) ON DELETE CASCADE,
    version VARCHAR(32) NOT NULL,
    definition_hash VARCHAR(64) NOT NULL,
    tasks_schema JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (definition_id, version)
);

-- 3. Process Instances
CREATE TABLE IF NOT EXISTS process_instances (
    instance_id VARCHAR(64) PRIMARY KEY,
    definition_id VARCHAR(64) NOT NULL REFERENCES process_definitions(definition_id),
    definition_version VARCHAR(32) NOT NULL,
    definition_hash VARCHAR(64) NOT NULL,
    tenant_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    variables JSONB NOT NULL DEFAULT '{}'::jsonb,
    checkpoint_version INTEGER NOT NULL DEFAULT 0,
    idempotency_key VARCHAR(128),
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    completed_at DOUBLE PRECISION,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_proc_inst_tenant_status ON process_instances(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_proc_inst_idem ON process_instances(tenant_id, idempotency_key);

-- 4. Process Task Instances
CREATE TABLE IF NOT EXISTS process_task_instances (
    task_instance_id VARCHAR(64) PRIMARY KEY,
    process_instance_id VARCHAR(64) NOT NULL REFERENCES process_instances(instance_id) ON DELETE CASCADE,
    task_def_id VARCHAR(64) NOT NULL,
    task_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    assigned_to VARCHAR(64),
    inputs JSONB NOT NULL DEFAULT '{}'::jsonb,
    outputs JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    lease_token VARCHAR(64),
    lease_fencing_token BIGINT NOT NULL DEFAULT 0,
    lease_expires_at DOUBLE PRECISION,
    retry_count INTEGER NOT NULL DEFAULT 0,
    started_at DOUBLE PRECISION,
    completed_at DOUBLE PRECISION,
    idempotency_key VARCHAR(128)
);
CREATE INDEX IF NOT EXISTS idx_proc_task_inst_process ON process_task_instances(process_instance_id);

-- 5. Process Execution Events (Append-only audit stream)
CREATE TABLE IF NOT EXISTS process_execution_events (
    event_id VARCHAR(64) PRIMARY KEY,
    process_instance_id VARCHAR(64) NOT NULL REFERENCES process_instances(instance_id) ON DELETE CASCADE,
    task_instance_id VARCHAR(64),
    tenant_id VARCHAR(64) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    sequence BIGINT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    timestamp DOUBLE PRECISION NOT NULL,
    UNIQUE (process_instance_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_proc_events_instance ON process_execution_events(process_instance_id, sequence);

-- 6. Process Checkpoints
CREATE TABLE IF NOT EXISTS process_checkpoints (
    id BIGSERIAL PRIMARY KEY,
    instance_id VARCHAR(64) NOT NULL REFERENCES process_instances(instance_id) ON DELETE CASCADE,
    checkpoint_version INTEGER NOT NULL,
    fencing_token BIGINT NOT NULL DEFAULT 0,
    state_snapshot JSONB NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (instance_id, checkpoint_version)
);

-- 7. Worker Leases
CREATE TABLE IF NOT EXISTS process_worker_leases (
    lease_id VARCHAR(64) PRIMARY KEY,
    task_instance_id VARCHAR(64) NOT NULL REFERENCES process_task_instances(task_instance_id) ON DELETE CASCADE UNIQUE,
    process_instance_id VARCHAR(64) NOT NULL REFERENCES process_instances(instance_id) ON DELETE CASCADE,
    worker_id VARCHAR(64) NOT NULL,
    fencing_token BIGINT NOT NULL,
    status VARCHAR(32) NOT NULL,
    acquired_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_worker_leases_active ON process_worker_leases(task_instance_id, status);

-- 8. Idempotency Records
CREATE TABLE IF NOT EXISTS process_idempotency_records (
    idempotency_key VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(64) NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    response_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, idempotency_key)
);

-- 9. Human Approval Requests
CREATE TABLE IF NOT EXISTS process_approval_requests (
    approval_id VARCHAR(64) PRIMARY KEY,
    process_instance_id VARCHAR(64) NOT NULL REFERENCES process_instances(instance_id) ON DELETE CASCADE,
    task_def_id VARCHAR(64) NOT NULL,
    action_name VARCHAR(128) NOT NULL,
    target_resource VARCHAR(255) NOT NULL,
    parameters JSONB NOT NULL,
    parameter_hash VARCHAR(64) NOT NULL,
    requesting_identity VARCHAR(64) NOT NULL,
    allowed_approver_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_approver_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    required_approvals INTEGER NOT NULL DEFAULT 1,
    risk_classification VARCHAR(32) NOT NULL DEFAULT 'HIGH',
    status VARCHAR(32) NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    resolved_at DOUBLE PRECISION
);

-- 10. Human Approval Decisions
CREATE TABLE IF NOT EXISTS process_approval_decisions (
    id BIGSERIAL PRIMARY KEY,
    approval_id VARCHAR(64) NOT NULL REFERENCES process_approval_requests(approval_id) ON DELETE CASCADE,
    approver_id VARCHAR(64) NOT NULL,
    decision VARCHAR(32) NOT NULL,
    comments TEXT NOT NULL DEFAULT '',
    decided_at DOUBLE PRECISION NOT NULL,
    UNIQUE (approval_id, approver_id)
);

-- 11. Distributed Saga Transactions
CREATE TABLE IF NOT EXISTS process_saga_transactions (
    saga_id VARCHAR(64) PRIMARY KEY,
    process_instance_id VARCHAR(64) NOT NULL REFERENCES process_instances(instance_id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    completed_at DOUBLE PRECISION,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 12. Saga Steps
CREATE TABLE IF NOT EXISTS process_saga_steps (
    step_id VARCHAR(64) PRIMARY KEY,
    saga_id VARCHAR(64) NOT NULL REFERENCES process_saga_transactions(saga_id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    is_idempotent BOOLEAN NOT NULL DEFAULT FALSE,
    idempotency_key VARCHAR(128) NOT NULL,
    forward_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    forward_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    compensation_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    compensation_attempts INTEGER NOT NULL DEFAULT 0,
    compensation_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_message TEXT,
    executed_at DOUBLE PRECISION,
    compensated_at DOUBLE PRECISION
);

-- 13. Compensation Records
CREATE TABLE IF NOT EXISTS process_compensation_records (
    id BIGSERIAL PRIMARY KEY,
    saga_id VARCHAR(64) NOT NULL REFERENCES process_saga_transactions(saga_id) ON DELETE CASCADE,
    step_id VARCHAR(64) NOT NULL REFERENCES process_saga_steps(step_id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    timestamp DOUBLE PRECISION NOT NULL
);

-- 14. Reconciliation Records
CREATE TABLE IF NOT EXISTS process_reconciliation_records (
    id BIGSERIAL PRIMARY KEY,
    saga_id VARCHAR(64) NOT NULL REFERENCES process_saga_transactions(saga_id) ON DELETE CASCADE,
    step_id VARCHAR(64) NOT NULL REFERENCES process_saga_steps(step_id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    resolved_by VARCHAR(64),
    notes TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    resolved_at DOUBLE PRECISION
);

-- 15. Event Inbox and Outbox
CREATE TABLE IF NOT EXISTS process_event_inbox (
    event_id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    source VARCHAR(128) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'RECEIVED',
    received_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS process_event_outbox (
    event_id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    destination VARCHAR(128) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    created_at DOUBLE PRECISION NOT NULL,
    sent_at DOUBLE PRECISION
);
