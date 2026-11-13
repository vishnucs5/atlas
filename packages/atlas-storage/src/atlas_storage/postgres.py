"""PostgreSQL production storage implementation, connection pooling, and schema definitions.

This module provides the enterprise-grade event-sourced storage engine for ATLAS,
implementing all five core storage protocols backed by PostgreSQL 16+.
"""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.ledger import ActionExecutionRecord, ActionExecutionStatus
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_core.contracts.worker import LeaseStatus, WorkerLease, WorkerRecord, WorkerStatus
from psycopg import errors
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field

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

POSTGRES_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id VARCHAR(64) PRIMARY KEY,
    objective TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    priority VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_checkpoint_id VARCHAR(64),
    schema_version VARCHAR(16) NOT NULL DEFAULT '1.0'
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);

CREATE TABLE IF NOT EXISTS execution_events (
    event_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    session_id VARCHAR(64),
    sequence BIGINT NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    correlation_id VARCHAR(64) NOT NULL,
    schema_version VARCHAR(16) NOT NULL DEFAULT '1.0',
    CONSTRAINT uq_task_sequence UNIQUE (task_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_events_task_seq ON execution_events(task_id, sequence);
CREATE INDEX IF NOT EXISTS idx_events_correlation ON execution_events(correlation_id);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    session_id VARCHAR(64),
    worker_id VARCHAR(64),
    lease_generation BIGINT NOT NULL DEFAULT 1,
    state VARCHAR(32) NOT NULL,
    sequence BIGINT NOT NULL DEFAULT 0,
    plan_id VARCHAR(64),
    plan_version INT NOT NULL DEFAULT 1,
    current_step_id VARCHAR(64),
    completed_action_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    pending_action_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    uncertain_action_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_event_sequence BIGINT NOT NULL DEFAULT 0,
    state_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    environment_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    verification_evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    recovery_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    checkpoint_hash VARCHAR(128),
    schema_version VARCHAR(16) NOT NULL DEFAULT '1.0',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_task ON checkpoints(task_id, created_at);

CREATE TABLE IF NOT EXISTS action_ledger (
    action_id VARCHAR(64) NOT NULL,
    task_id VARCHAR(64) NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    idempotency_key VARCHAR(128) NOT NULL,
    attempt INT NOT NULL DEFAULT 1,
    status VARCHAR(32) NOT NULL,
    worker_id VARCHAR(64) NOT NULL,
    lease_generation BIGINT NOT NULL DEFAULT 1,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    action_type VARCHAR(64) NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    output JSONB,
    verification_result JSONB,
    error JSONB,
    schema_version VARCHAR(16) NOT NULL DEFAULT '1.0',
    PRIMARY KEY (task_id, idempotency_key, attempt)
);

CREATE INDEX IF NOT EXISTS idx_ledger_action_id ON action_ledger(action_id);
CREATE INDEX IF NOT EXISTS idx_ledger_task_status ON action_ledger(task_id, status);

CREATE TABLE IF NOT EXISTS worker_registry (
    worker_id VARCHAR(64) PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    current_task_id VARCHAR(64),
    registered_at TIMESTAMPTZ NOT NULL,
    last_heartbeat_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    schema_version VARCHAR(16) NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS worker_leases (
    lease_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL UNIQUE REFERENCES tasks(task_id) ON DELETE CASCADE,
    worker_id VARCHAR(64) NOT NULL REFERENCES worker_registry(worker_id),
    generation BIGINT NOT NULL DEFAULT 1,
    status VARCHAR(32) NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    schema_version VARCHAR(16) NOT NULL DEFAULT '1.0'
);

CREATE INDEX IF NOT EXISTS idx_leases_worker ON worker_leases(worker_id);
"""


class PostgresConfig(BaseModel):
    """Configuration settings for PostgreSQL connection pooling and runtime."""

    model_config = ConfigDict(validate_assignment=True)

    host: str = "localhost"
    port: int = 5432
    database: str = "atlas"
    user: str = "atlas_user"
    password: str = Field(default="", repr=False)
    min_pool_size: int = 1
    max_pool_size: int = 20
    connect_timeout_seconds: float = 10.0
    ssl_mode: str = "prefer"
    application_name: str = "atlas-orchestrator"


class PostgresStorageSpec:
    """Specification describing PostgreSQL schema, connection pooling, and DDL."""

    def __init__(self, config: PostgresConfig | None = None) -> None:
        self.config = config or PostgresConfig()

    @property
    def dsn(self) -> str:
        """Construct database connection string."""
        auth = f"{self.config.user}"
        if self.config.password:
            auth += f":{self.config.password}"
        return f"postgresql://{auth}@{self.config.host}:{self.config.port}/{self.config.database}"

    def get_schema_ddl(self) -> str:
        """Return production relational schema DDL for PostgreSQL."""
        return POSTGRES_SCHEMA_DDL


class PostgresStorage(
    TaskStoreProtocol,
    EventStoreProtocol,
    CheckpointStoreProtocol,
    ActionLedgerStoreProtocol,
    WorkerStoreProtocol,
):
    """Production-grade event-sourced storage engine backed by PostgreSQL."""

    def __init__(
        self,
        dsn_or_config: str | PostgresConfig | None = None,
        config: PostgresConfig | None = None,
        min_pool_size: int = 1,
        max_pool_size: int = 20,
        timeout: float = 10.0,
    ) -> None:
        cfg = config or (dsn_or_config if isinstance(dsn_or_config, PostgresConfig) else None)
        if cfg:
            self.config = cfg
            self.dsn = PostgresStorageSpec(self.config).dsn
        elif isinstance(dsn_or_config, str):
            self.dsn = dsn_or_config
            self.config = PostgresConfig()
        else:
            env_url = os.getenv("ATLAS_DATABASE_URL")
            if env_url:
                self.dsn = env_url
                self.config = PostgresConfig()
            else:
                self.config = PostgresConfig()
                self.dsn = PostgresStorageSpec(self.config).dsn

        self.spec = PostgresStorageSpec(self.config)
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self.timeout = timeout if timeout is not None else self.config.connect_timeout_seconds
        self._is_open = False

        self.pool = ConnectionPool(
            conninfo=self.dsn,
            min_size=self.min_pool_size,
            max_size=self.max_pool_size,
            timeout=self.timeout,
            open=False,
            kwargs={"autocommit": False},
        )

    def initialize(self) -> None:
        """Initialize connection pool, verify connectivity, and apply schema DDL."""
        try:
            if not self._is_open:
                self.pool.open()
                self._is_open = True

            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    cur.execute(self.spec.get_schema_ddl())
                conn.commit()
        except Exception as exc:
            raise StorageError(
                f"Failed to connect to PostgreSQL database at '{self.dsn}': {exc}"
            ) from exc

    def close(self) -> None:
        """Close connection pool and release resources."""
        if self._is_open:
            try:
                self.pool.close()
            finally:
                self._is_open = False

    def __enter__(self) -> "PostgresStorage":
        self.initialize()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # -------------------------------------------------------------------------
    # TaskStoreProtocol
    # -------------------------------------------------------------------------

    def save_task(self, task: Task) -> None:
        """Persist or overwrite a materialized task record."""
        query = """
        INSERT INTO tasks (
            task_id, objective, status, priority, created_at, updated_at,
            metadata, current_checkpoint_id, schema_version
        ) VALUES (
            %(task_id)s, %(objective)s, %(status)s, %(priority)s, %(created_at)s, %(updated_at)s,
            %(metadata)s::jsonb, %(current_checkpoint_id)s, %(schema_version)s
        )
        ON CONFLICT (task_id) DO UPDATE SET
            objective = EXCLUDED.objective,
            status = EXCLUDED.status,
            priority = EXCLUDED.priority,
            updated_at = EXCLUDED.updated_at,
            metadata = EXCLUDED.metadata,
            current_checkpoint_id = EXCLUDED.current_checkpoint_id,
            schema_version = EXCLUDED.schema_version;
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        {
                            "task_id": task.task_id,
                            "objective": task.objective,
                            "status": task.status.value
                            if isinstance(task.status, TaskStatus)
                            else str(task.status),
                            "priority": task.priority.value
                            if isinstance(task.priority, TaskPriority)
                            else str(task.priority),
                            "created_at": task.created_at,
                            "updated_at": task.updated_at,
                            "metadata": json.dumps(task.metadata),
                            "current_checkpoint_id": task.current_checkpoint_id,
                            "schema_version": task.schema_version,
                        },
                    )
                conn.commit()
        except Exception as exc:
            raise StorageError(f"Failed to save task '{task.task_id}': {exc}") from exc

    def get_task(self, task_id: str) -> Task | None:
        """Retrieve a task by its unique identifier."""
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("SELECT * FROM tasks WHERE task_id = %s;", (task_id,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    return self._row_to_task(row)
        except Exception as exc:
            raise StorageError(f"Failed to retrieve task '{task_id}': {exc}") from exc

    def update_task_status(
        self,
        task_id: str,
        new_status: TaskStatus,
        expected_status: TaskStatus | None = None,
    ) -> Task:
        """Update task status with optimistic concurrency control."""
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("SELECT * FROM tasks WHERE task_id = %s FOR UPDATE;", (task_id,))
                    row = cur.fetchone()
                    if not row:
                        raise TaskNotFoundError(f"Task with ID '{task_id}' not found.")

                    current = self._row_to_task(row)
                    if expected_status is not None and current.status != expected_status:
                        raise OptimisticLockError(
                            f"Optimistic lock conflict for task '{task_id}': "
                            f"expected status '{expected_status}', found '{current.status}'."
                        )

                    now = datetime.now(UTC)
                    status_str = (
                        new_status.value if isinstance(new_status, TaskStatus) else str(new_status)
                    )
                    cur.execute(
                        "UPDATE tasks SET status = %s, updated_at = %s WHERE task_id = %s;",
                        (status_str, now, task_id),
                    )
                conn.commit()

            updated = self.get_task(task_id)
            if not updated:
                raise TaskNotFoundError(f"Task with ID '{task_id}' not found after update.")
            return updated
        except (TaskNotFoundError, OptimisticLockError):
            raise
        except Exception as exc:
            raise StorageError(f"Failed to update status for task '{task_id}': {exc}") from exc

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks with optional status filter and pagination."""
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    if status is not None:
                        status_str = status.value if isinstance(status, TaskStatus) else str(status)
                        cur.execute(
                            "SELECT * FROM tasks WHERE status = %s ORDER BY created_at DESC LIMIT %s OFFSET %s;",
                            (status_str, limit, offset),
                        )
                    else:
                        cur.execute(
                            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT %s OFFSET %s;",
                            (limit, offset),
                        )
                    rows = cur.fetchall()
                    return [self._row_to_task(r) for r in rows]
        except Exception as exc:
            raise StorageError(f"Failed to list tasks: {exc}") from exc

    # -------------------------------------------------------------------------
    # EventStoreProtocol
    # -------------------------------------------------------------------------

    def append_event(self, event: ExecutionEvent) -> None:
        """Append an immutable event to the event stream."""
        query = """
        INSERT INTO execution_events (
            event_id, task_id, session_id, sequence, event_type, timestamp,
            payload, correlation_id, schema_version
        ) VALUES (
            %(event_id)s, %(task_id)s, %(session_id)s, %(sequence)s, %(event_type)s, %(timestamp)s,
            %(payload)s::jsonb, %(correlation_id)s, %(schema_version)s
        );
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        {
                            "event_id": event.event_id,
                            "task_id": event.task_id,
                            "session_id": event.session_id,
                            "sequence": event.sequence,
                            "event_type": event.event_type.value
                            if isinstance(event.event_type, EventType)
                            else str(event.event_type),
                            "timestamp": event.timestamp,
                            "payload": json.dumps(event.payload),
                            "correlation_id": event.correlation_id,
                            "schema_version": event.schema_version,
                        },
                    )
                conn.commit()
        except errors.UniqueViolation as exc:
            raise SequenceCollisionError(
                f"Sequence collision for task '{event.task_id}' at sequence {event.sequence}."
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"Failed to append event '{event.event_id}' for task '{event.task_id}': {exc}"
            ) from exc

    def append_events(self, events: list[ExecutionEvent]) -> None:
        """Batch append multiple events atomically in a single transaction."""
        if not events:
            return
        query = """
        INSERT INTO execution_events (
            event_id, task_id, session_id, sequence, event_type, timestamp,
            payload, correlation_id, schema_version
        ) VALUES (
            %(event_id)s, %(task_id)s, %(session_id)s, %(sequence)s, %(event_type)s, %(timestamp)s,
            %(payload)s::jsonb, %(correlation_id)s, %(schema_version)s
        );
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    for event in events:
                        cur.execute(
                            query,
                            {
                                "event_id": event.event_id,
                                "task_id": event.task_id,
                                "session_id": event.session_id,
                                "sequence": event.sequence,
                                "event_type": event.event_type.value
                                if isinstance(event.event_type, EventType)
                                else str(event.event_type),
                                "timestamp": event.timestamp,
                                "payload": json.dumps(event.payload),
                                "correlation_id": event.correlation_id,
                                "schema_version": event.schema_version,
                            },
                        )
                conn.commit()
        except errors.UniqueViolation as exc:
            raise SequenceCollisionError(
                "Sequence collision detected during batch event appending."
            ) from exc
        except Exception as exc:
            raise StorageError(f"Failed to batch append events: {exc}") from exc

    def get_events(
        self,
        task_id: str,
        since_sequence: int = 0,
    ) -> list[ExecutionEvent]:
        """Retrieve events for a given task, ordered strictly by sequence number."""
        query = """
        SELECT * FROM execution_events
        WHERE task_id = %s AND sequence > %s
        ORDER BY sequence ASC;
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (task_id, since_sequence))
                    rows = cur.fetchall()
                    return [self._row_to_event(r) for r in rows]
        except Exception as exc:
            raise StorageError(f"Failed to retrieve events for task '{task_id}': {exc}") from exc

    def get_latest_event(self, task_id: str) -> ExecutionEvent | None:
        """Retrieve the event with the highest sequence number for a given task."""
        query = """
        SELECT * FROM execution_events
        WHERE task_id = %s
        ORDER BY sequence DESC
        LIMIT 1;
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (task_id,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    return self._row_to_event(row)
        except Exception as exc:
            raise StorageError(
                f"Failed to retrieve latest event for task '{task_id}': {exc}"
            ) from exc

    def get_latest_sequence(self, task_id: str) -> int:
        """Retrieve the highest sequence number recorded for a task (0 if none exist)."""
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COALESCE(MAX(sequence), 0) FROM execution_events WHERE task_id = %s;",
                        (task_id,),
                    )
                    row = cur.fetchone()
                    return int(row[0]) if row and row[0] is not None else 0
        except Exception as exc:
            raise StorageError(
                f"Failed to get latest sequence for task '{task_id}': {exc}"
            ) from exc

    # -------------------------------------------------------------------------
    # CheckpointStoreProtocol
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
        ) VALUES (
            %(checkpoint_id)s, %(task_id)s, %(session_id)s, %(worker_id)s, %(lease_generation)s,
            %(state)s, %(sequence)s, %(plan_id)s, %(plan_version)s, %(current_step_id)s,
            %(completed_action_ids)s::jsonb, %(pending_action_ids)s::jsonb, %(uncertain_action_ids)s::jsonb,
            %(last_event_sequence)s, %(state_snapshot)s::jsonb, %(environment_metadata)s::jsonb,
            %(verification_evidence_refs)s::jsonb, %(recovery_metadata)s::jsonb, %(metadata)s::jsonb,
            %(checkpoint_hash)s, %(schema_version)s, %(created_at)s
        )
        ON CONFLICT (checkpoint_id) DO UPDATE SET
            state = EXCLUDED.state,
            sequence = EXCLUDED.sequence,
            lease_generation = EXCLUDED.lease_generation,
            plan_id = EXCLUDED.plan_id,
            plan_version = EXCLUDED.plan_version,
            current_step_id = EXCLUDED.current_step_id,
            completed_action_ids = EXCLUDED.completed_action_ids,
            pending_action_ids = EXCLUDED.pending_action_ids,
            uncertain_action_ids = EXCLUDED.uncertain_action_ids,
            last_event_sequence = EXCLUDED.last_event_sequence,
            state_snapshot = EXCLUDED.state_snapshot,
            environment_metadata = EXCLUDED.environment_metadata,
            verification_evidence_refs = EXCLUDED.verification_evidence_refs,
            recovery_metadata = EXCLUDED.recovery_metadata,
            metadata = EXCLUDED.metadata,
            checkpoint_hash = EXCLUDED.checkpoint_hash;
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        {
                            "checkpoint_id": checkpoint.checkpoint_id,
                            "task_id": checkpoint.task_id,
                            "session_id": checkpoint.session_id,
                            "worker_id": checkpoint.worker_id,
                            "lease_generation": checkpoint.lease_generation,
                            "state": checkpoint.state.value
                            if isinstance(checkpoint.state, TaskStatus)
                            else str(checkpoint.state),
                            "sequence": checkpoint.sequence,
                            "plan_id": checkpoint.plan_id,
                            "plan_version": checkpoint.plan_version,
                            "current_step_id": checkpoint.current_step_id,
                            "completed_action_ids": json.dumps(checkpoint.completed_action_ids),
                            "pending_action_ids": json.dumps(checkpoint.pending_action_ids),
                            "uncertain_action_ids": json.dumps(checkpoint.uncertain_action_ids),
                            "last_event_sequence": checkpoint.last_event_sequence,
                            "state_snapshot": json.dumps(checkpoint.state_snapshot),
                            "environment_metadata": json.dumps(checkpoint.environment_metadata),
                            "verification_evidence_refs": json.dumps(
                                checkpoint.verification_evidence_refs
                            ),
                            "recovery_metadata": json.dumps(checkpoint.recovery_metadata),
                            "metadata": json.dumps(checkpoint.metadata),
                            "checkpoint_hash": checkpoint.checkpoint_hash,
                            "schema_version": checkpoint.schema_version,
                            "created_at": checkpoint.timestamp,
                        },
                    )
                    cur.execute(
                        "UPDATE tasks SET current_checkpoint_id = %s WHERE task_id = %s;",
                        (checkpoint.checkpoint_id, checkpoint.task_id),
                    )
                conn.commit()
        except Exception as exc:
            raise StorageError(
                f"Failed to save checkpoint '{checkpoint.checkpoint_id}': {exc}"
            ) from exc

    def get_checkpoint(self, checkpoint_id: str, verify: bool = True) -> Checkpoint | None:
        """Retrieve a checkpoint by its unique ID, verifying cryptographic integrity."""
        query = "SELECT * FROM checkpoints WHERE checkpoint_id = %s;"
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (checkpoint_id,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    chk = self._row_to_checkpoint(row)
                    if verify and chk.checkpoint_hash:
                        computed = chk.compute_hash()
                        if computed != chk.checkpoint_hash:
                            raise CorruptedCheckpointError(
                                f"Cryptographic checksum mismatch for checkpoint '{checkpoint_id}': "
                                f"expected '{chk.checkpoint_hash}', computed '{computed}'."
                            )
                    return chk
        except CorruptedCheckpointError:
            raise
        except Exception as exc:
            raise StorageError(f"Failed to retrieve checkpoint '{checkpoint_id}': {exc}") from exc

    def get_latest_checkpoint(self, task_id: str, verify: bool = True) -> Checkpoint | None:
        """Retrieve the most recent checkpoint recorded for a task."""
        query = """
        SELECT * FROM checkpoints
        WHERE task_id = %s
        ORDER BY created_at DESC, sequence DESC
        LIMIT 1;
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (task_id,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    chk = self._row_to_checkpoint(row)
                    if verify and chk.checkpoint_hash:
                        computed = chk.compute_hash()
                        if computed != chk.checkpoint_hash:
                            raise CorruptedCheckpointError(
                                f"Cryptographic checksum mismatch for checkpoint '{chk.checkpoint_id}'."
                            )
                    return chk
        except CorruptedCheckpointError:
            raise
        except Exception as exc:
            raise StorageError(
                f"Failed to retrieve latest checkpoint for task '{task_id}': {exc}"
            ) from exc

    def list_checkpoints(self, task_id: str, limit: int = 50) -> list[Checkpoint]:
        """List checkpoints for a task ordered from newest to oldest."""
        query = """
        SELECT * FROM checkpoints
        WHERE task_id = %s
        ORDER BY created_at DESC, sequence DESC
        LIMIT %s;
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (task_id, limit))
                    rows = cur.fetchall()
                    return [self._row_to_checkpoint(r) for r in rows]
        except Exception as exc:
            raise StorageError(f"Failed to list checkpoints for task '{task_id}': {exc}") from exc

    # -------------------------------------------------------------------------
    # ActionLedgerStoreProtocol
    # -------------------------------------------------------------------------

    def record_action_attempt(self, record: ActionExecutionRecord) -> None:
        """Record an initial or retried action execution attempt."""
        query = """
        INSERT INTO action_ledger (
            action_id, task_id, idempotency_key, attempt, status,
            worker_id, lease_generation, started_at, completed_at,
            action_type, parameters, output, verification_result, error, schema_version
        ) VALUES (
            %(action_id)s, %(task_id)s, %(idempotency_key)s, %(attempt)s, %(status)s,
            %(worker_id)s, %(lease_generation)s, %(started_at)s, %(completed_at)s,
            %(action_type)s, %(parameters)s::jsonb, %(output)s::jsonb,
            %(verification_result)s::jsonb, %(error)s::jsonb, %(schema_version)s
        )
        ON CONFLICT (task_id, idempotency_key, attempt) DO UPDATE SET
            status = EXCLUDED.status,
            completed_at = EXCLUDED.completed_at,
            output = EXCLUDED.output,
            verification_result = EXCLUDED.verification_result,
            error = EXCLUDED.error;
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        {
                            "action_id": record.action_id,
                            "task_id": record.task_id,
                            "idempotency_key": record.idempotency_key,
                            "attempt": record.attempt,
                            "status": record.status.value
                            if isinstance(record.status, ActionExecutionStatus)
                            else str(record.status),
                            "worker_id": record.worker_id,
                            "lease_generation": record.lease_generation,
                            "started_at": record.started_at,
                            "completed_at": record.completed_at,
                            "action_type": record.action_type,
                            "parameters": json.dumps(record.parameters),
                            "output": json.dumps(record.output)
                            if record.output is not None
                            else None,
                            "verification_result": json.dumps(record.verification_result)
                            if record.verification_result is not None
                            else None,
                            "error": json.dumps({"error": record.error})
                            if record.error is not None
                            else None,
                            "schema_version": record.schema_version,
                        },
                    )
                conn.commit()
        except Exception as exc:
            raise StorageError(
                f"Failed to record action attempt for action '{record.action_id}': {exc}"
            ) from exc

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
        """Update action execution status and verification outcome."""
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        """
                        SELECT * FROM action_ledger
                        WHERE task_id = %s AND idempotency_key = %s AND attempt = %s
                        FOR UPDATE;
                        """,
                        (task_id, idempotency_key, attempt),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise ActionNotFoundError(
                            f"Action execution record not found for task '{task_id}', "
                            f"key '{idempotency_key}', attempt {attempt}."
                        )

                    completed = completed_at or datetime.now(UTC)
                    status_str = (
                        status.value if isinstance(status, ActionExecutionStatus) else str(status)
                    )
                    cur.execute(
                        """
                        UPDATE action_ledger
                        SET status = %s,
                            output = %s::jsonb,
                            verification_result = %s::jsonb,
                            error = %s::jsonb,
                            completed_at = %s
                        WHERE task_id = %s AND idempotency_key = %s AND attempt = %s;
                        """,
                        (
                            status_str,
                            json.dumps(output) if output is not None else None,
                            json.dumps(verification_result)
                            if verification_result is not None
                            else None,
                            json.dumps({"error": error}) if error is not None else None,
                            completed,
                            task_id,
                            idempotency_key,
                            attempt,
                        ),
                    )
                conn.commit()

            record = self.get_action_record(task_id, idempotency_key, attempt)
            if not record:
                raise ActionNotFoundError("Action record not found after update.")
            return record
        except ActionNotFoundError:
            raise
        except Exception as exc:
            raise StorageError(
                f"Failed to update action status for task '{task_id}': {exc}"
            ) from exc

    def get_action_record(
        self, task_id: str, idempotency_key: str, attempt: int = 1
    ) -> ActionExecutionRecord | None:
        """Retrieve an action execution record."""
        query = """
        SELECT * FROM action_ledger
        WHERE task_id = %s AND idempotency_key = %s AND attempt = %s;
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (task_id, idempotency_key, attempt))
                    row = cur.fetchone()
                    if not row:
                        return None
                    return self._row_to_action_record(row)
        except Exception as exc:
            raise StorageError(
                f"Failed to retrieve action record for task '{task_id}': {exc}"
            ) from exc

    def get_latest_action(self, task_id: str, idempotency_key: str) -> ActionExecutionRecord | None:
        """Retrieve the latest attempt for an action by idempotency key."""
        query = """
        SELECT * FROM action_ledger
        WHERE task_id = %s AND idempotency_key = %s
        ORDER BY attempt DESC
        LIMIT 1;
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (task_id, idempotency_key))
                    row = cur.fetchone()
                    if not row:
                        return None
                    return self._row_to_action_record(row)
        except Exception as exc:
            raise StorageError(
                f"Failed to retrieve latest action for task '{task_id}': {exc}"
            ) from exc

    def get_task_actions(self, task_id: str) -> list[ActionExecutionRecord]:
        """Retrieve all action execution records for a task."""
        query = """
        SELECT * FROM action_ledger
        WHERE task_id = %s
        ORDER BY started_at ASC, attempt ASC;
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (task_id,))
                    rows = cur.fetchall()
                    return [self._row_to_action_record(r) for r in rows]
        except Exception as exc:
            raise StorageError(f"Failed to get task actions for task '{task_id}': {exc}") from exc

    # -------------------------------------------------------------------------
    # WorkerStoreProtocol
    # -------------------------------------------------------------------------

    def register_worker(self, worker: WorkerRecord) -> None:
        """Register a worker in the worker registry."""
        query = """
        INSERT INTO worker_registry (
            worker_id, hostname, status, capabilities, current_task_id,
            registered_at, last_heartbeat_at, metadata, schema_version
        ) VALUES (
            %(worker_id)s, %(hostname)s, %(status)s, %(capabilities)s::jsonb, %(current_task_id)s,
            %(registered_at)s, %(last_heartbeat_at)s, %(metadata)s::jsonb, %(schema_version)s
        )
        ON CONFLICT (worker_id) DO UPDATE SET
            hostname = EXCLUDED.hostname,
            status = EXCLUDED.status,
            capabilities = EXCLUDED.capabilities,
            current_task_id = EXCLUDED.current_task_id,
            last_heartbeat_at = EXCLUDED.last_heartbeat_at,
            metadata = EXCLUDED.metadata;
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        {
                            "worker_id": worker.worker_id,
                            "hostname": worker.hostname,
                            "status": worker.status.value
                            if isinstance(worker.status, WorkerStatus)
                            else str(worker.status),
                            "capabilities": json.dumps(worker.capabilities),
                            "current_task_id": worker.current_task_id,
                            "registered_at": worker.registered_at,
                            "last_heartbeat_at": worker.last_heartbeat_at,
                            "metadata": json.dumps(worker.metadata),
                            "schema_version": worker.schema_version,
                        },
                    )
                conn.commit()
        except Exception as exc:
            raise StorageError(f"Failed to register worker '{worker.worker_id}': {exc}") from exc

    def heartbeat_worker(self, worker_id: str, status: WorkerStatus | None = None) -> None:
        """Record a heartbeat timestamp and optional status update for a worker."""
        now = datetime.now(UTC)
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    if status is not None:
                        status_str = (
                            status.value if isinstance(status, WorkerStatus) else str(status)
                        )
                        cur.execute(
                            "UPDATE worker_registry SET last_heartbeat_at = %s, status = %s WHERE worker_id = %s;",
                            (now, status_str, worker_id),
                        )
                    else:
                        cur.execute(
                            "UPDATE worker_registry SET last_heartbeat_at = %s WHERE worker_id = %s;",
                            (now, worker_id),
                        )
                conn.commit()
        except Exception as exc:
            raise StorageError(
                f"Failed to record heartbeat for worker '{worker_id}': {exc}"
            ) from exc

    def get_worker(self, worker_id: str) -> WorkerRecord | None:
        """Retrieve a worker record by worker ID."""
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT * FROM worker_registry WHERE worker_id = %s;",
                        (worker_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                    return self._row_to_worker(row)
        except Exception as exc:
            raise StorageError(f"Failed to retrieve worker '{worker_id}': {exc}") from exc

    def list_workers(self, status: WorkerStatus | None = None) -> list[WorkerRecord]:
        """List workers with optional status filter."""
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    if status is not None:
                        status_str = (
                            status.value if isinstance(status, WorkerStatus) else str(status)
                        )
                        cur.execute(
                            "SELECT * FROM worker_registry WHERE status = %s ORDER BY registered_at ASC;",
                            (status_str,),
                        )
                    else:
                        cur.execute("SELECT * FROM worker_registry ORDER BY registered_at ASC;")
                    rows = cur.fetchall()
                    return [self._row_to_worker(r) for r in rows]
        except Exception as exc:
            raise StorageError(f"Failed to list workers: {exc}") from exc

    def acquire_lease(
        self,
        task_id: str,
        worker_id: str,
        ttl_seconds: float = 30.0,
    ) -> WorkerLease:
        """Acquire an exclusive task lease, incrementing generation fencing token."""
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)

        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT * FROM worker_leases WHERE task_id = %s FOR UPDATE;",
                        (task_id,),
                    )
                    existing = cur.fetchone()

                    if existing:
                        current_lease = self._row_to_lease(existing)
                        if current_lease.worker_id != worker_id and not current_lease.is_expired(
                            now
                        ):
                            raise StorageError(
                                f"Task '{task_id}' is actively leased to worker '{current_lease.worker_id}' "
                                f"until {current_lease.expires_at}."
                            )

                        new_generation = current_lease.generation + 1
                        lease_id = current_lease.lease_id
                        cur.execute(
                            """
                            UPDATE worker_leases
                            SET worker_id = %s,
                                generation = %s,
                                status = %s,
                                acquired_at = %s,
                                expires_at = %s
                            WHERE task_id = %s;
                            """,
                            (
                                worker_id,
                                new_generation,
                                LeaseStatus.ACTIVE.value,
                                now,
                                expires_at,
                                task_id,
                            ),
                        )
                    else:
                        lease_id = str(uuid.uuid4())
                        new_generation = 1
                        cur.execute(
                            """
                            INSERT INTO worker_leases (
                                lease_id, task_id, worker_id, generation, status,
                                acquired_at, expires_at, schema_version
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, '1.0'
                            );
                            """,
                            (
                                lease_id,
                                task_id,
                                worker_id,
                                new_generation,
                                LeaseStatus.ACTIVE.value,
                                now,
                                expires_at,
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
                expires_at=expires_at,
                schema_version="1.0",
            )
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(
                f"Failed to acquire lease on task '{task_id}' for worker '{worker_id}': {exc}"
            ) from exc

    def renew_lease(
        self,
        lease_id: str,
        worker_id: str,
        ttl_seconds: float = 30.0,
    ) -> WorkerLease:
        """Renew an existing active task lease."""
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)

        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT * FROM worker_leases WHERE lease_id = %s FOR UPDATE;",
                        (lease_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise StorageError(f"Worker lease '{lease_id}' not found.")

                    lease = self._row_to_lease(row)
                    if lease.worker_id != worker_id:
                        raise StorageError(
                            f"Worker '{worker_id}' does not own lease '{lease_id}' (owned by '{lease.worker_id}')."
                        )
                    if lease.is_expired(now):
                        raise LeaseExpiredError(f"Worker lease '{lease_id}' has expired.")

                    cur.execute(
                        "UPDATE worker_leases SET expires_at = %s WHERE lease_id = %s;",
                        (expires_at, lease_id),
                    )
                conn.commit()

            return WorkerLease(
                lease_id=lease.lease_id,
                task_id=lease.task_id,
                worker_id=lease.worker_id,
                generation=lease.generation,
                status=lease.status,
                acquired_at=lease.acquired_at,
                expires_at=expires_at,
                schema_version=lease.schema_version,
            )
        except (StorageError, LeaseExpiredError):
            raise
        except Exception as exc:
            raise StorageError(
                f"Failed to renew lease '{lease_id}' for worker '{worker_id}': {exc}"
            ) from exc

    def release_lease(self, lease_id: str, worker_id: str) -> None:
        """Explicitly release an active task lease."""
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE worker_leases SET status = %s WHERE lease_id = %s AND worker_id = %s;",
                        (LeaseStatus.RELEASED.value, lease_id, worker_id),
                    )
                conn.commit()
        except Exception as exc:
            raise StorageError(
                f"Failed to release lease '{lease_id}' for worker '{worker_id}': {exc}"
            ) from exc

    def get_active_lease(self, task_id: str) -> WorkerLease | None:
        """Retrieve the active lease for a task if not expired."""
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("SELECT * FROM worker_leases WHERE task_id = %s;", (task_id,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    lease = self._row_to_lease(row)
                    now = datetime.now(UTC)
                    return None if lease.is_expired(now) else lease
        except Exception as exc:
            raise StorageError(f"Failed to get active lease for task '{task_id}': {exc}") from exc

    def validate_lease_fencing(
        self,
        task_id: str,
        expected_generation: int,
    ) -> bool:
        """Validate whether the specified generation matches the active lease fencing token."""
        try:
            with self.pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("SELECT * FROM worker_leases WHERE task_id = %s;", (task_id,))
                    row = cur.fetchone()
                    if not row:
                        return True
                    lease = self._row_to_lease(row)
                    if lease.generation != expected_generation:
                        raise StaleWorkerError(
                            f"Stale worker commit rejected: lease generation {lease.generation} "
                            f"exceeds expected generation {expected_generation}."
                        )
                    return True
        except StaleWorkerError:
            raise
        except Exception as exc:
            raise StorageError(
                f"Failed to validate lease fencing for task '{task_id}': {exc}"
            ) from exc

    # -------------------------------------------------------------------------
    # Row Deserializers
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_datetime(dt_val: Any) -> datetime:
        if isinstance(dt_val, datetime):
            return dt_val
        return datetime.fromisoformat(str(dt_val))

    @staticmethod
    def _parse_json(json_val: Any, default: Any = None) -> Any:
        if json_val is None:
            return default
        if isinstance(json_val, (dict, list)):
            return json_val
        try:
            return json.loads(str(json_val))
        except (json.JSONDecodeError, TypeError):
            return default

    @classmethod
    def _row_to_task(cls, row: dict[str, Any]) -> Task:
        return Task(
            task_id=row["task_id"],
            objective=row["objective"],
            status=TaskStatus(row["status"]),
            priority=TaskPriority(row["priority"]),
            created_at=cls._parse_datetime(row["created_at"]),
            updated_at=cls._parse_datetime(row["updated_at"]),
            metadata=cls._parse_json(row["metadata"], {}),
            current_checkpoint_id=row["current_checkpoint_id"],
            schema_version=row["schema_version"],
        )

    @classmethod
    def _row_to_event(cls, row: dict[str, Any]) -> ExecutionEvent:
        return ExecutionEvent(
            event_id=row["event_id"],
            task_id=row["task_id"],
            session_id=row["session_id"],
            sequence=int(row["sequence"]),
            event_type=EventType(row["event_type"]),
            timestamp=cls._parse_datetime(row["timestamp"]),
            payload=cls._parse_json(row["payload"], {}),
            correlation_id=row["correlation_id"],
            schema_version=row["schema_version"],
        )

    @classmethod
    def _row_to_checkpoint(cls, row: dict[str, Any]) -> Checkpoint:
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
            completed_action_ids=cls._parse_json(row["completed_action_ids"], []),
            pending_action_ids=cls._parse_json(row["pending_action_ids"], []),
            uncertain_action_ids=cls._parse_json(row["uncertain_action_ids"], []),
            last_event_sequence=int(row["last_event_sequence"]),
            state_snapshot=cls._parse_json(row["state_snapshot"], {}),
            environment_metadata=cls._parse_json(row["environment_metadata"], {}),
            verification_evidence_refs=cls._parse_json(row["verification_evidence_refs"], []),
            recovery_metadata=cls._parse_json(row["recovery_metadata"], {}),
            metadata=cls._parse_json(row["metadata"], {}),
            checkpoint_hash=row["checkpoint_hash"],
            schema_version=row["schema_version"],
            timestamp=cls._parse_datetime(row["created_at"]),
        )

    @classmethod
    def _row_to_action_record(cls, row: dict[str, Any]) -> ActionExecutionRecord:
        err_data = cls._parse_json(row["error"], None)
        err_str = None
        if isinstance(err_data, dict) and "error" in err_data:
            err_str = err_data["error"]
        elif isinstance(err_data, str):
            err_str = err_data

        return ActionExecutionRecord(
            action_id=row["action_id"],
            task_id=row["task_id"],
            idempotency_key=row["idempotency_key"],
            attempt=int(row["attempt"]),
            status=ActionExecutionStatus(row["status"]),
            worker_id=row["worker_id"],
            lease_generation=int(row["lease_generation"]),
            started_at=cls._parse_datetime(row["started_at"]),
            completed_at=cls._parse_datetime(row["completed_at"]) if row["completed_at"] else None,
            action_type=row["action_type"],
            parameters=cls._parse_json(row["parameters"], {}),
            output=cls._parse_json(row["output"], None),
            verification_result=cls._parse_json(row["verification_result"], None),
            error=err_str,
            schema_version=row["schema_version"],
        )

    @classmethod
    def _row_to_worker(cls, row: dict[str, Any]) -> WorkerRecord:
        return WorkerRecord(
            worker_id=row["worker_id"],
            hostname=row["hostname"],
            status=WorkerStatus(row["status"]),
            capabilities=cls._parse_json(row["capabilities"], []),
            current_task_id=row["current_task_id"],
            registered_at=cls._parse_datetime(row["registered_at"]),
            last_heartbeat_at=cls._parse_datetime(row["last_heartbeat_at"]),
            metadata=cls._parse_json(row["metadata"], {}),
            schema_version=row["schema_version"],
        )

    @classmethod
    def _row_to_lease(cls, row: dict[str, Any]) -> WorkerLease:
        return WorkerLease(
            lease_id=row["lease_id"],
            task_id=row["task_id"],
            worker_id=row["worker_id"],
            generation=int(row["generation"]),
            status=LeaseStatus(row["status"]),
            acquired_at=cls._parse_datetime(row["acquired_at"]),
            expires_at=cls._parse_datetime(row["expires_at"]),
            schema_version=row["schema_version"],
        )


# Backward-compatible protocol alias
PostgresTaskStoreInterface = PostgresStorage
