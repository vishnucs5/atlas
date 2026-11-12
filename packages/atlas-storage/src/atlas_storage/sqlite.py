"""SQLite implementation of event-sourced storage, checkpoints, worker leases, and action ledger for ATLAS."""

import json
import os
import sqlite3
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.ledger import ActionExecutionRecord, ActionExecutionStatus
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_core.contracts.worker import LeaseStatus, WorkerLease, WorkerRecord, WorkerStatus

from atlas_storage.interfaces import (
    ActionLedgerStoreProtocol,
    ActionNotFoundError,
    CheckpointStoreProtocol,
    CorruptedCheckpointError,
    EventStoreProtocol,
    LeaseExpiredError,
    OptimisticLockError,
    SequenceCollisionError,
    StaleWorkerError,
    StorageError,
    TaskNotFoundError,
    TaskStoreProtocol,
    WorkerStoreProtocol,
)

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    priority TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    current_checkpoint_id TEXT,
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);

CREATE TABLE IF NOT EXISTS execution_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    session_id TEXT,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '1.0',
    UNIQUE (task_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_events_task_seq ON execution_events(task_id, sequence);
CREATE INDEX IF NOT EXISTS idx_events_correlation ON execution_events(correlation_id);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    session_id TEXT,
    worker_id TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL,
    sequence INTEGER NOT NULL DEFAULT 0,
    plan_id TEXT,
    plan_version INTEGER NOT NULL DEFAULT 1,
    current_step_id TEXT,
    completed_action_ids TEXT NOT NULL DEFAULT '[]',
    pending_action_ids TEXT NOT NULL DEFAULT '[]',
    uncertain_action_ids TEXT NOT NULL DEFAULT '[]',
    last_event_sequence INTEGER NOT NULL DEFAULT 0,
    state_snapshot TEXT NOT NULL DEFAULT '{}',
    environment_metadata TEXT NOT NULL DEFAULT '{}',
    verification_evidence_refs TEXT NOT NULL DEFAULT '[]',
    recovery_metadata TEXT NOT NULL DEFAULT '{}',
    metadata TEXT NOT NULL DEFAULT '{}',
    checkpoint_hash TEXT,
    schema_version TEXT NOT NULL DEFAULT '1.0',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_task ON checkpoints(task_id, created_at);

CREATE TABLE IF NOT EXISTS action_ledger (
    action_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    lease_generation INTEGER NOT NULL DEFAULT 1,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    action_type TEXT NOT NULL,
    parameters TEXT NOT NULL DEFAULT '{}',
    output TEXT,
    verification_result TEXT,
    error TEXT,
    schema_version TEXT NOT NULL DEFAULT '1.0',
    PRIMARY KEY (task_id, idempotency_key, attempt)
);

CREATE INDEX IF NOT EXISTS idx_ledger_action_id ON action_ledger(action_id);
CREATE INDEX IF NOT EXISTS idx_ledger_task_status ON action_ledger(task_id, status);

CREATE TABLE IF NOT EXISTS worker_registry (
    worker_id TEXT PRIMARY KEY,
    hostname TEXT NOT NULL,
    status TEXT NOT NULL,
    capabilities TEXT NOT NULL DEFAULT '[]',
    current_task_id TEXT,
    registered_at TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS worker_leases (
    lease_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE,
    worker_id TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE INDEX IF NOT EXISTS idx_leases_worker ON worker_leases(worker_id);
"""


class SQLiteStorage(
    TaskStoreProtocol,
    EventStoreProtocol,
    CheckpointStoreProtocol,
    ActionLedgerStoreProtocol,
    WorkerStoreProtocol,
):
    """Event-sourced task storage, checkpoint, worker lease, and ledger engine powered by SQLite."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

        if self._db_path != ":memory:":
            abs_path = os.path.abspath(self._db_path)
            parent_dir = os.path.dirname(abs_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                timeout=5.0,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def initialize(self) -> None:
        """Initialize database pragmas and execute schema DDL."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if self._db_path != ":memory:":
                cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA busy_timeout = 5000;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.executescript(SCHEMA_DDL)
            conn.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection if open."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "SQLiteStorage":
        self.initialize()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # -------------------------------------------------------------------------
    # TaskStoreProtocol Implementation
    # -------------------------------------------------------------------------

    def save_task(self, task: Task) -> None:
        query = """
        INSERT INTO tasks (
            task_id, objective, status, priority, created_at, updated_at,
            metadata, current_checkpoint_id, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            objective = excluded.objective,
            status = excluded.status,
            priority = excluded.priority,
            updated_at = excluded.updated_at,
            metadata = excluded.metadata,
            current_checkpoint_id = excluded.current_checkpoint_id,
            schema_version = excluded.schema_version;
        """
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    query,
                    (
                        task.task_id,
                        task.objective,
                        task.status.value
                        if isinstance(task.status, TaskStatus)
                        else str(task.status),
                        task.priority.value
                        if isinstance(task.priority, TaskPriority)
                        else str(task.priority),
                        task.created_at.isoformat(),
                        task.updated_at.isoformat(),
                        json.dumps(task.metadata),
                        task.current_checkpoint_id,
                        task.schema_version,
                    ),
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(f"Failed to save task '{task.task_id}': {exc}") from exc

    def get_task(self, task_id: str) -> Task | None:
        query = "SELECT * FROM tasks WHERE task_id = ?;"
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (task_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_task(row)

    def update_task_status(
        self,
        task_id: str,
        new_status: TaskStatus,
        expected_status: TaskStatus | None = None,
    ) -> Task:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("SELECT * FROM tasks WHERE task_id = ?;", (task_id,))
            row = cursor.fetchone()
            if row is None:
                raise TaskNotFoundError(f"Task with ID '{task_id}' does not exist.")

            current_status = TaskStatus(row["status"])
            if expected_status is not None and current_status != expected_status:
                raise OptimisticLockError(
                    f"Task '{task_id}' status mismatch. Expected '{expected_status.value}', found '{current_status.value}'."
                )

            now = datetime.now(UTC)
            update_query = "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?;"
            try:
                conn.execute(
                    update_query,
                    (
                        new_status.value if isinstance(new_status, TaskStatus) else str(new_status),
                        now.isoformat(),
                        task_id,
                    ),
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(f"Failed to update task status: {exc}") from exc

            cursor = conn.execute("SELECT * FROM tasks WHERE task_id = ?;", (task_id,))
            updated_row = cursor.fetchone()
            return self._row_to_task(updated_row)  # type: ignore

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        with self._lock:
            conn = self._get_connection()
            if status is not None:
                query = "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?;"
                status_str = status.value if isinstance(status, TaskStatus) else str(status)
                cursor = conn.execute(query, (status_str, limit, offset))
            else:
                query = "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?;"
                cursor = conn.execute(query, (limit, offset))
            rows = cursor.fetchall()
            return [self._row_to_task(r) for r in rows]

    # -------------------------------------------------------------------------
    # EventStoreProtocol Implementation
    # -------------------------------------------------------------------------

    def append_event(self, event: ExecutionEvent) -> None:
        query = """
        INSERT INTO execution_events (
            event_id, task_id, session_id, sequence, event_type,
            timestamp, payload, correlation_id, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    query,
                    (
                        event.event_id,
                        event.task_id,
                        event.session_id,
                        event.sequence,
                        event.event_type.value
                        if isinstance(event.event_type, EventType)
                        else str(event.event_type),
                        event.timestamp.isoformat(),
                        json.dumps(event.payload),
                        event.correlation_id,
                        event.schema_version,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise SequenceCollisionError(
                    f"Integrity violation on event '{event.event_id}' (sequence {event.sequence} for task '{event.task_id}'): {exc}"
                ) from exc
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(f"Failed to append event: {exc}") from exc

    def append_events(self, events: list[ExecutionEvent]) -> None:
        if not events:
            return
        query = """
        INSERT INTO execution_events (
            event_id, task_id, session_id, sequence, event_type,
            timestamp, payload, correlation_id, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = [
            (
                e.event_id,
                e.task_id,
                e.session_id,
                e.sequence,
                e.event_type.value if isinstance(e.event_type, EventType) else str(e.event_type),
                e.timestamp.isoformat(),
                json.dumps(e.payload),
                e.correlation_id,
                e.schema_version,
            )
            for e in events
        ]
        with self._lock:
            conn = self._get_connection()
            try:
                conn.executemany(query, params)
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise SequenceCollisionError(
                    f"Batch append aborted due to integrity collision: {exc}"
                ) from exc
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(f"Batch append failed: {exc}") from exc

    def get_events(
        self,
        task_id: str,
        since_sequence: int = 0,
    ) -> list[ExecutionEvent]:
        query = """
        SELECT * FROM execution_events
        WHERE task_id = ? AND sequence > ?
        ORDER BY sequence ASC;
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (task_id, since_sequence))
            rows = cursor.fetchall()
            return [self._row_to_event(r) for r in rows]

    def get_latest_event(self, task_id: str) -> ExecutionEvent | None:
        query = """
        SELECT * FROM execution_events
        WHERE task_id = ?
        ORDER BY sequence DESC
        LIMIT 1;
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (task_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_event(row)

    def get_latest_sequence(self, task_id: str) -> int:
        query = "SELECT MAX(sequence) as max_seq FROM execution_events WHERE task_id = ?;"
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (task_id,))
            row = cursor.fetchone()
            if row is None or row["max_seq"] is None:
                return 0
            return int(row["max_seq"])

    # -------------------------------------------------------------------------
    # CheckpointStoreProtocol Implementation
    # -------------------------------------------------------------------------

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Persist a versioned, sealed task checkpoint."""
        query = """
        INSERT INTO checkpoints (
            checkpoint_id, task_id, session_id, worker_id, lease_generation,
            state, sequence, plan_id, plan_version, current_step_id,
            completed_action_ids, pending_action_ids, uncertain_action_ids,
            last_event_sequence, state_snapshot, environment_metadata,
            verification_evidence_refs, recovery_metadata, metadata,
            checkpoint_hash, schema_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(checkpoint_id) DO UPDATE SET
            state = excluded.state,
            sequence = excluded.sequence,
            lease_generation = excluded.lease_generation,
            plan_id = excluded.plan_id,
            plan_version = excluded.plan_version,
            current_step_id = excluded.current_step_id,
            completed_action_ids = excluded.completed_action_ids,
            pending_action_ids = excluded.pending_action_ids,
            uncertain_action_ids = excluded.uncertain_action_ids,
            last_event_sequence = excluded.last_event_sequence,
            state_snapshot = excluded.state_snapshot,
            environment_metadata = excluded.environment_metadata,
            verification_evidence_refs = excluded.verification_evidence_refs,
            recovery_metadata = excluded.recovery_metadata,
            metadata = excluded.metadata,
            checkpoint_hash = excluded.checkpoint_hash;
        """
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    query,
                    (
                        checkpoint.checkpoint_id,
                        checkpoint.task_id,
                        checkpoint.session_id,
                        checkpoint.worker_id,
                        checkpoint.lease_generation,
                        checkpoint.state.value
                        if isinstance(checkpoint.state, TaskStatus)
                        else str(checkpoint.state),
                        checkpoint.sequence,
                        checkpoint.plan_id,
                        checkpoint.plan_version,
                        checkpoint.current_step_id,
                        json.dumps(checkpoint.completed_action_ids),
                        json.dumps(checkpoint.pending_action_ids),
                        json.dumps(checkpoint.uncertain_action_ids),
                        checkpoint.last_event_sequence,
                        json.dumps(checkpoint.state_snapshot),
                        json.dumps(checkpoint.environment_metadata),
                        json.dumps(checkpoint.verification_evidence_refs),
                        json.dumps(checkpoint.recovery_metadata),
                        json.dumps(checkpoint.metadata),
                        checkpoint.checkpoint_hash,
                        checkpoint.schema_version,
                        checkpoint.timestamp.isoformat(),
                    ),
                )
                # Update task pointer
                conn.execute(
                    "UPDATE tasks SET current_checkpoint_id = ? WHERE task_id = ?;",
                    (checkpoint.checkpoint_id, checkpoint.task_id),
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(
                    f"Failed to save checkpoint '{checkpoint.checkpoint_id}': {exc}"
                ) from exc

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        query = "SELECT * FROM checkpoints WHERE checkpoint_id = ?;"
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (checkpoint_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_checkpoint(row)

    def get_latest_checkpoint(self, task_id: str) -> Checkpoint | None:
        query = """
        SELECT * FROM checkpoints
        WHERE task_id = ?
        ORDER BY created_at DESC, sequence DESC
        LIMIT 1;
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (task_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_checkpoint(row)

    def list_checkpoints(self, task_id: str, limit: int = 50) -> list[Checkpoint]:
        query = """
        SELECT * FROM checkpoints
        WHERE task_id = ?
        ORDER BY created_at DESC, sequence DESC
        LIMIT ?;
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (task_id, limit))
            rows = cursor.fetchall()
            checkpoints: list[Checkpoint] = []
            for r in rows:
                try:
                    checkpoints.append(self._row_to_checkpoint(r))
                except CorruptedCheckpointError:
                    continue
            return checkpoints

    # -------------------------------------------------------------------------
    # ActionLedgerStoreProtocol Implementation
    # -------------------------------------------------------------------------

    def record_action_attempt(self, record: ActionExecutionRecord) -> None:
        query = """
        INSERT INTO action_ledger (
            action_id, task_id, idempotency_key, attempt, status,
            worker_id, lease_generation, started_at, completed_at,
            action_type, parameters, output, verification_result, error,
            schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    query,
                    (
                        record.action_id,
                        record.task_id,
                        record.idempotency_key,
                        record.attempt,
                        record.status.value
                        if isinstance(record.status, ActionExecutionStatus)
                        else str(record.status),
                        record.worker_id,
                        record.lease_generation,
                        record.started_at.isoformat(),
                        record.completed_at.isoformat() if record.completed_at else None,
                        record.action_type,
                        json.dumps(record.parameters),
                        json.dumps(record.output) if record.output else None,
                        json.dumps(record.verification_result)
                        if record.verification_result
                        else None,
                        record.error,
                        record.schema_version,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise StorageError(
                    f"Action record collision on task '{record.task_id}', key '{record.idempotency_key}', attempt {record.attempt}: {exc}"
                ) from exc
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(f"Failed to record action attempt: {exc}") from exc

    def update_action_status(
        self,
        task_id: str,
        idempotency_key: str,
        attempt: int,
        status: ActionExecutionStatus,
        output: dict[str, Any] | None = None,
        verification_result: dict[str, Any] | None = None,
        error: str | None = None,
        completed_at: datetime | None = None,
    ) -> ActionExecutionRecord:
        now = completed_at or datetime.now(UTC)
        query = """
        UPDATE action_ledger
        SET status = ?, output = ?, verification_result = ?, error = ?, completed_at = ?
        WHERE task_id = ? AND idempotency_key = ? AND attempt = ?;
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    query,
                    (
                        status.value if isinstance(status, ActionExecutionStatus) else str(status),
                        json.dumps(output) if output else None,
                        json.dumps(verification_result) if verification_result else None,
                        error,
                        now.isoformat(),
                        task_id,
                        idempotency_key,
                        attempt,
                    ),
                )
                if cursor.rowcount == 0:
                    raise ActionNotFoundError(
                        f"Action attempt {attempt} for key '{idempotency_key}' in task '{task_id}' not found."
                    )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(f"Failed to update action status: {exc}") from exc

            record = self.get_action_record(task_id, idempotency_key, attempt)
            if record is None:
                raise ActionNotFoundError("Failed to retrieve updated action record.")
            return record

    def get_action_record(
        self, task_id: str, idempotency_key: str, attempt: int = 1
    ) -> ActionExecutionRecord | None:
        query = (
            "SELECT * FROM action_ledger WHERE task_id = ? AND idempotency_key = ? AND attempt = ?;"
        )
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (task_id, idempotency_key, attempt))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_action_record(row)

    def get_latest_action(self, task_id: str, idempotency_key: str) -> ActionExecutionRecord | None:
        query = """
        SELECT * FROM action_ledger
        WHERE task_id = ? AND idempotency_key = ?
        ORDER BY attempt DESC
        LIMIT 1;
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (task_id, idempotency_key))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_action_record(row)

    def get_task_actions(self, task_id: str) -> list[ActionExecutionRecord]:
        query = (
            "SELECT * FROM action_ledger WHERE task_id = ? ORDER BY started_at ASC, attempt ASC;"
        )
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (task_id,))
            rows = cursor.fetchall()
            return [self._row_to_action_record(r) for r in rows]

    # -------------------------------------------------------------------------
    # WorkerStoreProtocol Implementation
    # -------------------------------------------------------------------------

    def register_worker(self, worker: WorkerRecord) -> None:
        query = """
        INSERT INTO worker_registry (
            worker_id, hostname, status, capabilities, current_task_id,
            registered_at, last_heartbeat_at, metadata, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(worker_id) DO UPDATE SET
            hostname = excluded.hostname,
            status = excluded.status,
            capabilities = excluded.capabilities,
            current_task_id = excluded.current_task_id,
            last_heartbeat_at = excluded.last_heartbeat_at,
            metadata = excluded.metadata;
        """
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    query,
                    (
                        worker.worker_id,
                        worker.hostname,
                        worker.status.value
                        if isinstance(worker.status, WorkerStatus)
                        else str(worker.status),
                        json.dumps(worker.capabilities),
                        worker.current_task_id,
                        worker.registered_at.isoformat(),
                        worker.last_heartbeat_at.isoformat(),
                        json.dumps(worker.metadata),
                        worker.schema_version,
                    ),
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(
                    f"Failed to register worker '{worker.worker_id}': {exc}"
                ) from exc

    def heartbeat_worker(self, worker_id: str, status: WorkerStatus | None = None) -> None:
        now = datetime.now(UTC)
        with self._lock:
            conn = self._get_connection()
            try:
                if status:
                    conn.execute(
                        "UPDATE worker_registry SET last_heartbeat_at = ?, status = ? WHERE worker_id = ?;",
                        (
                            now.isoformat(),
                            status.value if isinstance(status, WorkerStatus) else str(status),
                            worker_id,
                        ),
                    )
                else:
                    conn.execute(
                        "UPDATE worker_registry SET last_heartbeat_at = ? WHERE worker_id = ?;",
                        (now.isoformat(), worker_id),
                    )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(f"Failed to record worker heartbeat: {exc}") from exc

    def get_worker(self, worker_id: str) -> WorkerRecord | None:
        query = "SELECT * FROM worker_registry WHERE worker_id = ?;"
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (worker_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_worker(row)

    def list_workers(self, status: WorkerStatus | None = None) -> list[WorkerRecord]:
        with self._lock:
            conn = self._get_connection()
            if status:
                query = "SELECT * FROM worker_registry WHERE status = ? ORDER BY registered_at ASC;"
                cursor = conn.execute(
                    query, (status.value if isinstance(status, WorkerStatus) else str(status),)
                )
            else:
                query = "SELECT * FROM worker_registry ORDER BY registered_at ASC;"
                cursor = conn.execute(query)
            rows = cursor.fetchall()
            return [self._row_to_worker(r) for r in rows]

    def acquire_lease(self, task_id: str, worker_id: str, ttl_seconds: float = 30.0) -> WorkerLease:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=ttl_seconds)

        with self._lock:
            conn = self._get_connection()
            try:
                # Check for existing lease
                cursor = conn.execute("SELECT * FROM worker_leases WHERE task_id = ?;", (task_id,))
                row = cursor.fetchone()

                new_generation = 1
                if row:
                    curr_lease = self._row_to_lease(row)
                    # If actively held by another worker and not expired, reject
                    if curr_lease.worker_id != worker_id and not curr_lease.is_expired(now):
                        raise StorageError(
                            f"Task '{task_id}' is actively leased to worker '{curr_lease.worker_id}' until {curr_lease.expires_at}."
                        )
                    # Increment fencing token generation
                    new_generation = curr_lease.generation + 1

                lease_id = f"lease_{uuid.uuid4().hex[:12]}"
                query = """
                INSERT INTO worker_leases (
                    lease_id, task_id, worker_id, generation, status,
                    acquired_at, expires_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    lease_id = excluded.lease_id,
                    worker_id = excluded.worker_id,
                    generation = excluded.generation,
                    status = excluded.status,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at;
                """
                conn.execute(
                    query,
                    (
                        lease_id,
                        task_id,
                        worker_id,
                        new_generation,
                        LeaseStatus.ACTIVE.value,
                        now.isoformat(),
                        expires.isoformat(),
                        "1.0",
                    ),
                )
                conn.commit()

                return WorkerLease(
                    lease_id=lease_id,
                    task_id=task_id,
                    worker_id=worker_id,
                    generation=new_generation,
                    status=LeaseStatus.ACTIVE,
                    acquired_at=now,
                    expires_at=expires,
                )
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(f"Failed to acquire lease for task '{task_id}': {exc}") from exc

    def renew_lease(self, lease_id: str, worker_id: str, ttl_seconds: float = 30.0) -> WorkerLease:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=ttl_seconds)

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT * FROM worker_leases WHERE lease_id = ?;", (lease_id,)
                )
                row = cursor.fetchone()
                if row is None:
                    raise LeaseExpiredError(f"Lease '{lease_id}' not found.")

                lease = self._row_to_lease(row)
                if lease.worker_id != worker_id:
                    raise StaleWorkerError(
                        f"Stale worker commit: lease '{lease_id}' belongs to worker '{lease.worker_id}', not '{worker_id}'."
                    )
                if lease.status != LeaseStatus.ACTIVE:
                    raise LeaseExpiredError(
                        f"Lease '{lease_id}' is not in ACTIVE status ({lease.status})."
                    )

                conn.execute(
                    "UPDATE worker_leases SET expires_at = ? WHERE lease_id = ?;",
                    (expires.isoformat(), lease_id),
                )
                conn.commit()

                lease.expires_at = expires
                return lease
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(f"Failed to renew lease '{lease_id}': {exc}") from exc

    def release_lease(self, lease_id: str, worker_id: str) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT * FROM worker_leases WHERE lease_id = ?;", (lease_id,)
                )
                row = cursor.fetchone()
                if row:
                    lease = self._row_to_lease(row)
                    if lease.worker_id == worker_id:
                        conn.execute(
                            "UPDATE worker_leases SET status = ? WHERE lease_id = ?;",
                            (LeaseStatus.RELEASED.value, lease_id),
                        )
                        conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(f"Failed to release lease '{lease_id}': {exc}") from exc

    def get_active_lease(self, task_id: str) -> WorkerLease | None:
        now = datetime.now(UTC)
        query = "SELECT * FROM worker_leases WHERE task_id = ?;"
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (task_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            lease = self._row_to_lease(row)
            if lease.is_expired(now):
                return None
            return lease

    def validate_lease_fencing(self, task_id: str, expected_generation: int) -> bool:
        """Validate whether the specified generation matches the active lease fencing token."""
        now = datetime.now(UTC)
        query = "SELECT * FROM worker_leases WHERE task_id = ?;"
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, (task_id,))
            row = cursor.fetchone()
            if row is None:
                return False
            lease = self._row_to_lease(row)
            if lease.is_expired(now):
                return False
            return lease.generation == expected_generation

    # -------------------------------------------------------------------------
    # Helper Deserializers
    # -------------------------------------------------------------------------

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        return Task(
            task_id=row["task_id"],
            objective=row["objective"],
            status=TaskStatus(row["status"]),
            priority=TaskPriority(row["priority"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            metadata=json.loads(row["metadata"]),
            current_checkpoint_id=row["current_checkpoint_id"],
            schema_version=row["schema_version"],
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> ExecutionEvent:
        return ExecutionEvent(
            event_id=row["event_id"],
            task_id=row["task_id"],
            session_id=row["session_id"],
            sequence=int(row["sequence"]),
            event_type=EventType(row["event_type"]),
            timestamp=datetime.fromisoformat(row["timestamp"]),
            payload=json.loads(row["payload"]),
            correlation_id=row["correlation_id"],
            schema_version=row["schema_version"],
        )

    @staticmethod
    def _row_to_checkpoint(row: sqlite3.Row) -> Checkpoint:
        try:
            state_val = row["state"]
            try:
                state = TaskStatus(state_val)
            except ValueError:
                state = state_val

            return Checkpoint(
                checkpoint_id=row["checkpoint_id"],
                task_id=row["task_id"],
                session_id=row["session_id"],
                worker_id=row["worker_id"],
                lease_generation=int(row["lease_generation"]),
                state=state,
                sequence=int(row["sequence"]),
                plan_id=row["plan_id"],
                plan_version=int(row["plan_version"]),
                current_step_id=row["current_step_id"],
                completed_action_ids=json.loads(row["completed_action_ids"]),
                pending_action_ids=json.loads(row["pending_action_ids"]),
                uncertain_action_ids=json.loads(row["uncertain_action_ids"]),
                last_event_sequence=int(row["last_event_sequence"]),
                state_snapshot=json.loads(row["state_snapshot"]),
                environment_metadata=json.loads(row["environment_metadata"]),
                verification_evidence_refs=json.loads(row["verification_evidence_refs"]),
                recovery_metadata=json.loads(row["recovery_metadata"]),
                metadata=json.loads(row["metadata"]),
                checkpoint_hash=row["checkpoint_hash"],
                schema_version=row["schema_version"],
                timestamp=datetime.fromisoformat(row["created_at"]),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise CorruptedCheckpointError(
                f"Failed to deserialize checkpoint '{row['checkpoint_id']}': {exc}"
            ) from exc

    @staticmethod
    def _row_to_action_record(row: sqlite3.Row) -> ActionExecutionRecord:
        return ActionExecutionRecord(
            action_id=row["action_id"],
            task_id=row["task_id"],
            idempotency_key=row["idempotency_key"],
            attempt=int(row["attempt"]),
            status=ActionExecutionStatus(row["status"]),
            worker_id=row["worker_id"],
            lease_generation=int(row["lease_generation"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"])
            if row["completed_at"]
            else None,
            action_type=row["action_type"],
            parameters=json.loads(row["parameters"]),
            output=json.loads(row["output"]) if row["output"] else None,
            verification_result=json.loads(row["verification_result"])
            if row["verification_result"]
            else None,
            error=row["error"],
            schema_version=row["schema_version"],
        )

    @staticmethod
    def _row_to_worker(row: sqlite3.Row) -> WorkerRecord:
        return WorkerRecord(
            worker_id=row["worker_id"],
            hostname=row["hostname"],
            status=WorkerStatus(row["status"]),
            capabilities=json.loads(row["capabilities"]),
            current_task_id=row["current_task_id"],
            registered_at=datetime.fromisoformat(row["registered_at"]),
            last_heartbeat_at=datetime.fromisoformat(row["last_heartbeat_at"]),
            metadata=json.loads(row["metadata"]),
            schema_version=row["schema_version"],
        )

    @staticmethod
    def _row_to_lease(row: sqlite3.Row) -> WorkerLease:
        return WorkerLease(
            lease_id=row["lease_id"],
            task_id=row["task_id"],
            worker_id=row["worker_id"],
            generation=int(row["generation"]),
            status=LeaseStatus(row["status"]),
            acquired_at=datetime.fromisoformat(row["acquired_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            schema_version=row["schema_version"],
        )


# Alias for explicit task store typing
SQLiteTaskStore = SQLiteStorage
