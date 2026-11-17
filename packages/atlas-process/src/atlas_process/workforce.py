"""ATLAS Digital Workforce Allocation Engine.

Orchestrates human operators and autonomous digital AI agents, matching skills,
enforcing workload balancing, respecting tenant boundaries, and managing assignment leases.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class WorkerKind(StrEnum):
    """Categorization of workforce resources."""

    AI_AGENT = "AI_AGENT"
    HUMAN_OPERATOR = "HUMAN_OPERATOR"


class AssignmentPolicy(StrEnum):
    """Routing policy preference between human and AI execution."""

    AGENT_ONLY = "AGENT_ONLY"
    HUMAN_ONLY = "HUMAN_ONLY"
    PREFER_AGENT = "PREFER_AGENT"
    PREFER_HUMAN = "PREFER_HUMAN"


class DigitalWorker(BaseModel):
    """Registered human or autonomous agent workforce member."""

    worker_id: str
    name: str
    kind: WorkerKind
    tenant_id: str
    skills: list[str] = Field(default_factory=list)
    max_concurrency: int = 5
    current_load: int = 0
    is_active: bool = True


class WorkforceAllocationEngine:
    """Matches process tasks to optimal digital agents or human operators based on capabilities and load."""

    def __init__(self) -> None:
        self._workers: dict[str, DigitalWorker] = {}
        self._assignment_history: list[dict[str, Any]] = []

    def register_worker(self, worker: DigitalWorker) -> None:
        """Register a worker in the workforce directory."""
        self._workers[worker.worker_id] = worker

    def select_worker(
        self,
        required_skills: list[str],
        tenant_id: str,
        policy: AssignmentPolicy = AssignmentPolicy.PREFER_AGENT,
    ) -> DigitalWorker | None:
        """Find the best available worker matching skills, tenancy, and policy preference."""
        candidates = [
            w
            for w in self._workers.values()
            if w.is_active
            and w.tenant_id == tenant_id
            and w.current_load < w.max_concurrency
            and all(req in w.skills for req in required_skills)
        ]

        if not candidates:
            return None

        # Filter by assignment policy
        if policy == AssignmentPolicy.AGENT_ONLY:
            candidates = [c for c in candidates if c.kind == WorkerKind.AI_AGENT]
        elif policy == AssignmentPolicy.HUMAN_ONLY:
            candidates = [c for c in candidates if c.kind == WorkerKind.HUMAN_OPERATOR]
        elif policy == AssignmentPolicy.PREFER_AGENT:
            agent_candidates = [c for c in candidates if c.kind == WorkerKind.AI_AGENT]
            if agent_candidates:
                candidates = agent_candidates
        elif policy == AssignmentPolicy.PREFER_HUMAN:
            human_candidates = [c for c in candidates if c.kind == WorkerKind.HUMAN_OPERATOR]
            if human_candidates:
                candidates = human_candidates

        if not candidates:
            return None

        # Select candidate with lowest current load (workload-aware)
        selected = min(candidates, key=lambda w: w.current_load)
        return selected

    def assign_task(
        self,
        task_instance_id: str,
        worker_id: str,
    ) -> None:
        """Record an assignment and increment worker load."""
        worker = self._workers.get(worker_id)
        if not worker:
            raise KeyError(f"Worker '{worker_id}' not found.")

        worker.current_load += 1
        self._assignment_history.append(
            {
                "task_instance_id": task_instance_id,
                "worker_id": worker_id,
                "assigned_at": time.time(),
            }
        )

    def release_worker(self, worker_id: str) -> None:
        """Release worker slot upon task completion or failure."""
        worker = self._workers.get(worker_id)
        if worker and worker.current_load > 0:
            worker.current_load -= 1
