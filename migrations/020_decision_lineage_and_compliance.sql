-- Migration 020: Causal Decision Lineage, In-Flight Steering & Compliance Proofs
-- Purpose: Relational schema for Phase 17 explainability Merkle trees, child idempotency steering, and regulatory compliance evidence.

-- 1. Causal Decision Lineage & Explainability
CREATE TABLE IF NOT EXISTS process_decision_lineage (
    decision_id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    agent_id VARCHAR(64) NOT NULL,
    task_instance_id VARCHAR(64) NOT NULL,
    selected_action VARCHAR(255) NOT NULL,
    rationale TEXT NOT NULL,
    factors JSONB NOT NULL DEFAULT '[]'::jsonb,
    policy_checks_passed JSONB NOT NULL DEFAULT '[]'::jsonb,
    merkle_root_hash VARCHAR(64) NOT NULL,
    cas_artifact_uri VARCHAR(255),
    timestamp DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decision_lineage_tenant_task 
    ON process_decision_lineage(tenant_id, task_instance_id);

CREATE INDEX IF NOT EXISTS idx_decision_lineage_merkle 
    ON process_decision_lineage(merkle_root_hash);

-- 2. In-Flight Human Steering Events & Child Idempotency Tracing
CREATE TABLE IF NOT EXISTS process_steering_events (
    steering_id VARCHAR(64) PRIMARY KEY,
    workspace_id VARCHAR(64) NOT NULL,
    operator_id VARCHAR(128) NOT NULL,
    parent_operation_key VARCHAR(128) NOT NULL,
    child_operation_key VARCHAR(128) NOT NULL,
    original_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    modified_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL,
    timestamp DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_steering_events_workspace 
    ON process_steering_events(workspace_id);

CREATE INDEX IF NOT EXISTS idx_steering_events_keys 
    ON process_steering_events(parent_operation_key, child_operation_key);

-- 3. Verifiable Compliance Evidence Bundles
CREATE TABLE IF NOT EXISTS process_compliance_proofs (
    bundle_id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    workspace_id VARCHAR(64) NOT NULL,
    frameworks JSONB NOT NULL DEFAULT '[]'::jsonb,
    decision_merkle_root VARCHAR(64) NOT NULL,
    hmac_signature VARCHAR(128) NOT NULL,
    total_decisions INTEGER NOT NULL DEFAULT 0,
    generated_at DOUBLE PRECISION NOT NULL,
    audit_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_compliance_proofs_workspace 
    ON process_compliance_proofs(workspace_id);

CREATE INDEX IF NOT EXISTS idx_compliance_proofs_tenant 
    ON process_compliance_proofs(tenant_id);
