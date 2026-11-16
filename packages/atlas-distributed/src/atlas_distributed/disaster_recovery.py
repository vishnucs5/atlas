"""Disaster Recovery, Automated Chaos Injection, and State Reconciliation for ATLAS."""

from __future__ import annotations

import enum
import logging
import time
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger("atlas.distributed.disaster_recovery")


class FaultType(enum.StrEnum):
    POD_TERMINATION = "POD_TERMINATION"
    NODE_FAILURE = "NODE_FAILURE"
    NETWORK_PARTITION = "NETWORK_PARTITION"
    DATABASE_OUTAGE = "DATABASE_OUTAGE"
    LEASE_EXPIRATION = "LEASE_EXPIRATION"
    STALE_WORKER_RACE = "STALE_WORKER_RACE"


class TaskRecoveryState(BaseModel):
    """Snapshot of a task undergoing disaster recovery."""

    task_id: str
    tenant_id: str
    original_worker_id: str
    new_worker_id: str | None = None
    last_checkpoint_step: int = 0
    fencing_token: int = 1
    recovery_status: str = "PENDING"  # PENDING | RECONCILED | ABORTED


class DisasterRecoveryCoordinator:
    """Orchestrates chaos fault injection, lease fencing, and deterministic state restoration."""

    def __init__(self) -> None:
        self._active_leases: dict[
            str, tuple[str, int, float]
        ] = {}  # task_id -> (worker_id, fencing_token, expires_at)
        self._fenced_workers: set[str] = set()
        self._task_checkpoints: dict[str, int] = {}  # task_id -> last_step
        self._committed_actions: list[dict[str, Any]] = []
        self._recovery_ledger: dict[str, TaskRecoveryState] = {}

    def grant_lease(
        self,
        task_id: str,
        worker_id: str,
        duration_seconds: float = 60.0,
        initial_fencing_token: int = 1,
    ) -> int:
        """Grant task execution lease with monotonic fencing token."""
        expires_at = time.time() + duration_seconds
        self._active_leases[task_id] = (
            worker_id,
            initial_fencing_token,
            expires_at,
        )
        return initial_fencing_token

    def commit_action_result(
        self,
        task_id: str,
        worker_id: str,
        fencing_token: int,
        step: int,
        action_data: dict[str, Any],
    ) -> bool:
        """Validate worker lease and monotonic fencing token before committing action to ledger."""
        # 1. Fenced worker check
        if worker_id in self._fenced_workers:
            logger.warning(f"Action rejected: worker '{worker_id}' is permanently FENCED")
            return False

        # 2. Lease validity check
        lease = self._active_leases.get(task_id)
        if not lease:
            logger.warning(f"Action rejected: no active lease found for task '{task_id}'")
            return False

        current_worker, current_token, expires_at = lease

        # 3. Epoch / fencing token check
        if fencing_token < current_token:
            logger.error(
                f"Action rejected: stale fencing token {fencing_token} < current {current_token} for task '{task_id}'"
            )
            return False

        # 4. Expiration check
        if time.time() > expires_at:
            logger.warning(
                f"Action rejected: lease expired for worker '{worker_id}' on task '{task_id}'"
            )
            return False

        # Commit action and update checkpoint
        self._committed_actions.append(
            {
                "task_id": task_id,
                "worker_id": worker_id,
                "step": step,
                "fencing_token": fencing_token,
                "data": action_data,
                "timestamp": time.time(),
            }
        )
        self._task_checkpoints[task_id] = step
        return True

    def inject_fault(self, fault: FaultType, target_id: str) -> None:
        """Simulate catastrophic infrastructure failures."""
        logger.warning(f"Injecting simulated fault: {fault.value} on target '{target_id}'")

        if fault == FaultType.POD_TERMINATION:
            # Worker pod killed abruptly
            self._fenced_workers.add(target_id)

        elif fault == FaultType.NETWORK_PARTITION:
            # Isolate worker or cluster; leases expire
            for tid, (wid, token, _) in list(self._active_leases.items()):
                if wid == target_id:
                    # Force lease expiration
                    self._active_leases[tid] = (wid, token, time.time() - 1.0)

        elif fault == FaultType.STALE_WORKER_RACE:
            # Simulate old worker attempting action after reassignment
            self._fenced_workers.add(target_id)

    def recover_task(
        self,
        task_id: str,
        tenant_id: str,
        new_worker_id: str,
    ) -> TaskRecoveryState:
        """Reassign task to new worker, increment fencing token, and restore latest checkpoint."""
        old_worker_id = "unknown"
        old_token = 1

        if task_id in self._active_leases:
            old_worker_id, old_token, _ = self._active_leases[task_id]
            # Fence old worker
            self._fenced_workers.add(old_worker_id)

        new_fencing_token = old_token + 1
        last_step = self._task_checkpoints.get(task_id, 0)

        # Grant new lease with higher fencing token
        self.grant_lease(
            task_id=task_id,
            worker_id=new_worker_id,
            duration_seconds=60.0,
            initial_fencing_token=new_fencing_token,
        )

        recovery_state = TaskRecoveryState(
            task_id=task_id,
            tenant_id=tenant_id,
            original_worker_id=old_worker_id,
            new_worker_id=new_worker_id,
            last_checkpoint_step=last_step,
            fencing_token=new_fencing_token,
            recovery_status="RECONCILED",
        )
        self._recovery_ledger[task_id] = recovery_state

        logger.info(
            f"Successfully recovered task '{task_id}' -> new worker '{new_worker_id}' at checkpoint step {last_step} (epoch {new_fencing_token})"
        )
        return recovery_state
