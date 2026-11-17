"""ATLAS Process Definition Contracts & Schemas.

Provides versioned, validated process definition models including sequential,
parallel, conditional branching, human approval tasks, compensation steps,
error paths, timers, deadlines, and schema-validated I/O contracts.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskType(StrEnum):
    """Classification of steps within a business process definition."""

    AGENT_EXECUTION = "AGENT_EXECUTION"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    EXTERNAL_INTEGRATION = "EXTERNAL_INTEGRATION"
    SUBPROCESS = "SUBPROCESS"
    TIMER = "TIMER"
    COMPENSATION = "COMPENSATION"
    NOTIFICATION = "NOTIFICATION"
    GATEWAY_PARALLEL = "GATEWAY_PARALLEL"
    GATEWAY_CONDITIONAL = "GATEWAY_CONDITIONAL"
    GATEWAY_JOIN = "GATEWAY_JOIN"


class BranchCondition(BaseModel):
    """Declarative conditional branch evaluation rule."""

    expression: str  # e.g., "amount > 10000"
    target_task_id: str


class ProcessTaskDefinition(BaseModel):
    """Declarative specification of a single step within a process definition."""

    task_def_id: str
    name: str
    task_type: TaskType
    description: str = ""
    dependencies: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_permissions: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    timeout_seconds: float = 300.0
    retry_limit: int = 0
    is_idempotent: bool = False
    compensation_task_id: str | None = None
    conditions: list[BranchCondition] = Field(default_factory=list)
    parallel_branches: list[list[str]] = Field(default_factory=list)
    join_condition: str = "ALL"  # ALL or ANY
    escalation_timeout_seconds: float | None = None
    approval_config: dict[str, Any] = Field(default_factory=dict)
    connector_id: str | None = None


class ProcessDefinitionStatus(StrEnum):
    """Lifecycle status of a process definition."""

    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class ProcessDefinitionError(Exception):
    """Base exception for process definition validation errors."""


class CyclicDependencyError(ProcessDefinitionError):
    """Raised when task dependencies form a cycle."""


class InvalidDependencyError(ProcessDefinitionError):
    """Raised when a dependency references a nonexistent task."""


class DuplicateTaskIdError(ProcessDefinitionError):
    """Raised when multiple tasks share the same task_def_id."""


class ProcessDefinition(BaseModel):
    """Versioned, validated enterprise process definition."""

    definition_id: str = Field(default_factory=lambda: f"pdef_{uuid.uuid4().hex[:12]}")
    name: str
    version: str = "1.0.0"
    description: str = ""
    tenant_id: str = "tenant_default"
    tasks: list[ProcessTaskDefinition] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    status: ProcessDefinitionStatus = ProcessDefinitionStatus.DRAFT
    created_at: float = Field(default_factory=time.time)
    created_by: str = "system"
    definition_hash: str = ""

    def compute_hash(self) -> str:
        """Compute content-addressed hash of definition for versioning."""
        raw = json.dumps(
            {
                "name": self.name,
                "version": self.version,
                "tasks": [t.model_dump() for t in self.tasks],
                "input_schema": self.input_schema,
                "output_schema": self.output_schema,
            },
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode()).hexdigest()


class ProcessDefinitionValidator:
    """Validates process definitions for structural integrity before deployment."""

    def validate(self, definition: ProcessDefinition) -> list[str]:
        """Validate a process definition and return list of errors (empty = valid)."""
        errors: list[str] = []

        if not definition.tasks:
            errors.append("Process definition must contain at least one task.")
            return errors

        # Check for duplicate task IDs
        task_ids = [t.task_def_id for t in definition.tasks]
        seen: set[str] = set()
        for tid in task_ids:
            if tid in seen:
                errors.append(f"Duplicate task_def_id: '{tid}'")
            seen.add(tid)

        task_id_set = set(task_ids)

        # Validate dependencies reference existing tasks
        for task in definition.tasks:
            for dep in task.dependencies:
                if dep not in task_id_set:
                    errors.append(f"Task '{task.task_def_id}' depends on nonexistent task '{dep}'.")

        # Check for cyclic dependencies
        if not errors:
            cycle = self._detect_cycle(definition.tasks)
            if cycle:
                errors.append(f"Cyclic dependency detected: {' -> '.join(cycle)}")

        # Validate conditional branches reference existing tasks
        for task in definition.tasks:
            for cond in task.conditions:
                if cond.target_task_id not in task_id_set:
                    errors.append(
                        f"Task '{task.task_def_id}' condition references nonexistent task '{cond.target_task_id}'."
                    )

        # Validate compensation references
        for task in definition.tasks:
            if task.compensation_task_id and task.compensation_task_id not in task_id_set:
                errors.append(
                    f"Task '{task.task_def_id}' compensation references nonexistent task '{task.compensation_task_id}'."
                )

        if not errors:
            definition.definition_hash = definition.compute_hash()
            definition.status = ProcessDefinitionStatus.VALIDATED

        return errors

    def _detect_cycle(self, tasks: list[ProcessTaskDefinition]) -> list[str] | None:
        """Detect cyclic dependencies using DFS."""
        adj: dict[str, list[str]] = {t.task_def_id: list(t.dependencies) for t in tasks}
        visited: set[str] = set()
        rec_stack: set[str] = set()
        path: list[str] = []

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    path.append(neighbor)
                    return True
            path.pop()
            rec_stack.discard(node)
            return False

        for task_id in adj:
            if task_id not in visited:
                if dfs(task_id):
                    return path
        return None
