"""PostgreSQL production storage interface specification and schema definitions.

This module defines the connection configuration, relational schema DDL, and interface
contract for production-grade event-sourced storage (scheduled for Phase 4 hardening).
"""

from datetime import datetime
from typing import Any

from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.event import ExecutionEvent
from atlas_core.contracts.ledger import ActionExecutionRecord, ActionExecutionStatus
from atlas_core.contracts.task import Task, TaskStatus
from atlas_core.contracts.worker import WorkerLease, WorkerRecord, WorkerStatus
from pydantic import BaseModel, ConfigDict, Field

from atlas_storage.interfaces import (
    ActionLedgerStoreProtocol,
    CheckpointStoreProtocol,
    EventStoreProtocol,
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
    min_pool_size: int = 5
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
        return (
            f"postgresql://{self.config.user}:{self.config.password}@"
            f"{self.config.host}:{self.config.port}/{self.config.database}"
        )

    def get_schema_ddl(self) -> str:
        """Return production relational schema DDL for PostgreSQL."""
        return POSTGRES_SCHEMA_DDL


class PostgresTaskStoreInterface(
    TaskStoreProtocol,
    EventStoreProtocol,
    CheckpointStoreProtocol,
    ActionLedgerStoreProtocol,
    WorkerStoreProtocol,
):
    """Abstract interface and contract specification for PostgreSQL production drivers.

    Production implementation is provisioned in Phase 4 hardening.
    """

    def __init__(self, config: PostgresConfig | None = None) -> None:
        self.config = config or PostgresConfig()
        self.spec = PostgresStorageSpec(self.config)

    def initialize(self) -> None:
        """Initialize connection pool and apply schema migrations."""
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def save_task(self, task: Task) -> None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def get_task(self, task_id: str) -> Task | None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def update_task_status(
        self,
        task_id: str,
        new_status: TaskStatus,
        expected_status: TaskStatus | None = None,
    ) -> Task:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def append_event(self, event: ExecutionEvent) -> None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def get_events(
        self,
        task_id: str,
        since_sequence: int = 0,
    ) -> list[ExecutionEvent]:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def get_latest_event(self, task_id: str) -> ExecutionEvent | None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def append_events(self, events: list[ExecutionEvent]) -> None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def get_latest_sequence(self, task_id: str) -> int:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def get_latest_checkpoint(self, task_id: str) -> Checkpoint | None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def list_checkpoints(self, task_id: str, limit: int = 50) -> list[Checkpoint]:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def record_action_attempt(self, record: ActionExecutionRecord) -> None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

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
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def get_action_record(
        self,
        task_id: str,
        idempotency_key: str,
        attempt: int = 1,
    ) -> ActionExecutionRecord | None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def get_latest_action(
        self,
        task_id: str,
        idempotency_key: str,
    ) -> ActionExecutionRecord | None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def get_task_actions(
        self,
        task_id: str,
    ) -> list[ActionExecutionRecord]:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def register_worker(self, worker: WorkerRecord) -> None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def heartbeat_worker(self, worker_id: str, status: WorkerStatus | None = None) -> None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def get_worker(self, worker_id: str) -> WorkerRecord | None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def list_workers(self, status: WorkerStatus | None = None) -> list[WorkerRecord]:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def acquire_lease(
        self,
        task_id: str,
        worker_id: str,
        ttl_seconds: float = 30.0,
    ) -> WorkerLease:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def renew_lease(
        self,
        lease_id: str,
        worker_id: str,
        ttl_seconds: float = 30.0,
    ) -> WorkerLease:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def release_lease(
        self,
        lease_id: str,
        worker_id: str,
    ) -> None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def get_active_lease(self, task_id: str) -> WorkerLease | None:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )

    def validate_lease_fencing(
        self,
        task_id: str,
        expected_generation: int,
    ) -> bool:
        raise NotImplementedError(
            "PostgreSQL production driver is scheduled for Phase 4 hardening."
        )
