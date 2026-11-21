-- Migration 019: Collaborative Workspaces & Dynamic Governance Delegations
-- Purpose: Relational schema for Phase 17 Human-AI Collaboration, semantic turn leases, and delegation envelopes.

-- 1. Collaborative Workspaces
CREATE TABLE IF NOT EXISTS process_collaborative_workspaces (
    workspace_id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    active_fencing_token INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_collab_workspaces_tenant 
    ON process_collaborative_workspaces(tenant_id, status);

-- 2. Collaborative Workspace Members
CREATE TABLE IF NOT EXISTS process_collaborative_collaborators (
    workspace_id VARCHAR(64) NOT NULL REFERENCES process_collaborative_workspaces(workspace_id) ON DELETE CASCADE,
    identity VARCHAR(128) NOT NULL,
    role VARCHAR(32) NOT NULL,
    joined_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (workspace_id, identity)
);

CREATE INDEX IF NOT EXISTS idx_collab_members_identity 
    ON process_collaborative_collaborators(identity);

-- 3. Semantic Turn Leases with Fencing Tokens
CREATE TABLE IF NOT EXISTS process_collaborative_leases (
    lease_id VARCHAR(64) PRIMARY KEY,
    workspace_id VARCHAR(64) NOT NULL REFERENCES process_collaborative_workspaces(workspace_id) ON DELETE CASCADE,
    holder_identity VARCHAR(128) NOT NULL,
    holder_role VARCHAR(32) NOT NULL,
    fencing_token INTEGER NOT NULL,
    acquired_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_collab_leases_workspace 
    ON process_collaborative_leases(workspace_id, is_active);

CREATE INDEX IF NOT EXISTS idx_collab_leases_fencing 
    ON process_collaborative_leases(workspace_id, fencing_token);

-- 4. Dynamic Policy & Authority Delegations
CREATE TABLE IF NOT EXISTS process_governance_delegations (
    delegation_id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    grantor_id VARCHAR(128) NOT NULL,
    delegatee_id VARCHAR(128) NOT NULL,
    scope VARCHAR(64) NOT NULL,
    constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    valid_from DOUBLE PRECISION NOT NULL,
    valid_until DOUBLE PRECISION NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    signature VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gov_delegations_tenant 
    ON process_governance_delegations(tenant_id, scope, revoked);

CREATE INDEX IF NOT EXISTS idx_gov_delegations_delegatee 
    ON process_governance_delegations(delegatee_id, valid_until);
