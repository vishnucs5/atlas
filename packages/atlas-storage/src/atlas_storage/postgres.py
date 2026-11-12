"""PostgreSQL production storage interface specification and schema definitions.

This module defines the connection configuration, relational schema DDL, and interface
contract for production-grade event-sourced storage (scheduled for Phase 4 hardening).
"""

from atlas_core.contracts.event import ExecutionEvent
from atlas_core.contracts.task import Task, TaskStatus
from pydantic import BaseModel, ConfigDict, Field

from atlas_storage.interfaces import EventStoreProtocol, TaskStoreProtocol

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


class PostgresTaskStoreInterface(TaskStoreProtocol, EventStoreProtocol):
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
