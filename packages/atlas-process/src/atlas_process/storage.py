"""Durable persistence layer for ATLAS Enterprise Process Execution.

Implements relational storage protocols, PostgreSQL connection-pooled repository,
SQLite embedded storage, WAL crash durability, fencing leases, and archival.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from atlas_process.engine import ProcessInstance

from atlas_process.approvals import ApprovalDecision, ApprovalRecord, ApprovalRequest
from atlas_process.definitions import (
    ProcessDefinition,
    ProcessDefinitionStatus,
    ProcessTaskDefinition,
    TaskType,
)
from atlas_process.state_machine import ProcessStatus, ProcessTaskStatus
from atlas_process.transactions import (
    SagaStatus,
    SagaStep,
    SagaStepStatus,
    SagaTransaction,
)


class StorageError(Exception):
    """Base exception for process storage failures."""


class LeaseExpiredError(StorageError):
    """Raised when an operation targets an expired task lease."""


class StaleWorkerError(StorageError):
    """Raised when a worker attempts a commit with a stale fencing token."""


class OptimisticLockError(StorageError):
    """Raised when concurrent mutation violates version or status checks."""


@runtime_checkable
class ProcessStorageProtocol(Protocol):
    """Protocol for reading and writing durable enterprise process state."""

    def initialize(self) -> None:
        """Initialize database schema, migrations, and tables."""
        ...

    def save_definition(self, definition: ProcessDefinition) -> None:
        """Persist or update a process definition."""
        ...

    def get_definition(self, definition_id: str) -> ProcessDefinition | None:
        """Retrieve a process definition by ID."""
        ...

    def save_instance(self, instance: ProcessInstance) -> None:
        """Atomically persist or update a process instance and its task states."""
        ...

    def get_instance(self, instance_id: str) -> ProcessInstance | None:
        """Retrieve a process instance by ID."""
        ...

    def list_instances(
        self,
        tenant_id: str | None = None,
        status: ProcessStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProcessInstance]:
        """Query process instances with pagination and filtering."""
        ...

    def save_checkpoint(
        self,
        instance_id: str,
        checkpoint_version: int,
        state_snapshot: dict[str, Any],
        fencing_token: int = 0,
    ) -> None:
        """Append an immutable versioned checkpoint."""
        ...

    def get_latest_checkpoint(self, instance_id: str) -> dict[str, Any] | None:
        """Retrieve the latest checkpoint for an instance."""
        ...

    def acquire_lease(
        self,
        task_instance_id: str,
        process_instance_id: str,
        worker_id: str,
        lease_duration_seconds: float = 60.0,
    ) -> tuple[str, int]:
        """Atomically acquire a lease and increment the monotonic fencing token."""
        ...

    def verify_lease(
        self,
        task_instance_id: str,
        lease_token: str,
        fencing_token: int,
    ) -> bool:
        """Validate lease validity and fencing token freshness."""
        ...

    def renew_lease(
        self,
        task_instance_id: str,
        lease_token: str,
        extension_seconds: float = 60.0,
    ) -> bool:
        """Renew active lease if token matches and has not expired."""
        ...

    def release_lease(
        self,
        task_instance_id: str,
        lease_token: str,
    ) -> bool:
        """Explicitly release lease before expiration."""
        ...

    def save_approval(self, approval: ApprovalRequest) -> None:
        """Persist human approval request and decisions."""
        ...

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        """Retrieve human approval request by ID."""
        ...

    def save_saga(self, saga: SagaTransaction) -> None:
        """Persist saga transaction state and steps."""
        ...

    def get_saga(self, saga_id: str) -> SagaTransaction | None:
        """Retrieve saga transaction by ID."""
        ...

    def record_reconciliation(
        self,
        saga_id: str,
        step_id: str,
        reason: str,
        notes: str = "",
    ) -> int:
        """Persist a manual reconciliation record."""
        ...

    def list_reconciliations(
        self,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List reconciliation records filtered by status."""
        ...

    def resolve_reconciliation(
        self,
        record_id: int | str,
        resolved_by: str,
        notes: str = "",
    ) -> bool:
        """Mark a reconciliation record as resolved."""
        ...

    def record_event_inbox(
        self,
        event_id: str,
        tenant_id: str,
        source: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> bool:
        """Persist incoming event for idempotent deduplication."""
        ...

    def has_event_inbox(self, tenant_id: str, event_id: str) -> bool:
        """Check whether an event has already been ingested."""
        ...

    def archive_completed_instances(
        self,
        cutoff_timestamp: float,
        tenant_id: str | None = None,
    ) -> int:
        """Archive or purge completed/failed instances older than cutoff."""
        ...

    def get_uncompleted_instances(self) -> list[ProcessInstance]:
        """Retrieve all active or recovering instances for crash recovery."""
        ...


class InMemoryProcessStorage:
    """In-memory storage implementation for high-speed unit tests."""

    def __init__(self) -> None:
        self._definitions: dict[str, ProcessDefinition] = {}
        self._instances: dict[str, ProcessInstance] = {}
        self._checkpoints: dict[str, list[dict[str, Any]]] = {}
        self._leases: dict[str, dict[str, Any]] = {}
        self._fencing_tokens: dict[str, int] = {}
        self._approvals: dict[str, ApprovalRequest] = {}
        self._sagas: dict[str, SagaTransaction] = {}
        self._reconciliations: dict[int, dict[str, Any]] = {}
        self._reconciliation_seq: int = 0
        self._event_inbox: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.RLock()

    def initialize(self) -> None:
        pass

    def save_definition(self, definition: ProcessDefinition) -> None:
        with self._lock:
            self._definitions[definition.definition_id] = definition

    def get_definition(self, definition_id: str) -> ProcessDefinition | None:
        with self._lock:
            return self._definitions.get(definition_id)

    def save_instance(self, instance: ProcessInstance) -> None:
        with self._lock:
            self._instances[instance.instance_id] = instance.model_copy(deep=True)

    def get_instance(self, instance_id: str) -> ProcessInstance | None:
        with self._lock:
            inst = self._instances.get(instance_id)
            return inst.model_copy(deep=True) if inst else None

    def list_instances(
        self,
        tenant_id: str | None = None,
        status: ProcessStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProcessInstance]:
        with self._lock:
            results = []
            for inst in self._instances.values():
                if tenant_id and inst.tenant_id != tenant_id:
                    continue
                if status and inst.status != status:
                    continue
                results.append(inst.model_copy(deep=True))
            # Sort by created_at desc
            results.sort(key=lambda x: x.created_at, reverse=True)
            return results[offset : offset + limit]

    def save_checkpoint(
        self,
        instance_id: str,
        checkpoint_version: int,
        state_snapshot: dict[str, Any],
        fencing_token: int = 0,
    ) -> None:
        with self._lock:
            history = self._checkpoints.setdefault(instance_id, [])
            history.append(
                {
                    "checkpoint_version": checkpoint_version,
                    "fencing_token": fencing_token,
                    "state": state_snapshot,
                    "created_at": time.time(),
                }
            )

    def get_latest_checkpoint(self, instance_id: str) -> dict[str, Any] | None:
        with self._lock:
            history = self._checkpoints.get(instance_id, [])
            return history[-1]["state"] if history else None

    def acquire_lease(
        self,
        task_instance_id: str,
        process_instance_id: str,
        worker_id: str,
        lease_duration_seconds: float = 60.0,
    ) -> tuple[str, int]:
        with self._lock:
            token = f"lease_{uuid.uuid4().hex[:12]}"
            current_fencing = self._fencing_tokens.get(task_instance_id, 0) + 1
            self._fencing_tokens[task_instance_id] = current_fencing
            now = time.time()
            self._leases[task_instance_id] = {
                "lease_token": token,
                "fencing_token": current_fencing,
                "worker_id": worker_id,
                "expires_at": now + lease_duration_seconds,
            }
            return token, current_fencing

    def verify_lease(
        self,
        task_instance_id: str,
        lease_token: str,
        fencing_token: int,
    ) -> bool:
        with self._lock:
            lease = self._leases.get(task_instance_id)
            if not lease:
                return False
            now = time.time()
            if now > lease["expires_at"]:
                return False
            if lease["lease_token"] != lease_token:
                return False
            if lease["fencing_token"] != fencing_token:
                return False
            return True

    def renew_lease(
        self,
        task_instance_id: str,
        lease_token: str,
        extension_seconds: float = 60.0,
    ) -> bool:
        with self._lock:
            lease = self._leases.get(task_instance_id)
            if not lease:
                return False
            now = time.time()
            if now > lease["expires_at"] or lease["lease_token"] != lease_token:
                return False
            lease["expires_at"] = now + extension_seconds
            return True

    def release_lease(
        self,
        task_instance_id: str,
        lease_token: str,
    ) -> bool:
        with self._lock:
            lease = self._leases.get(task_instance_id)
            if not lease or lease["lease_token"] != lease_token:
                return False
            lease["expires_at"] = 0.0
            lease["lease_token"] = ""
            return True

    def save_approval(self, approval: ApprovalRequest) -> None:
        with self._lock:
            self._approvals[approval.approval_id] = approval.model_copy(deep=True)

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        with self._lock:
            appr = self._approvals.get(approval_id)
            return appr.model_copy(deep=True) if appr else None

    def save_saga(self, saga: SagaTransaction) -> None:
        with self._lock:
            self._sagas[saga.saga_id] = saga.model_copy(deep=True)

    def get_saga(self, saga_id: str) -> SagaTransaction | None:
        with self._lock:
            saga = self._sagas.get(saga_id)
            return saga.model_copy(deep=True) if saga else None

    def record_reconciliation(
        self,
        saga_id: str,
        step_id: str,
        reason: str,
        notes: str = "",
    ) -> int:
        with self._lock:
            self._reconciliation_seq += 1
            rec_id = self._reconciliation_seq
            self._reconciliations[rec_id] = {
                "id": rec_id,
                "saga_id": saga_id,
                "step_id": step_id,
                "reason": reason,
                "status": "PENDING",
                "resolved_by": None,
                "notes": notes,
                "created_at": time.time(),
                "resolved_at": None,
            }
            return rec_id

    def list_reconciliations(
        self,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            recs = list(self._reconciliations.values())
            if status:
                recs = [r for r in recs if r.get("status") == status]
            recs.sort(key=lambda x: x.get("created_at", 0.0), reverse=True)
            return [dict(r) for r in recs]

    def resolve_reconciliation(
        self,
        record_id: int | str,
        resolved_by: str,
        notes: str = "",
    ) -> bool:
        with self._lock:
            rec = self._reconciliations.get(int(record_id))
            if not rec:
                return False
            rec["status"] = "RESOLVED"
            rec["resolved_by"] = resolved_by
            rec["notes"] = notes
            rec["resolved_at"] = time.time()
            return True

    def record_event_inbox(
        self,
        event_id: str,
        tenant_id: str,
        source: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> bool:
        with self._lock:
            key = (tenant_id, event_id)
            if key in self._event_inbox:
                return False
            self._event_inbox[key] = {
                "event_id": event_id,
                "tenant_id": tenant_id,
                "source": source,
                "event_type": event_type,
                "payload": payload,
                "received_at": time.time(),
            }
            return True

    def has_event_inbox(self, tenant_id: str, event_id: str) -> bool:
        with self._lock:
            return (tenant_id, event_id) in self._event_inbox

    def archive_completed_instances(
        self,
        cutoff_timestamp: float,
        tenant_id: str | None = None,
    ) -> int:
        with self._lock:
            to_remove = []
            for iid, inst in self._instances.items():
                if tenant_id and inst.tenant_id != tenant_id:
                    continue
                # Protection: Do not archive if any saga has pending reconciliation records
                has_pending_rec = False
                for rec in self._reconciliations.values():
                    if rec.get("status") == "PENDING":
                        saga = self._sagas.get(rec.get("saga_id", ""))
                        if saga and saga.process_instance_id == iid:
                            has_pending_rec = True
                            break
                if has_pending_rec:
                    continue
                if (
                    inst.status in (ProcessStatus.COMPLETED, ProcessStatus.FAILED)
                    and inst.completed_at
                    and inst.completed_at < cutoff_timestamp
                ):
                    to_remove.append(iid)
            for iid in to_remove:
                self._instances.pop(iid, None)
                self._checkpoints.pop(iid, None)
            return len(to_remove)

    def get_uncompleted_instances(self) -> list[ProcessInstance]:
        with self._lock:
            return [
                inst.model_copy(deep=True)
                for inst in self._instances.values()
                if inst.status in (ProcessStatus.RUNNING, ProcessStatus.SUSPENDED)
            ]


class SqliteProcessStorage:
    """Embedded SQLite storage engine providing full durability, WAL crash safety, and local ACID persistence."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self.initialize()

    @contextlib.contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS process_definitions (
                definition_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT '1.0',
                status TEXT NOT NULL DEFAULT 'VALIDATED',
                tasks_schema TEXT NOT NULL DEFAULT '[]',
                definition_hash TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS process_instances (
                instance_id TEXT PRIMARY KEY,
                definition_id TEXT NOT NULL,
                definition_version TEXT NOT NULL,
                definition_hash TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                status TEXT NOT NULL,
                variables TEXT NOT NULL DEFAULT '{}',
                checkpoint_version INTEGER NOT NULL DEFAULT 0,
                idempotency_key TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS process_task_instances (
                task_instance_id TEXT PRIMARY KEY,
                process_instance_id TEXT NOT NULL,
                task_def_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                assigned_to TEXT,
                inputs TEXT NOT NULL DEFAULT '{}',
                outputs TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                lease_token TEXT,
                lease_fencing_token INTEGER NOT NULL DEFAULT 0,
                lease_expires_at REAL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                started_at REAL,
                completed_at REAL,
                idempotency_key TEXT,
                FOREIGN KEY (process_instance_id) REFERENCES process_instances(instance_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS process_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id TEXT NOT NULL,
                checkpoint_version INTEGER NOT NULL,
                fencing_token INTEGER NOT NULL DEFAULT 0,
                state_snapshot TEXT NOT NULL,
                checksum TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE (instance_id, checkpoint_version)
            );

            CREATE TABLE IF NOT EXISTS process_worker_leases (
                task_instance_id TEXT PRIMARY KEY,
                process_instance_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                lease_token TEXT NOT NULL,
                fencing_token INTEGER NOT NULL,
                expires_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS process_approval_requests (
                approval_id TEXT PRIMARY KEY,
                process_instance_id TEXT NOT NULL,
                task_def_id TEXT NOT NULL,
                action_name TEXT NOT NULL,
                target_resource TEXT NOT NULL,
                parameters TEXT NOT NULL,
                parameter_hash TEXT NOT NULL,
                requesting_identity TEXT NOT NULL,
                allowed_approver_ids TEXT NOT NULL,
                allowed_approver_roles TEXT NOT NULL,
                required_approvals INTEGER NOT NULL DEFAULT 1,
                risk_classification TEXT NOT NULL DEFAULT 'HIGH',
                status TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL,
                resolved_at REAL,
                decisions_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS process_saga_transactions (
                saga_id TEXT PRIMARY KEY,
                process_instance_id TEXT NOT NULL,
                status TEXT NOT NULL,
                steps_json TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                completed_at REAL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS process_approval_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                approval_id TEXT NOT NULL,
                approver_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                comments TEXT NOT NULL DEFAULT '',
                decided_at REAL NOT NULL,
                UNIQUE (approval_id, approver_id)
            );

            CREATE TABLE IF NOT EXISTS process_reconciliation_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                saga_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                resolved_by TEXT,
                notes TEXT,
                created_at REAL NOT NULL,
                resolved_at REAL
            );

            CREATE TABLE IF NOT EXISTS process_event_inbox (
                event_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'RECEIVED',
                received_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_event_inbox_tenant ON process_event_inbox(tenant_id, event_id);
            """)

    def save_definition(self, definition: ProcessDefinition) -> None:
        with self._lock, self._get_connection() as conn:
            tasks_data = json.dumps([t.model_dump() for t in definition.tasks])
            now = time.time()
            conn.execute(
                """
                INSERT INTO process_definitions (
                    definition_id, tenant_id, name, version, status, tasks_schema, definition_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (definition_id) DO UPDATE SET
                    name = excluded.name,
                    version = excluded.version,
                    status = excluded.status,
                    tasks_schema = excluded.tasks_schema,
                    definition_hash = excluded.definition_hash,
                    updated_at = excluded.updated_at
                """,
                (
                    definition.definition_id,
                    definition.tenant_id,
                    definition.name,
                    definition.version,
                    definition.status.value,
                    tasks_data,
                    definition.definition_hash or definition.compute_hash(),
                    now,
                    now,
                ),
            )

    def get_definition(self, definition_id: str) -> ProcessDefinition | None:
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM process_definitions WHERE definition_id = ?", (definition_id,)
            ).fetchone()
            if not row:
                return None
            tasks_list = [ProcessTaskDefinition(**t) for t in json.loads(row["tasks_schema"])]
            return ProcessDefinition(
                definition_id=row["definition_id"],
                tenant_id=row["tenant_id"],
                name=row["name"],
                version=row["version"],
                status=ProcessDefinitionStatus(row["status"]),
                tasks=tasks_list,
                definition_hash=row["definition_hash"],
            )

    def save_instance(self, instance: ProcessInstance) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO process_instances (
                    instance_id, definition_id, definition_version, definition_hash, tenant_id,
                    status, variables, checkpoint_version, idempotency_key, created_at, updated_at,
                    completed_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (instance_id) DO UPDATE SET
                    status = excluded.status,
                    variables = excluded.variables,
                    checkpoint_version = excluded.checkpoint_version,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at,
                    error_message = excluded.error_message
                """,
                (
                    instance.instance_id,
                    instance.definition_id,
                    instance.definition_version,
                    instance.definition_hash,
                    instance.tenant_id,
                    instance.status.value,
                    json.dumps(instance.variables),
                    instance.checkpoint_version,
                    instance.idempotency_key,
                    instance.created_at,
                    instance.updated_at,
                    instance.completed_at,
                    instance.error_message,
                ),
            )

            # Upsert task instances
            for t_inst in instance.task_instances.values():
                conn.execute(
                    """
                    INSERT INTO process_task_instances (
                        task_instance_id, process_instance_id, task_def_id, task_type,
                        status, assigned_to, inputs, outputs, error, lease_token,
                        lease_fencing_token, lease_expires_at, retry_count, started_at,
                        completed_at, idempotency_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (task_instance_id) DO UPDATE SET
                        status = excluded.status,
                        assigned_to = excluded.assigned_to,
                        inputs = excluded.inputs,
                        outputs = excluded.outputs,
                        error = excluded.error,
                        lease_token = excluded.lease_token,
                        lease_fencing_token = excluded.lease_fencing_token,
                        lease_expires_at = excluded.lease_expires_at,
                        retry_count = excluded.retry_count,
                        started_at = excluded.started_at,
                        completed_at = excluded.completed_at
                    """,
                    (
                        t_inst.task_instance_id,
                        t_inst.process_instance_id,
                        t_inst.task_def_id,
                        t_inst.task_type.value,
                        t_inst.status.value,
                        t_inst.assigned_to,
                        json.dumps(t_inst.inputs),
                        json.dumps(t_inst.outputs),
                        t_inst.error,
                        t_inst.lease_token,
                        t_inst.lease_fencing_token,
                        t_inst.lease_expires_at,
                        t_inst.retry_count,
                        t_inst.started_at,
                        t_inst.completed_at,
                        t_inst.idempotency_key,
                    ),
                )

    def get_instance(self, instance_id: str) -> ProcessInstance | None:
        from atlas_process.engine import ProcessInstance, ProcessTaskInstance

        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM process_instances WHERE instance_id = ?", (instance_id,)
            ).fetchone()
            if not row:
                return None

            task_rows = conn.execute(
                "SELECT * FROM process_task_instances WHERE process_instance_id = ?",
                (instance_id,),
            ).fetchall()

            tasks_map = {}
            for tr in task_rows:
                t_inst = ProcessTaskInstance(
                    task_instance_id=tr["task_instance_id"],
                    process_instance_id=tr["process_instance_id"],
                    task_def_id=tr["task_def_id"],
                    task_type=TaskType(tr["task_type"]),
                    status=ProcessTaskStatus(tr["status"]),
                    assigned_to=tr["assigned_to"],
                    inputs=json.loads(tr["inputs"]),
                    outputs=json.loads(tr["outputs"]),
                    error=tr["error"],
                    lease_token=tr["lease_token"],
                    lease_fencing_token=tr["lease_fencing_token"],
                    lease_expires_at=tr["lease_expires_at"],
                    retry_count=tr["retry_count"],
                    started_at=tr["started_at"],
                    completed_at=tr["completed_at"],
                    idempotency_key=tr["idempotency_key"],
                )
                tasks_map[t_inst.task_def_id] = t_inst

            return ProcessInstance(
                instance_id=row["instance_id"],
                definition_id=row["definition_id"],
                definition_version=row["definition_version"],
                definition_hash=row["definition_hash"],
                tenant_id=row["tenant_id"],
                status=ProcessStatus(row["status"]),
                variables=json.loads(row["variables"]),
                task_instances=tasks_map,
                checkpoint_version=row["checkpoint_version"],
                idempotency_key=row["idempotency_key"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                completed_at=row["completed_at"],
                error_message=row["error_message"],
            )

    def list_instances(
        self,
        tenant_id: str | None = None,
        status: ProcessStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProcessInstance]:
        with self._lock:
            with self._get_connection() as conn:
                query = "SELECT instance_id FROM process_instances WHERE 1=1"
                params: list[Any] = []
                if tenant_id:
                    query += " AND tenant_id = ?"
                    params.append(tenant_id)
                if status:
                    query += " AND status = ?"
                    params.append(status.value)
                query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])

                rows = conn.execute(query, params).fetchall()
                instance_ids = [r["instance_id"] for r in rows if r]
            return [inst for iid in instance_ids if (inst := self.get_instance(iid)) is not None]

    def save_checkpoint(
        self,
        instance_id: str,
        checkpoint_version: int,
        state_snapshot: dict[str, Any],
        fencing_token: int = 0,
    ) -> None:
        raw_state = json.dumps(state_snapshot, sort_keys=True)
        checksum = hashlib.sha256(raw_state.encode("utf-8")).hexdigest()
        now = time.time()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO process_checkpoints (
                    instance_id, checkpoint_version, fencing_token, state_snapshot, checksum, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (instance_id, checkpoint_version) DO UPDATE SET
                    state_snapshot = excluded.state_snapshot,
                    fencing_token = excluded.fencing_token,
                    checksum = excluded.checksum
                """,
                (instance_id, checkpoint_version, fencing_token, raw_state, checksum, now),
            )

    def get_latest_checkpoint(self, instance_id: str) -> dict[str, Any] | None:
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT state_snapshot FROM process_checkpoints WHERE instance_id = ? ORDER BY checkpoint_version DESC LIMIT 1",
                (instance_id,),
            ).fetchone()
            return json.loads(row["state_snapshot"]) if row else None

    def acquire_lease(
        self,
        task_instance_id: str,
        process_instance_id: str,
        worker_id: str,
        lease_duration_seconds: float = 60.0,
    ) -> tuple[str, int]:
        with self._lock, self._get_connection() as conn:
            existing = conn.execute(
                "SELECT fencing_token FROM process_worker_leases WHERE task_instance_id = ?",
                (task_instance_id,),
            ).fetchone()
            current_fencing = (existing["fencing_token"] if existing else 0) + 1
            token = f"lease_{uuid.uuid4().hex[:12]}"
            expires_at = time.time() + lease_duration_seconds

            conn.execute(
                """
                INSERT INTO process_worker_leases (
                    task_instance_id, process_instance_id, worker_id, lease_token, fencing_token, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (task_instance_id) DO UPDATE SET
                    worker_id = excluded.worker_id,
                    lease_token = excluded.lease_token,
                    fencing_token = excluded.fencing_token,
                    expires_at = excluded.expires_at
                """,
                (
                    task_instance_id,
                    process_instance_id,
                    worker_id,
                    token,
                    current_fencing,
                    expires_at,
                ),
            )
            return token, current_fencing

    def verify_lease(
        self,
        task_instance_id: str,
        lease_token: str,
        fencing_token: int,
    ) -> bool:
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM process_worker_leases WHERE task_instance_id = ?",
                (task_instance_id,),
            ).fetchone()
            if not row:
                return False
            now = time.time()
            if now > row["expires_at"]:
                return False
            if row["lease_token"] != lease_token:
                return False
            if row["fencing_token"] != fencing_token:
                return False
            return True

    def renew_lease(
        self,
        task_instance_id: str,
        lease_token: str,
        extension_seconds: float = 60.0,
    ) -> bool:
        with self._lock, self._get_connection() as conn:
            now = time.time()
            row = conn.execute(
                "SELECT lease_token, expires_at FROM process_worker_leases WHERE task_instance_id = ?",
                (task_instance_id,),
            ).fetchone()
            if not row or row["lease_token"] != lease_token or now > row["expires_at"]:
                return False
            new_expires = now + extension_seconds
            conn.execute(
                "UPDATE process_worker_leases SET expires_at = ? WHERE task_instance_id = ?",
                (new_expires, task_instance_id),
            )
            return True

    def release_lease(
        self,
        task_instance_id: str,
        lease_token: str,
    ) -> bool:
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT lease_token FROM process_worker_leases WHERE task_instance_id = ?",
                (task_instance_id,),
            ).fetchone()
            if not row or row["lease_token"] != lease_token:
                return False
            conn.execute(
                "UPDATE process_worker_leases SET expires_at = 0.0, lease_token = '' WHERE task_instance_id = ?",
                (task_instance_id,),
            )
            return True

    def save_approval(self, approval: ApprovalRequest) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO process_approval_requests (
                    approval_id, process_instance_id, task_def_id, action_name, target_resource,
                    parameters, parameter_hash, requesting_identity, allowed_approver_ids,
                    allowed_approver_roles, required_approvals, risk_classification, status,
                    expires_at, created_at, resolved_at, decisions_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (approval_id) DO UPDATE SET
                    status = excluded.status,
                    resolved_at = excluded.resolved_at,
                    decisions_json = excluded.decisions_json
                """,
                (
                    approval.approval_id,
                    approval.process_instance_id,
                    approval.task_def_id,
                    approval.action_name,
                    approval.target_resource,
                    json.dumps(approval.parameters),
                    approval.parameter_hash,
                    approval.requesting_identity,
                    json.dumps(approval.allowed_approver_ids),
                    json.dumps(approval.allowed_approver_roles),
                    approval.required_approvals,
                    approval.risk_classification,
                    approval.status.value,
                    approval.expires_at,
                    approval.created_at,
                    approval.resolved_at,
                    json.dumps([d.model_dump() for d in approval.decisions]),
                ),
            )
            for d in approval.decisions:
                conn.execute(
                    """
                    INSERT INTO process_approval_decisions (
                        approval_id, approver_id, decision, comments, decided_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (approval_id, approver_id) DO UPDATE SET
                        decision = excluded.decision,
                        comments = excluded.comments,
                        decided_at = excluded.decided_at
                    """,
                    (
                        approval.approval_id,
                        d.approver_id,
                        d.decision.value,
                        d.comments,
                        d.decided_at,
                    ),
                )

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM process_approval_requests WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if not row:
                return None
            decisions = [ApprovalRecord(**d) for d in json.loads(row["decisions_json"])]
            return ApprovalRequest(
                approval_id=row["approval_id"],
                process_instance_id=row["process_instance_id"],
                task_def_id=row["task_def_id"],
                action_name=row["action_name"],
                target_resource=row["target_resource"],
                parameters=json.loads(row["parameters"]),
                parameter_hash=row["parameter_hash"],
                requesting_identity=row["requesting_identity"],
                allowed_approver_ids=json.loads(row["allowed_approver_ids"]),
                allowed_approver_roles=json.loads(row["allowed_approver_roles"]),
                required_approvals=row["required_approvals"],
                risk_classification=row["risk_classification"],
                status=ApprovalDecision(row["status"]),
                expires_at=row["expires_at"],
                created_at=row["created_at"],
                resolved_at=row["resolved_at"],
                decisions=decisions,
            )

    def save_saga(self, saga: SagaTransaction) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO process_saga_transactions (
                    saga_id, process_instance_id, status, steps_json, created_at, completed_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (saga_id) DO UPDATE SET
                    status = excluded.status,
                    steps_json = excluded.steps_json,
                    completed_at = excluded.completed_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    saga.saga_id,
                    saga.process_instance_id,
                    saga.status.value,
                    json.dumps([s.model_dump() for s in saga.steps]),
                    saga.created_at,
                    saga.completed_at,
                    json.dumps(saga.metadata),
                ),
            )

    def get_saga(self, saga_id: str) -> SagaTransaction | None:
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM process_saga_transactions WHERE saga_id = ?", (saga_id,)
            ).fetchone()
            if not row:
                return None
            steps = [SagaStep(**s) for s in json.loads(row["steps_json"])]
            return SagaTransaction(
                saga_id=row["saga_id"],
                process_instance_id=row["process_instance_id"],
                status=SagaStatus(row["status"]),
                steps=steps,
                created_at=row["created_at"],
                completed_at=row["completed_at"],
                metadata=json.loads(row["metadata_json"]),
            )

    def record_reconciliation(
        self,
        saga_id: str,
        step_id: str,
        reason: str,
        notes: str = "",
    ) -> int:
        with self._lock, self._get_connection() as conn:
            now = time.time()
            cur = conn.execute(
                """
                INSERT INTO process_reconciliation_records (
                    saga_id, step_id, reason, status, notes, created_at
                ) VALUES (?, ?, ?, 'PENDING', ?, ?)
                """,
                (saga_id, step_id, reason, notes, now),
            )
            return int(cur.lastrowid)

    def list_reconciliations(
        self,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock, self._get_connection() as conn:
            query = "SELECT id, saga_id, step_id, reason, status, resolved_by, notes, created_at, resolved_at FROM process_reconciliation_records"
            params = []
            if status:
                query += " WHERE status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "id": r["id"],
                    "saga_id": r["saga_id"],
                    "step_id": r["step_id"],
                    "reason": r["reason"],
                    "status": r["status"],
                    "resolved_by": r["resolved_by"],
                    "notes": r["notes"],
                    "created_at": r["created_at"],
                    "resolved_at": r["resolved_at"],
                }
                for r in rows
            ]

    def resolve_reconciliation(
        self,
        record_id: int | str,
        resolved_by: str,
        notes: str = "",
    ) -> bool:
        with self._lock, self._get_connection() as conn:
            now = time.time()
            cur = conn.execute(
                """
                UPDATE process_reconciliation_records
                SET status = 'RESOLVED', resolved_by = ?, notes = ?, resolved_at = ?
                WHERE id = ?
                """,
                (resolved_by, notes, now, int(record_id)),
            )
            return cur.rowcount > 0

    def record_event_inbox(
        self,
        event_id: str,
        tenant_id: str,
        source: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> bool:
        with self._lock, self._get_connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO process_event_inbox (
                        event_id, tenant_id, source, event_type, payload, status, received_at
                    ) VALUES (?, ?, ?, ?, ?, 'RECEIVED', ?)
                    """,
                    (event_id, tenant_id, source, event_type, json.dumps(payload), time.time()),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def has_event_inbox(self, tenant_id: str, event_id: str) -> bool:
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM process_event_inbox WHERE tenant_id = ? AND event_id = ?",
                (tenant_id, event_id),
            ).fetchone()
            return row is not None

    def archive_completed_instances(
        self,
        cutoff_timestamp: float,
        tenant_id: str | None = None,
    ) -> int:
        with self._lock, self._get_connection() as conn:
            query = """
            DELETE FROM process_instances
            WHERE status IN ('COMPLETED', 'FAILED')
              AND completed_at IS NOT NULL
              AND completed_at < ?
              AND instance_id NOT IN (
                  SELECT pst.process_instance_id
                  FROM process_saga_transactions pst
                  JOIN process_reconciliation_records prr ON prr.saga_id = pst.saga_id
                  WHERE prr.status = 'PENDING'
              )
            """
            params: list[Any] = [cutoff_timestamp]
            if tenant_id:
                query += " AND tenant_id = ?"
                params.append(tenant_id)
            cur = conn.execute(query, params)
            return cur.rowcount

    def get_uncompleted_instances(self) -> list[ProcessInstance]:
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT instance_id FROM process_instances WHERE status IN ('RUNNING', 'SUSPENDED')"
                ).fetchall()
                instance_ids = [r["instance_id"] for r in rows if r]
            return [inst for iid in instance_ids if (inst := self.get_instance(iid)) is not None]


class PostgresProcessStorage:
    """Production PostgreSQL 16+ storage engine with connection pooling and WAL ACID guarantees."""

    def __init__(
        self, connection_uri: str, min_pool_size: int = 2, max_pool_size: int = 20
    ) -> None:
        self.connection_uri = connection_uri
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self._pool = None

    def _ensure_pool(self):
        if self._pool is None:
            try:
                from psycopg_pool import ConnectionPool

                self._pool = ConnectionPool(
                    self.connection_uri,
                    min_size=self.min_pool_size,
                    max_size=self.max_pool_size,
                    open=True,
                )
            except Exception as exc:
                raise StorageError(f"Failed to connect to PostgreSQL pool: {exc}") from exc
        return self._pool

    def close(self) -> None:
        if self._pool:
            self._pool.close()
            self._pool = None

    def initialize(self) -> None:
        """Apply schema DDL idempotently from migrations in forward order."""
        pool = self._ensure_pool()
        migrations_dir = Path(__file__).resolve().parents[4] / "migrations"
        if not migrations_dir.exists():
            raise StorageError(f"Migrations directory not found at {migrations_dir}")

        migration_files = sorted(migrations_dir.glob("*.sql"))
        if not migration_files:
            raise StorageError(f"No migration SQL files found in {migrations_dir}")

        with pool.connection() as conn:
            with conn.cursor() as cur:
                for m_file in migration_files:
                    ddl = m_file.read_text(encoding="utf-8")
                    cur.execute(ddl)
            conn.commit()

    def save_definition(self, definition: ProcessDefinition) -> None:
        pool = self._ensure_pool()
        tasks_json = json.dumps([t.model_dump() for t in definition.tasks])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO process_definitions (
                        definition_id, tenant_id, name, version, status, tasks_schema, definition_hash, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (definition_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        version = EXCLUDED.version,
                        status = EXCLUDED.status,
                        tasks_schema = EXCLUDED.tasks_schema,
                        definition_hash = EXCLUDED.definition_hash,
                        updated_at = NOW();
                    """,
                    (
                        definition.definition_id,
                        definition.tenant_id,
                        definition.name,
                        definition.version,
                        definition.status.value,
                        tasks_json,
                        definition.definition_hash or definition.compute_hash(),
                    ),
                )
            conn.commit()

    def get_definition(self, definition_id: str) -> ProcessDefinition | None:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT definition_id, tenant_id, name, version, status, tasks_schema, definition_hash FROM process_definitions WHERE definition_id = %s",
                    (definition_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                tasks_raw = row[5] if isinstance(row[5], list) else json.loads(row[5])
                tasks = [ProcessTaskDefinition(**t) for t in tasks_raw]
                return ProcessDefinition(
                    definition_id=row[0],
                    tenant_id=row[1],
                    name=row[2],
                    version=row[3],
                    status=ProcessDefinitionStatus(row[4]),
                    tasks=tasks,
                    definition_hash=row[6],
                )

    def save_instance(self, instance: ProcessInstance) -> None:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO process_instances (
                        instance_id, definition_id, definition_version, definition_hash, tenant_id,
                        status, variables, checkpoint_version, idempotency_key, created_at, updated_at,
                        completed_at, error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (instance_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        variables = EXCLUDED.variables,
                        checkpoint_version = EXCLUDED.checkpoint_version,
                        updated_at = EXCLUDED.updated_at,
                        completed_at = EXCLUDED.completed_at,
                        error_message = EXCLUDED.error_message;
                    """,
                    (
                        instance.instance_id,
                        instance.definition_id,
                        instance.definition_version,
                        instance.definition_hash,
                        instance.tenant_id,
                        instance.status.value,
                        json.dumps(instance.variables),
                        instance.checkpoint_version,
                        instance.idempotency_key,
                        instance.created_at,
                        instance.updated_at,
                        instance.completed_at,
                        instance.error_message,
                    ),
                )

                for t_inst in instance.task_instances.values():
                    cur.execute(
                        """
                        INSERT INTO process_task_instances (
                            task_instance_id, process_instance_id, task_def_id, task_type,
                            status, assigned_to, inputs, outputs, error, lease_token,
                            lease_fencing_token, lease_expires_at, retry_count, started_at,
                            completed_at, idempotency_key
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (task_instance_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            assigned_to = EXCLUDED.assigned_to,
                            inputs = EXCLUDED.inputs,
                            outputs = EXCLUDED.outputs,
                            error = EXCLUDED.error,
                            lease_token = EXCLUDED.lease_token,
                            lease_fencing_token = EXCLUDED.lease_fencing_token,
                            lease_expires_at = EXCLUDED.lease_expires_at,
                            retry_count = EXCLUDED.retry_count,
                            started_at = EXCLUDED.started_at,
                            completed_at = EXCLUDED.completed_at;
                        """,
                        (
                            t_inst.task_instance_id,
                            t_inst.process_instance_id,
                            t_inst.task_def_id,
                            t_inst.task_type.value,
                            t_inst.status.value,
                            t_inst.assigned_to,
                            json.dumps(t_inst.inputs),
                            json.dumps(t_inst.outputs),
                            t_inst.error,
                            t_inst.lease_token,
                            t_inst.lease_fencing_token,
                            t_inst.lease_expires_at,
                            t_inst.retry_count,
                            t_inst.started_at,
                            t_inst.completed_at,
                            t_inst.idempotency_key,
                        ),
                    )
            conn.commit()

    def get_instance(self, instance_id: str) -> ProcessInstance | None:
        from atlas_process.engine import ProcessInstance, ProcessTaskInstance

        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT instance_id, definition_id, definition_version, definition_hash, tenant_id, status, variables, checkpoint_version, idempotency_key, created_at, updated_at, completed_at, error_message FROM process_instances WHERE instance_id = %s",
                    (instance_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None

                cur.execute(
                    "SELECT task_instance_id, process_instance_id, task_def_id, task_type, status, assigned_to, inputs, outputs, error, lease_token, lease_fencing_token, lease_expires_at, retry_count, started_at, completed_at, idempotency_key FROM process_task_instances WHERE process_instance_id = %s",
                    (instance_id,),
                )
                task_rows = cur.fetchall()
                tasks_map = {}
                for tr in task_rows:
                    inp = tr[6] if isinstance(tr[6], dict) else json.loads(tr[6])
                    out = tr[7] if isinstance(tr[7], dict) else json.loads(tr[7])
                    t_inst = ProcessTaskInstance(
                        task_instance_id=tr[0],
                        process_instance_id=tr[1],
                        task_def_id=tr[2],
                        task_type=TaskType(tr[3]),
                        status=ProcessTaskStatus(tr[4]),
                        assigned_to=tr[5],
                        inputs=inp,
                        outputs=out,
                        error=tr[8],
                        lease_token=tr[9],
                        lease_fencing_token=tr[10],
                        lease_expires_at=tr[11],
                        retry_count=tr[12],
                        started_at=tr[13],
                        completed_at=tr[14],
                        idempotency_key=tr[15],
                    )
                    tasks_map[t_inst.task_def_id] = t_inst

                vars_data = row[6] if isinstance(row[6], dict) else json.loads(row[6])
                return ProcessInstance(
                    instance_id=row[0],
                    definition_id=row[1],
                    definition_version=row[2],
                    definition_hash=row[3],
                    tenant_id=row[4],
                    status=ProcessStatus(row[5]),
                    variables=vars_data,
                    task_instances=tasks_map,
                    checkpoint_version=row[7],
                    idempotency_key=row[8],
                    created_at=row[9],
                    updated_at=row[10],
                    completed_at=row[11],
                    error_message=row[12],
                )

    def list_instances(
        self,
        tenant_id: str | None = None,
        status: ProcessStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProcessInstance]:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                query = "SELECT instance_id FROM process_instances WHERE 1=1"
                params: list[Any] = []
                if tenant_id:
                    query += " AND tenant_id = %s"
                    params.append(tenant_id)
                if status:
                    query += " AND status = %s"
                    params.append(status.value)
                query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                cur.execute(query, tuple(params))
                rows = cur.fetchall()
                return [inst for r in rows if r and (inst := self.get_instance(r[0])) is not None]

    def save_checkpoint(
        self,
        instance_id: str,
        checkpoint_version: int,
        state_snapshot: dict[str, Any],
        fencing_token: int = 0,
    ) -> None:
        pool = self._ensure_pool()
        raw_state = json.dumps(state_snapshot, sort_keys=True)
        checksum = hashlib.sha256(raw_state.encode("utf-8")).hexdigest()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO process_checkpoints (
                        instance_id, checkpoint_version, fencing_token, state_snapshot, checksum, created_at
                    ) VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (instance_id, checkpoint_version) DO UPDATE SET
                        state_snapshot = EXCLUDED.state_snapshot,
                        fencing_token = EXCLUDED.fencing_token,
                        checksum = EXCLUDED.checksum;
                    """,
                    (instance_id, checkpoint_version, fencing_token, raw_state, checksum),
                )
            conn.commit()

    def get_latest_checkpoint(self, instance_id: str) -> dict[str, Any] | None:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT state_snapshot FROM process_checkpoints WHERE instance_id = %s ORDER BY checkpoint_version DESC LIMIT 1",
                    (instance_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return row[0] if isinstance(row[0], dict) else json.loads(row[0])

    def acquire_lease(
        self,
        task_instance_id: str,
        process_instance_id: str,
        worker_id: str,
        lease_duration_seconds: float = 60.0,
    ) -> tuple[str, int]:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT fencing_token FROM process_worker_leases WHERE task_instance_id = %s FOR UPDATE",
                    (task_instance_id,),
                )
                existing = cur.fetchone()
                current_fencing = (existing[0] if existing else 0) + 1
                token = f"lease_{uuid.uuid4().hex[:12]}"
                now = time.time()
                expires_at = now + lease_duration_seconds

                cur.execute(
                    """
                    INSERT INTO process_worker_leases (
                        lease_id, task_instance_id, process_instance_id, worker_id, lease_token, fencing_token, status, acquired_at, expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'ACTIVE', %s, %s)
                    ON CONFLICT (task_instance_id) DO UPDATE SET
                        worker_id = EXCLUDED.worker_id,
                        lease_token = EXCLUDED.lease_token,
                        fencing_token = EXCLUDED.fencing_token,
                        status = 'ACTIVE',
                        acquired_at = EXCLUDED.acquired_at,
                        expires_at = EXCLUDED.expires_at;
                    """,
                    (
                        f"wl_{uuid.uuid4().hex[:10]}",
                        task_instance_id,
                        process_instance_id,
                        worker_id,
                        token,
                        current_fencing,
                        now,
                        expires_at,
                    ),
                )
            conn.commit()
            return token, current_fencing

    def verify_lease(
        self,
        task_instance_id: str,
        lease_token: str,
        fencing_token: int,
    ) -> bool:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT lease_token, fencing_token, expires_at FROM process_worker_leases WHERE task_instance_id = %s",
                    (task_instance_id,),
                )
                row = cur.fetchone()
                if not row:
                    return False
                now = time.time()
                if now > row[2]:
                    return False
                if row[0] != lease_token:
                    return False
                if row[1] != fencing_token:
                    return False
                return True

    def renew_lease(
        self,
        task_instance_id: str,
        lease_token: str,
        extension_seconds: float = 60.0,
    ) -> bool:
        pool = self._ensure_pool()
        now = time.time()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT lease_token, expires_at FROM process_worker_leases WHERE task_instance_id = %s FOR UPDATE",
                    (task_instance_id,),
                )
                row = cur.fetchone()
                if not row or row[0] != lease_token or now > row[1]:
                    return False
                new_expires = now + extension_seconds
                cur.execute(
                    "UPDATE process_worker_leases SET expires_at = %s WHERE task_instance_id = %s",
                    (new_expires, task_instance_id),
                )
            conn.commit()
            return True

    def release_lease(
        self,
        task_instance_id: str,
        lease_token: str,
    ) -> bool:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT lease_token FROM process_worker_leases WHERE task_instance_id = %s FOR UPDATE",
                    (task_instance_id,),
                )
                row = cur.fetchone()
                if not row or row[0] != lease_token:
                    return False
                cur.execute(
                    "UPDATE process_worker_leases SET expires_at = 0.0, lease_token = '' WHERE task_instance_id = %s",
                    (task_instance_id,),
                )
            conn.commit()
            return True

    def save_approval(self, approval: ApprovalRequest) -> None:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO process_approval_requests (
                        approval_id, process_instance_id, task_def_id, action_name, target_resource,
                        parameters, parameter_hash, requesting_identity, allowed_approver_ids,
                        allowed_approver_roles, required_approvals, risk_classification, status,
                        expires_at, created_at, resolved_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (approval_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        resolved_at = EXCLUDED.resolved_at;
                    """,
                    (
                        approval.approval_id,
                        approval.process_instance_id,
                        approval.task_def_id,
                        approval.action_name,
                        approval.target_resource,
                        json.dumps(approval.parameters),
                        approval.parameter_hash,
                        approval.requesting_identity,
                        json.dumps(approval.allowed_approver_ids),
                        json.dumps(approval.allowed_approver_roles),
                        approval.required_approvals,
                        approval.risk_classification,
                        approval.status.value,
                        approval.expires_at,
                        approval.created_at,
                        approval.resolved_at,
                    ),
                )
                for d in approval.decisions:
                    cur.execute(
                        """
                        INSERT INTO process_approval_decisions (
                            approval_id, approver_id, decision, comments, decided_at
                        ) VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (approval_id, approver_id) DO UPDATE SET
                            decision = EXCLUDED.decision,
                            comments = EXCLUDED.comments,
                            decided_at = EXCLUDED.decided_at;
                        """,
                        (
                            approval.approval_id,
                            d.approver_id,
                            d.decision.value,
                            d.comments,
                            d.decided_at,
                        ),
                    )
            conn.commit()

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT approval_id, process_instance_id, task_def_id, action_name, target_resource, parameters, parameter_hash, requesting_identity, allowed_approver_ids, allowed_approver_roles, required_approvals, risk_classification, status, expires_at, created_at, resolved_at FROM process_approval_requests WHERE approval_id = %s",
                    (approval_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                params = row[5] if isinstance(row[5], dict) else json.loads(row[5])
                appr_ids = row[8] if isinstance(row[8], list) else json.loads(row[8])
                appr_roles = row[9] if isinstance(row[9], list) else json.loads(row[9])

                cur.execute(
                    "SELECT approver_id, decision, comments, decided_at FROM process_approval_decisions WHERE approval_id = %s ORDER BY decided_at ASC",
                    (approval_id,),
                )
                decision_rows = cur.fetchall()
                decisions = [
                    ApprovalRecord(
                        approver_id=dr[0],
                        decision=ApprovalDecision(dr[1]),
                        comments=dr[2],
                        decided_at=dr[3],
                    )
                    for dr in decision_rows
                ]

                return ApprovalRequest(
                    approval_id=row[0],
                    process_instance_id=row[1],
                    task_def_id=row[2],
                    action_name=row[3],
                    target_resource=row[4],
                    parameters=params,
                    parameter_hash=row[6],
                    requesting_identity=row[7],
                    allowed_approver_ids=appr_ids,
                    allowed_approver_roles=appr_roles,
                    required_approvals=row[10],
                    risk_classification=row[11],
                    status=ApprovalDecision(row[12]),
                    expires_at=row[13],
                    created_at=row[14],
                    resolved_at=row[15],
                    decisions=decisions,
                )

    def save_saga(self, saga: SagaTransaction) -> None:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO process_saga_transactions (
                        saga_id, process_instance_id, status, created_at, completed_at, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (saga_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        completed_at = EXCLUDED.completed_at,
                        metadata = EXCLUDED.metadata;
                    """,
                    (
                        saga.saga_id,
                        saga.process_instance_id,
                        saga.status.value,
                        saga.created_at,
                        saga.completed_at,
                        json.dumps(saga.metadata),
                    ),
                )
                for step in saga.steps:
                    cur.execute(
                        """
                        INSERT INTO process_saga_steps (
                            step_id, saga_id, name, status, is_idempotent, idempotency_key,
                            forward_payload, forward_result, compensation_payload,
                            compensation_attempts, compensation_history, error_message,
                            executed_at, compensated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (step_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            forward_result = EXCLUDED.forward_result,
                            compensation_payload = EXCLUDED.compensation_payload,
                            compensation_attempts = EXCLUDED.compensation_attempts,
                            compensation_history = EXCLUDED.compensation_history,
                            error_message = EXCLUDED.error_message,
                            executed_at = EXCLUDED.executed_at,
                            compensated_at = EXCLUDED.compensated_at;
                        """,
                        (
                            step.step_id,
                            saga.saga_id,
                            step.name,
                            step.status.value,
                            step.is_idempotent,
                            step.idempotency_key,
                            json.dumps(step.forward_payload),
                            json.dumps(step.forward_result),
                            json.dumps(step.compensation_payload),
                            step.compensation_attempts,
                            json.dumps(step.compensation_history),
                            step.error_message,
                            step.executed_at,
                            step.compensated_at,
                        ),
                    )
            conn.commit()

    def get_saga(self, saga_id: str) -> SagaTransaction | None:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT saga_id, process_instance_id, status, created_at, completed_at, metadata FROM process_saga_transactions WHERE saga_id = %s",
                    (saga_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                meta = row[5] if isinstance(row[5], dict) else json.loads(row[5])

                cur.execute(
                    """
                    SELECT step_id, name, status, is_idempotent, idempotency_key,
                           forward_payload, forward_result, compensation_payload,
                           compensation_attempts, compensation_history, error_message,
                           executed_at, compensated_at
                    FROM process_saga_steps
                    WHERE saga_id = %s
                    ORDER BY executed_at ASC NULLS LAST, step_id ASC
                    """,
                    (saga_id,),
                )
                step_rows = cur.fetchall()
                steps: list[SagaStep] = []
                for sr in step_rows:
                    fwd_payload = sr[5] if isinstance(sr[5], dict) else json.loads(sr[5])
                    fwd_result = sr[6] if isinstance(sr[6], dict) else json.loads(sr[6])
                    comp_payload = sr[7] if isinstance(sr[7], dict) else json.loads(sr[7])
                    comp_hist = sr[9] if isinstance(sr[9], list) else json.loads(sr[9])
                    steps.append(
                        SagaStep(
                            step_id=sr[0],
                            name=sr[1],
                            status=SagaStepStatus(sr[2]),
                            is_idempotent=sr[3],
                            idempotency_key=sr[4],
                            forward_payload=fwd_payload,
                            forward_result=fwd_result,
                            compensation_payload=comp_payload,
                            compensation_attempts=sr[8],
                            compensation_history=comp_hist,
                            error_message=sr[10],
                            executed_at=sr[11],
                            compensated_at=sr[12],
                        )
                    )

                return SagaTransaction(
                    saga_id=row[0],
                    process_instance_id=row[1],
                    status=SagaStatus(row[2]),
                    steps=steps,
                    created_at=row[3],
                    completed_at=row[4],
                    metadata=meta,
                )

    def record_reconciliation(
        self,
        saga_id: str,
        step_id: str,
        reason: str,
        notes: str = "",
    ) -> int:
        pool = self._ensure_pool()
        now = time.time()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO process_reconciliation_records (
                        saga_id, step_id, reason, status, notes, created_at
                    ) VALUES (%s, %s, %s, 'PENDING', %s, %s)
                    RETURNING id;
                    """,
                    (saga_id, step_id, reason, notes, now),
                )
                rec_id = cur.fetchone()[0]
            conn.commit()
            return rec_id

    def list_reconciliations(
        self,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                query = "SELECT id, saga_id, step_id, reason, status, resolved_by, notes, created_at, resolved_at FROM process_reconciliation_records"
                params = []
                if status:
                    query += " WHERE status = %s"
                    params.append(status)
                query += " ORDER BY created_at DESC"
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
                return [
                    {
                        "id": r[0],
                        "saga_id": r[1],
                        "step_id": r[2],
                        "reason": r[3],
                        "status": r[4],
                        "resolved_by": r[5],
                        "notes": r[6],
                        "created_at": r[7],
                        "resolved_at": r[8],
                    }
                    for r in rows
                ]

    def resolve_reconciliation(
        self,
        record_id: int | str,
        resolved_by: str,
        notes: str = "",
    ) -> bool:
        pool = self._ensure_pool()
        now = time.time()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE process_reconciliation_records
                    SET status = 'RESOLVED', resolved_by = %s, notes = %s, resolved_at = %s
                    WHERE id = %s
                    """,
                    (resolved_by, notes, now, int(record_id)),
                )
                affected = cur.rowcount > 0
            conn.commit()
            return affected

    def record_event_inbox(
        self,
        event_id: str,
        tenant_id: str,
        source: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> bool:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO process_event_inbox (
                            event_id, tenant_id, source, event_type, payload, status, received_at
                        ) VALUES (%s, %s, %s, %s, %s, 'RECEIVED', %s)
                        ON CONFLICT (event_id) DO NOTHING
                        """,
                        (event_id, tenant_id, source, event_type, json.dumps(payload), time.time()),
                    )
                    inserted = cur.rowcount > 0
                except Exception:
                    inserted = False
            conn.commit()
            return inserted

    def has_event_inbox(self, tenant_id: str, event_id: str) -> bool:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM process_event_inbox WHERE tenant_id = %s AND event_id = %s",
                    (tenant_id, event_id),
                )
                return cur.fetchone() is not None

    def archive_completed_instances(
        self,
        cutoff_timestamp: float,
        tenant_id: str | None = None,
    ) -> int:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                query = """
                DELETE FROM process_instances
                WHERE status IN ('COMPLETED', 'FAILED')
                  AND completed_at IS NOT NULL
                  AND completed_at < %s
                  AND instance_id NOT IN (
                      SELECT pst.process_instance_id
                      FROM process_saga_transactions pst
                      JOIN process_reconciliation_records prr ON prr.saga_id = pst.saga_id
                      WHERE prr.status = 'PENDING'
                  )
                """
                params: list[Any] = [cutoff_timestamp]
                if tenant_id:
                    query += " AND tenant_id = %s"
                    params.append(tenant_id)
                cur.execute(query, tuple(params))
                deleted_count = cur.rowcount
            conn.commit()
            return deleted_count

    def get_uncompleted_instances(self) -> list[ProcessInstance]:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT instance_id FROM process_instances WHERE status IN ('RUNNING', 'SUSPENDED')"
                )
                rows = cur.fetchall()
                return [inst for r in rows if r and (inst := self.get_instance(r[0])) is not None]
