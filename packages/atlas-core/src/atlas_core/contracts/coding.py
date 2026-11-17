"""Coding task and software engineering contracts for ATLAS."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from atlas_core.contracts.task import TaskPriority, TaskStatus


class FileChangeType(StrEnum):
    """Classification of filesystem modifications."""

    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"
    RENAME = "RENAME"


class FileChange(BaseModel):
    """Record of an authorized file change with cryptographic hashes."""

    path: str
    change_type: FileChangeType
    old_path: str | None = None
    before_hash: str | None = None
    after_hash: str | None = None
    diff: str | None = None
    lines_added: int = 0
    lines_removed: int = 0
    applied_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    verified: bool = False


class PatchHunk(BaseModel):
    """A single unified diff hunk."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[str] = Field(default_factory=list)


class FilePatch(BaseModel):
    """Parsed patch for a single file."""

    source_path: str
    target_path: str
    hunks: list[PatchHunk] = Field(default_factory=list)
    is_new: bool = False
    is_deleted: bool = False
    is_binary: bool = False


class UnifiedDiff(BaseModel):
    """Structured representation of a unified multi-file diff."""

    patches: list[FilePatch] = Field(default_factory=list)
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    raw_diff: str = ""


class TestResultSummary(BaseModel):
    """Outcome of a test discovery and execution run."""

    framework: str
    command: list[str]
    working_dir: str
    exit_code: int
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    total_count: int = 0
    duration_seconds: float = 0.0
    output: str = ""
    is_success: bool = False
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RepositoryFileMetadata(BaseModel):
    """Metadata describing a discovered repository file."""

    rel_path: str
    abs_path: str
    size_bytes: int
    is_binary: bool = False
    is_symlink: bool = False
    sha256: str = ""
    last_modified: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CodingTask(BaseModel):
    """Unified software engineering coding task representation."""

    task_id: str
    workspace_id: str
    tenant_id: str = "default"
    user_request: str
    repo_root: str
    objective: str
    status: TaskStatus = TaskStatus.CREATED
    priority: TaskPriority = TaskPriority.NORMAL
    plan: dict[str, Any] = Field(default_factory=dict)
    relevant_files: list[str] = Field(default_factory=list)
    authorized_tools: list[str] = Field(default_factory=list)
    action_history: list[dict[str, Any]] = Field(default_factory=list)
    file_changes: list[FileChange] = Field(default_factory=list)
    test_results: list[TestResultSummary] = Field(default_factory=list)
    verification_evidence: dict[str, Any] = Field(default_factory=dict)
    checkpoint_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
