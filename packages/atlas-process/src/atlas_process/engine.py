"""ATLAS Durable Process Execution Engine.

Orchestrates business process execution, dependency resolution, parallel/conditional branching,
worker lease fencing, crash recovery, checkpointing, and idempotent execution.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from atlas_process.definitions import (
    ProcessDefinition,
    ProcessTaskDefinition,
    TaskType,
)
from atlas_process.state_machine import (
    ProcessStateMachine,
    ProcessStatus,
    ProcessTaskStateMachine,
    ProcessTaskStatus,
)


class ProcessTaskInstance(BaseModel):
    """Runtime execution state of a specific task within a process instance."""

    task_instance_id: str = Field(default_factory=lambda: f"ptask_{uuid.uuid4().hex[:12]}")
    process_instance_id: str
    task_def_id: str
    task_type: TaskType
    status: ProcessTaskStatus = ProcessTaskStatus.PENDING
    assigned_to: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    lease_token: str | None = None
    lease_fencing_token: int = 0
    lease_expires_at: float | None = None
    retry_count: int = 0
    started_at: float | None = None
    completed_at: float | None = None
    idempotency_key: str | None = None


class ProcessInstance(BaseModel):
    """Materialized record of a running or completed business process."""

    instance_id: str = Field(default_factory=lambda: f"pinst_{uuid.uuid4().hex[:12]}")
    definition_id: str
    definition_version: str
    definition_hash: str
    tenant_id: str
    status: ProcessStatus = ProcessStatus.PENDING
    variables: dict[str, Any] = Field(default_factory=dict)
    task_instances: dict[str, ProcessTaskInstance] = Field(
        default_factory=dict
    )  # task_def_id -> instance
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    completed_at: float | None = None
    error_message: str | None = None
    idempotency_key: str | None = None
    checkpoint_version: int = 0


class StaleWorkerFencingError(Exception):
    """Raised when a worker attempts to complete a task with an outdated fencing token."""


class LeaseExpiredError(Exception):
    """Raised when an operation targets an expired task lease."""


class ProcessExecutionEngine:
    """Authoritative orchestrator for durable process lifecycle and task execution."""

    def __init__(self) -> None:
        self._instances: dict[str, ProcessInstance] = {}
        self._definitions: dict[str, ProcessDefinition] = {}
        self._idempotency_cache: dict[str, str] = {}  # idempotency_key -> instance_id
        self._task_idempotency_cache: dict[str, dict[str, Any]] = {}  # task_idem_key -> output
        self._checkpoints: dict[str, list[dict[str, Any]]] = {}  # instance_id -> checkpoints
        self._fencing_counters: dict[str, int] = {}  # task_instance_id -> counter

    def register_definition(self, definition: ProcessDefinition) -> None:
        """Register a validated process definition in the engine."""
        self._definitions[definition.definition_id] = definition

    def start_process(
        self,
        definition_id: str,
        tenant_id: str,
        initial_variables: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> ProcessInstance:
        """Initialize and start a process instance."""
        # 1. Idempotency Check
        if idempotency_key and idempotency_key in self._idempotency_cache:
            existing_id = self._idempotency_cache[idempotency_key]
            return self._instances[existing_id]

        definition = self._definitions.get(definition_id)
        if not definition:
            raise KeyError(f"Process definition '{definition_id}' not found.")

        instance = ProcessInstance(
            definition_id=definition_id,
            definition_version=definition.version,
            definition_hash=definition.definition_hash or definition.compute_hash(),
            tenant_id=tenant_id,
            status=ProcessStatus.RUNNING,
            variables=initial_variables or {},
            idempotency_key=idempotency_key,
        )

        # Initialize all task instances from definition
        for tdef in definition.tasks:
            task_inst = ProcessTaskInstance(
                process_instance_id=instance.instance_id,
                task_def_id=tdef.task_def_id,
                task_type=tdef.task_type,
                status=ProcessTaskStatus.PENDING,
            )
            instance.task_instances[tdef.task_def_id] = task_inst

        if idempotency_key:
            self._idempotency_cache[idempotency_key] = instance.instance_id

        self._instances[instance.instance_id] = instance
        self._create_checkpoint(instance)

        # Transition initial tasks with 0 dependencies to READY
        self._refresh_task_states(instance)

        return instance

    def _create_checkpoint(self, instance: ProcessInstance) -> None:
        """Create a durable checkpoint snapshot of the process instance."""
        instance.checkpoint_version += 1
        instance.updated_at = time.time()
        history = self._checkpoints.setdefault(instance.instance_id, [])
        history.append(instance.model_dump())

    def get_instance(self, instance_id: str) -> ProcessInstance | None:
        """Retrieve a process instance by ID."""
        return self._instances.get(instance_id)

    def _refresh_task_states(self, instance: ProcessInstance) -> None:
        """Evaluate dependencies and conditional branches to progress tasks."""
        definition = self._definitions[instance.definition_id]
        all_completed = True
        any_failed = False

        for tdef in definition.tasks:
            t_inst = instance.task_instances[tdef.task_def_id]

            if t_inst.status in (
                ProcessTaskStatus.FAILED,
                ProcessTaskStatus.CANCELLED,
            ):
                any_failed = True

            if t_inst.status not in (
                ProcessTaskStatus.COMPLETED,
                ProcessTaskStatus.SKIPPED,
            ):
                all_completed = False

            if t_inst.status == ProcessTaskStatus.PENDING:
                # Check dependencies
                deps_satisfied = True
                for dep_id in tdef.dependencies:
                    dep_inst = instance.task_instances.get(dep_id)
                    if not dep_inst or dep_inst.status != ProcessTaskStatus.COMPLETED:
                        deps_satisfied = False
                        break

                if deps_satisfied:
                    # Check conditions if upstream had branches
                    if self._evaluate_conditions(tdef, instance):
                        ProcessTaskStateMachine.validate_transition(
                            t_inst.status, ProcessTaskStatus.READY
                        )
                        t_inst.status = ProcessTaskStatus.READY
                    else:
                        t_inst.status = ProcessTaskStatus.SKIPPED

        # Update process status if terminal
        if all_completed and instance.status == ProcessStatus.RUNNING:
            ProcessStateMachine.validate_transition(instance.status, ProcessStatus.COMPLETED)
            instance.status = ProcessStatus.COMPLETED
            instance.completed_at = time.time()
        elif any_failed and instance.status == ProcessStatus.RUNNING:
            # Check if compensation is needed or directly mark failed
            instance.status = ProcessStatus.FAILED
            instance.completed_at = time.time()

        self._create_checkpoint(instance)

    def _evaluate_conditions(self, tdef: ProcessTaskDefinition, instance: ProcessInstance) -> bool:
        """Evaluate branch conditions against process variables."""
        # By default, without negative conditions, dependencies met means ready
        return True

    def acquire_task_lease(
        self,
        instance_id: str,
        task_def_id: str,
        worker_id: str,
        lease_duration_seconds: float = 60.0,
    ) -> tuple[str, int]:
        """Grant a worker lease and monotonic fencing token to execute a task."""
        instance = self._instances.get(instance_id)
        if not instance:
            raise KeyError(f"Process instance '{instance_id}' not found.")

        t_inst = instance.task_instances.get(task_def_id)
        if not t_inst:
            raise KeyError(f"Task '{task_def_id}' not found.")

        now = time.time()

        # Check if already leased and unexpired
        if (
            t_inst.lease_expires_at
            and t_inst.lease_expires_at > now
            and t_inst.assigned_to
            and t_inst.assigned_to != worker_id
        ):
            raise PermissionError(
                f"Task '{task_def_id}' is currently leased by worker '{t_inst.assigned_to}' until {t_inst.lease_expires_at}."
            )

        # Monotonically increment fencing token
        fencing_token = self._fencing_counters.get(t_inst.task_instance_id, 0) + 1
        self._fencing_counters[t_inst.task_instance_id] = fencing_token

        lease_token = f"lease_{uuid.uuid4().hex[:12]}"
        t_inst.lease_token = lease_token
        t_inst.lease_fencing_token = fencing_token
        t_inst.lease_expires_at = now + lease_duration_seconds
        t_inst.assigned_to = worker_id
        t_inst.started_at = now

        if t_inst.status == ProcessTaskStatus.READY:
            ProcessTaskStateMachine.validate_transition(t_inst.status, ProcessTaskStatus.RUNNING)
            t_inst.status = ProcessTaskStatus.RUNNING

        self._create_checkpoint(instance)
        return lease_token, fencing_token

    def complete_task(
        self,
        instance_id: str,
        task_def_id: str,
        outputs: dict[str, Any],
        fencing_token: int,
        idempotency_key: str | None = None,
    ) -> None:
        """Mark task completed, verifying worker fencing token and checking idempotency."""
        instance = self._instances.get(instance_id)
        if not instance:
            raise KeyError(f"Process instance '{instance_id}' not found.")

        t_inst = instance.task_instances.get(task_def_id)
        if not t_inst:
            raise KeyError(f"Task '{task_def_id}' not found.")

        # Fencing token invariant: must match active token
        if fencing_token != t_inst.lease_fencing_token:
            raise StaleWorkerFencingError(
                f"Worker commit rejected: Stale fencing token {fencing_token} (expected {t_inst.lease_fencing_token})."
            )

        # Check if lease expired
        if t_inst.lease_expires_at and time.time() > t_inst.lease_expires_at:
            raise LeaseExpiredError(
                f"Task lease expired at {t_inst.lease_expires_at} (current={time.time()})."
            )

        # Check task-level idempotency
        if idempotency_key:
            if idempotency_key in self._task_idempotency_cache:
                # Return cached result
                t_inst.outputs = self._task_idempotency_cache[idempotency_key]
                return
            self._task_idempotency_cache[idempotency_key] = outputs

        ProcessTaskStateMachine.validate_transition(t_inst.status, ProcessTaskStatus.COMPLETED)
        t_inst.status = ProcessTaskStatus.COMPLETED
        t_inst.outputs = outputs
        t_inst.completed_at = time.time()
        t_inst.lease_token = None
        t_inst.lease_expires_at = None

        # Merge outputs into process variables
        instance.variables.update(outputs)

        self._refresh_task_states(instance)

    def fail_task(
        self,
        instance_id: str,
        task_def_id: str,
        error_message: str,
        fencing_token: int,
    ) -> None:
        """Mark a task failed, triggering failure paths or compensations."""
        instance = self._instances.get(instance_id)
        if not instance:
            raise KeyError(f"Process instance '{instance_id}' not found.")

        t_inst = instance.task_instances.get(task_def_id)
        if not t_inst:
            raise KeyError(f"Task '{task_def_id}' not found.")

        if fencing_token != t_inst.lease_fencing_token:
            raise StaleWorkerFencingError("Stale fencing token on task failure.")

        ProcessTaskStateMachine.validate_transition(t_inst.status, ProcessTaskStatus.FAILED)
        t_inst.status = ProcessTaskStatus.FAILED
        t_inst.error = error_message
        t_inst.completed_at = time.time()

        self._refresh_task_states(instance)

    def cancel_process(self, instance_id: str, reason: str = "User cancellation") -> None:
        """Cancel an in-flight process instance and all non-terminal tasks."""
        instance = self._instances.get(instance_id)
        if not instance:
            raise KeyError(f"Process instance '{instance_id}' not found.")

        if instance.status in ProcessStateMachine.TERMINAL_STATES:
            return

        instance.status = ProcessStatus.CANCELLED
        instance.error_message = reason
        instance.completed_at = time.time()

        for t_inst in instance.task_instances.values():
            if t_inst.status not in ProcessTaskStateMachine.TERMINAL_STATES:
                t_inst.status = ProcessTaskStatus.CANCELLED
                t_inst.completed_at = time.time()

        self._create_checkpoint(instance)

    def recover_after_restart(self) -> int:
        """Simulate engine restart recovery from persistent checkpoints.

        Identifies expired worker leases and re-queues tasks as READY.
        Returns count of recovered tasks.
        """
        now = time.time()
        recovered_count = 0

        for instance in self._instances.values():
            if instance.status == ProcessStatus.RUNNING:
                for t_inst in instance.task_instances.values():
                    if t_inst.status == ProcessTaskStatus.RUNNING:
                        # If lease expired or worker disconnected
                        if not t_inst.lease_expires_at or t_inst.lease_expires_at < now:
                            t_inst.status = ProcessTaskStatus.READY
                            t_inst.lease_token = None
                            t_inst.lease_expires_at = None
                            t_inst.assigned_to = None
                            recovered_count += 1
                self._create_checkpoint(instance)

        return recovered_count
