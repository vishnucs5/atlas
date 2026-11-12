"""SQLite implementation of event-sourced storage for ATLAS."""

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus

from atlas_storage.interfaces import (
    EventStoreProtocol,
    OptimisticLockError,
    SequenceCollisionError,
    StorageError,
    TaskNotFoundError,
    TaskStoreProtocol,
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
"""


class SQLiteStorage(TaskStoreProtocol, EventStoreProtocol):
    """Event-sourced task storage engine powered by SQLite with WAL mode."""

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
        """Persist or overwrite a materialized task record."""
        query = """
        INSERT INTO tasks (
            task_id, objective, status, priority, created_at, updated_at,
            metadata, current_checkpoint_id, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            objective = excluded.objective,
            status = excluded.status,
            priority = excluded.priority,
            created_at = excluded.created_at,
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
                raise StorageError(f"Failed to save task '{task.task_id}': {exc}") from exc

    def get_task(self, task_id: str) -> Task | None:
        """Retrieve a materialized task by its unique identifier."""
        query = """
        SELECT task_id, objective, status, priority, created_at, updated_at,
               metadata, current_checkpoint_id, schema_version
        FROM tasks
        WHERE task_id = ?;
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, (task_id,))
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
        """Update the status of a task with optional optimistic concurrency check."""
        now = datetime.now(UTC)
        now_str = now.isoformat()
        new_status_str = new_status.value if isinstance(new_status, TaskStatus) else str(new_status)

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # First verify existence and current state
            cursor.execute("SELECT status FROM tasks WHERE task_id = ?;", (task_id,))
            row = cursor.fetchone()
            if row is None:
                raise TaskNotFoundError(f"Task '{task_id}' was not found.")

            current_status = row["status"]
            if expected_status is not None:
                expected_str = (
                    expected_status.value
                    if isinstance(expected_status, TaskStatus)
                    else str(expected_status)
                )
                if current_status != expected_str:
                    raise OptimisticLockError(
                        f"Task '{task_id}' current status '{current_status}' does not match expected '{expected_str}'."
                    )

            try:
                cursor.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?;",
                    (new_status_str, now_str, task_id),
                )
                conn.commit()
            except sqlite3.Error as exc:
                raise StorageError(f"Failed to update status for task '{task_id}': {exc}") from exc

            updated = self.get_task(task_id)
            if updated is None:
                raise TaskNotFoundError(f"Task '{task_id}' vanished after update.")
            return updated

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks with optional status filter and pagination."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if status is not None:
                status_str = status.value if isinstance(status, TaskStatus) else str(status)
                cursor.execute(
                    """
                    SELECT task_id, objective, status, priority, created_at, updated_at,
                           metadata, current_checkpoint_id, schema_version
                    FROM tasks
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?;
                    """,
                    (status_str, limit, offset),
                )
            else:
                cursor.execute(
                    """
                    SELECT task_id, objective, status, priority, created_at, updated_at,
                           metadata, current_checkpoint_id, schema_version
                    FROM tasks
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?;
                    """,
                    (limit, offset),
                )
            rows = cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    # -------------------------------------------------------------------------
    # EventStoreProtocol Implementation
    # -------------------------------------------------------------------------

    def append_event(self, event: ExecutionEvent) -> None:
        """Append an immutable event to the event stream."""
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
                raise SequenceCollisionError(
                    f"Integrity violation on event '{event.event_id}' (sequence {event.sequence} for task '{event.task_id}'): {exc}"
                ) from exc
            except sqlite3.Error as exc:
                raise StorageError(f"Failed to append event '{event.event_id}': {exc}") from exc

    def append_events(self, events: list[ExecutionEvent]) -> None:
        """Batch append multiple events atomically."""
        if not events:
            return
        query = """
        INSERT INTO execution_events (
            event_id, task_id, session_id, sequence, event_type,
            timestamp, payload, correlation_id, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                for event in events:
                    cursor.execute(
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
                raise SequenceCollisionError(f"Integrity collision in batch append: {exc}") from exc
            except sqlite3.Error as exc:
                conn.rollback()
                raise StorageError(f"Failed during batch append: {exc}") from exc

    def get_events(
        self,
        task_id: str,
        since_sequence: int = 0,
    ) -> list[ExecutionEvent]:
        """Retrieve events for a given task, ordered strictly by sequence number."""
        query = """
        SELECT event_id, task_id, session_id, sequence, event_type,
               timestamp, payload, correlation_id, schema_version
        FROM execution_events
        WHERE task_id = ? AND sequence > ?
        ORDER BY sequence ASC;
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, (task_id, since_sequence))
            rows = cursor.fetchall()
            return [self._row_to_event(row) for row in rows]

    def get_latest_event(self, task_id: str) -> ExecutionEvent | None:
        """Retrieve the event with the highest sequence number for a given task."""
        query = """
        SELECT event_id, task_id, session_id, sequence, event_type,
               timestamp, payload, correlation_id, schema_version
        FROM execution_events
        WHERE task_id = ?
        ORDER BY sequence DESC
        LIMIT 1;
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, (task_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_event(row)

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


# Alias for explicit task store typing
SQLiteTaskStore = SQLiteStorage
