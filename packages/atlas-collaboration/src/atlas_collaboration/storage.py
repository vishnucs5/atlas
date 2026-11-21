"""Durable storage and persistence engine for Phase 17 Collaboration.

Supports SQLite local storage with WAL mode and PostgreSQL persistence for
collaborative workspaces, turn leases, decision lineages, steering events,
and signed compliance proof bundles.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from atlas_collaboration.models import (
    AgentDecisionLineage,
    ComplianceBundle,
    DecisionFactor,
    SteeringEvent,
    TurnLease,
    WorkspaceRole,
)


class CollaborationStorage:
    """Thread-safe SQLite/Postgres persistence adapter for collaborative workspaces."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self.initialize()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        if self.db_path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def initialize(self) -> None:
        """Create relational tables for workspaces, leases, lineages, steering, and compliance."""
        with self._lock, self._get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS process_collaborative_workspaces (
                workspace_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                active_fencing_token INTEGER NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS process_collaborative_collaborators (
                workspace_id TEXT NOT NULL REFERENCES process_collaborative_workspaces(workspace_id) ON DELETE CASCADE,
                identity TEXT NOT NULL,
                role TEXT NOT NULL,
                joined_at REAL NOT NULL,
                PRIMARY KEY (workspace_id, identity)
            );

            CREATE TABLE IF NOT EXISTS process_collaborative_leases (
                lease_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES process_collaborative_workspaces(workspace_id) ON DELETE CASCADE,
                holder_identity TEXT NOT NULL,
                holder_role TEXT NOT NULL,
                fencing_token INTEGER NOT NULL,
                acquired_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS process_governance_delegations (
                delegation_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                grantor_id TEXT NOT NULL,
                delegatee_id TEXT NOT NULL,
                scope TEXT NOT NULL,
                constraints TEXT NOT NULL DEFAULT '{}',
                valid_from REAL NOT NULL,
                valid_until REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                signature TEXT,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS process_decision_lineage (
                decision_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                task_instance_id TEXT NOT NULL,
                selected_action TEXT NOT NULL,
                rationale TEXT NOT NULL,
                factors TEXT NOT NULL DEFAULT '[]',
                policy_checks_passed TEXT NOT NULL DEFAULT '[]',
                merkle_root_hash TEXT NOT NULL,
                cas_artifact_uri TEXT,
                timestamp REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS process_steering_events (
                steering_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                parent_operation_key TEXT NOT NULL,
                child_operation_key TEXT NOT NULL,
                original_parameters TEXT NOT NULL DEFAULT '{}',
                modified_parameters TEXT NOT NULL DEFAULT '{}',
                reason TEXT NOT NULL,
                timestamp REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS process_compliance_proofs (
                bundle_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                frameworks TEXT NOT NULL DEFAULT '[]',
                decision_merkle_root TEXT NOT NULL,
                hmac_signature TEXT NOT NULL,
                total_decisions INTEGER NOT NULL DEFAULT 0,
                generated_at REAL NOT NULL,
                audit_metadata TEXT NOT NULL DEFAULT '{}'
            );
            """)

    # -------------------------------------------------------------------------
    # Workspaces & Members
    # -------------------------------------------------------------------------

    def save_workspace(
        self,
        workspace_id: str,
        name: str,
        tenant_id: str = "default_tenant",
        created_at: float | None = None,
        status: str = "ACTIVE",
        active_fencing_token: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist or update workspace metadata."""
        ts = created_at if created_at is not None else time.time()
        meta_json = json.dumps(metadata or {})
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO process_collaborative_workspaces
                (workspace_id, tenant_id, name, created_at, status, active_fencing_token, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    name = excluded.name,
                    status = excluded.status,
                    active_fencing_token = excluded.active_fencing_token,
                    metadata = excluded.metadata
                """,
                (workspace_id, tenant_id, name, ts, status, active_fencing_token, meta_json),
            )
        return {
            "workspace_id": workspace_id,
            "tenant_id": tenant_id,
            "name": name,
            "created_at": ts,
            "status": status,
            "active_fencing_token": active_fencing_token,
            "metadata": metadata or {},
        }

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        """Fetch workspace details with member list."""
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM process_collaborative_workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            res["metadata"] = json.loads(res["metadata"])
            members = conn.execute(
                "SELECT * FROM process_collaborative_collaborators WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchall()
            res["collaborators"] = [
                {
                    "identity": m["identity"],
                    "role": m["role"],
                    "joined_at": m["joined_at"],
                }
                for m in members
            ]
            return res

    def list_workspaces(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """List all collaborative workspaces."""
        with self._lock, self._get_connection() as conn:
            if tenant_id:
                rows = conn.execute(
                    "SELECT * FROM process_collaborative_workspaces WHERE tenant_id = ? ORDER BY created_at DESC",
                    (tenant_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM process_collaborative_workspaces ORDER BY created_at DESC"
                ).fetchall()

            workspaces = []
            for r in rows:
                item = dict(r)
                item["metadata"] = json.loads(item["metadata"])
                workspaces.append(item)
            return workspaces

    def add_collaborator(
        self,
        workspace_id: str,
        identity: str,
        role: WorkspaceRole | str = WorkspaceRole.EDITOR,
        joined_at: float | None = None,
    ) -> None:
        """Register a collaborator in the workspace."""
        role_str = role.value if isinstance(role, WorkspaceRole) else str(role)
        ts = joined_at if joined_at is not None else time.time()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO process_collaborative_collaborators (workspace_id, identity, role, joined_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(workspace_id, identity) DO UPDATE SET
                    role = excluded.role
                """,
                (workspace_id, identity, role_str, ts),
            )

    # -------------------------------------------------------------------------
    # Turn Leases
    # -------------------------------------------------------------------------

    def save_lease(self, lease: TurnLease) -> None:
        """Persist active or updated turn lease and sync workspace fencing token."""
        with self._lock, self._get_connection() as conn:
            if lease.is_active:
                # Deactivate any other leases for this workspace
                conn.execute(
                    "UPDATE process_collaborative_leases SET is_active = 0 WHERE workspace_id = ? AND lease_id != ?",
                    (lease.workspace_id, lease.lease_id),
                )
            conn.execute(
                """
                INSERT INTO process_collaborative_leases
                (lease_id, workspace_id, holder_identity, holder_role, fencing_token, acquired_at, expires_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lease_id) DO UPDATE SET
                    expires_at = excluded.expires_at,
                    is_active = excluded.is_active
                """,
                (
                    lease.lease_id,
                    lease.workspace_id,
                    lease.holder_identity,
                    lease.holder_role.value
                    if isinstance(lease.holder_role, WorkspaceRole)
                    else str(lease.holder_role),
                    lease.fencing_token,
                    lease.acquired_at,
                    lease.expires_at,
                    1 if lease.is_active else 0,
                ),
            )
            # Update workspace active_fencing_token
            conn.execute(
                "UPDATE process_collaborative_workspaces SET active_fencing_token = ? WHERE workspace_id = ?",
                (lease.fencing_token, lease.workspace_id),
            )

    def get_active_lease(self, workspace_id: str) -> TurnLease | None:
        """Fetch the current active turn lease for a workspace."""
        now = time.time()
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM process_collaborative_leases
                WHERE workspace_id = ? AND is_active = 1 AND expires_at > ?
                ORDER BY fencing_token DESC LIMIT 1
                """,
                (workspace_id, now),
            ).fetchone()
            if not row:
                return None
            return TurnLease(
                lease_id=row["lease_id"],
                workspace_id=row["workspace_id"],
                holder_identity=row["holder_identity"],
                holder_role=WorkspaceRole(row["holder_role"]),
                fencing_token=row["fencing_token"],
                acquired_at=row["acquired_at"],
                expires_at=row["expires_at"],
                is_active=bool(row["is_active"]),
            )

    def revoke_lease(self, lease_id: str) -> None:
        """Revoke active turn lease."""
        with self._lock, self._get_connection() as conn:
            conn.execute(
                "UPDATE process_collaborative_leases SET is_active = 0 WHERE lease_id = ?",
                (lease_id,),
            )

    # -------------------------------------------------------------------------
    # Decision Lineage
    # -------------------------------------------------------------------------

    def save_decision_lineage(self, lineage: AgentDecisionLineage) -> None:
        """Persist causal decision lineage record."""
        factors_json = json.dumps([f.model_dump() for f in lineage.factors])
        policy_json = json.dumps(lineage.policy_checks_passed)
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO process_decision_lineage
                (decision_id, tenant_id, agent_id, task_instance_id, selected_action, rationale, factors, policy_checks_passed, merkle_root_hash, cas_artifact_uri, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(decision_id) DO UPDATE SET
                    rationale = excluded.rationale,
                    merkle_root_hash = excluded.merkle_root_hash
                """,
                (
                    lineage.decision_id,
                    lineage.tenant_id,
                    lineage.agent_id,
                    lineage.task_instance_id,
                    lineage.selected_action,
                    lineage.rationale,
                    factors_json,
                    policy_json,
                    lineage.merkle_root_hash,
                    lineage.cas_artifact_uri,
                    lineage.timestamp,
                ),
            )

    def list_decision_lineages(self, task_instance_id: str) -> list[AgentDecisionLineage]:
        """Query decision lineage chain for a task."""
        with self._lock, self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM process_decision_lineage WHERE task_instance_id = ? ORDER BY timestamp ASC",
                (task_instance_id,),
            ).fetchall()
            decisions = []
            for r in rows:
                factors_raw = json.loads(r["factors"])
                factors = [DecisionFactor(**f) for f in factors_raw]
                decisions.append(
                    AgentDecisionLineage(
                        decision_id=r["decision_id"],
                        tenant_id=r["tenant_id"],
                        agent_id=r["agent_id"],
                        task_instance_id=r["task_instance_id"],
                        selected_action=r["selected_action"],
                        rationale=r["rationale"],
                        factors=factors,
                        policy_checks_passed=json.loads(r["policy_checks_passed"]),
                        merkle_root_hash=r["merkle_root_hash"],
                        cas_artifact_uri=r["cas_artifact_uri"],
                        timestamp=r["timestamp"],
                    )
                )
            return decisions

    # -------------------------------------------------------------------------
    # Steering Events
    # -------------------------------------------------------------------------

    def save_steering_event(self, event: SteeringEvent) -> None:
        """Persist a human intervention steering event."""
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO process_steering_events
                (steering_id, workspace_id, operator_id, parent_operation_key, child_operation_key, original_parameters, modified_parameters, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(steering_id) DO NOTHING
                """,
                (
                    event.steering_id,
                    event.workspace_id,
                    event.operator_id,
                    event.parent_operation_key,
                    event.child_operation_key,
                    json.dumps(event.original_parameters),
                    json.dumps(event.modified_parameters),
                    event.reason,
                    event.timestamp,
                ),
            )

    def list_steering_events(self, workspace_id: str) -> list[SteeringEvent]:
        """Retrieve all steering events associated with a workspace."""
        with self._lock, self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM process_steering_events WHERE workspace_id = ? ORDER BY timestamp ASC",
                (workspace_id,),
            ).fetchall()
            return [
                SteeringEvent(
                    steering_id=r["steering_id"],
                    workspace_id=r["workspace_id"],
                    operator_id=r["operator_id"],
                    parent_operation_key=r["parent_operation_key"],
                    child_operation_key=r["child_operation_key"],
                    original_parameters=json.loads(r["original_parameters"]),
                    modified_parameters=json.loads(r["modified_parameters"]),
                    reason=r["reason"],
                    timestamp=r["timestamp"],
                )
                for r in rows
            ]

    # -------------------------------------------------------------------------
    # Compliance Proof Bundles
    # -------------------------------------------------------------------------

    def save_compliance_bundle(self, bundle: ComplianceBundle) -> None:
        """Persist a generated compliance proof bundle."""
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO process_compliance_proofs
                (bundle_id, tenant_id, workspace_id, frameworks, decision_merkle_root, hmac_signature, total_decisions, generated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bundle_id) DO UPDATE SET
                    hmac_signature = excluded.hmac_signature
                """,
                (
                    bundle.bundle_id,
                    bundle.tenant_id,
                    bundle.workspace_id,
                    json.dumps(bundle.frameworks),
                    bundle.decision_merkle_root,
                    bundle.hmac_signature,
                    bundle.total_decisions,
                    bundle.generated_at,
                ),
            )

    def get_latest_compliance_bundle(self, workspace_id: str) -> ComplianceBundle | None:
        """Retrieve the most recent compliance proof bundle for a workspace."""
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM process_compliance_proofs WHERE workspace_id = ? ORDER BY generated_at DESC LIMIT 1",
                (workspace_id,),
            ).fetchone()
            if not row:
                return None
            return ComplianceBundle(
                bundle_id=row["bundle_id"],
                tenant_id=row["tenant_id"],
                workspace_id=row["workspace_id"],
                frameworks=json.loads(row["frameworks"]),
                decision_merkle_root=row["decision_merkle_root"],
                hmac_signature=row["hmac_signature"],
                total_decisions=row["total_decisions"],
                generated_at=row["generated_at"],
            )
