"""Durable fault tolerance, dead worker detection, fencing validation, and unknown outcome reconciliation."""

import logging
import threading
from datetime import UTC, datetime, timedelta

from atlas_coordination.action_ledger import (
    ActionLedger,
    NonIdempotentActionUncertaintyError,
    is_action_idempotent,
)
from atlas_core.contracts.worker import WorkerStatus
from atlas_storage.interfaces import StaleWorkerError

from atlas_distributed.enrollment import WorkerEnrollmentAuthority
from atlas_distributed.models import (
    AssignmentPayload,
    AssignmentResult,
)
from atlas_distributed.scheduler import DistributedScheduler, TaskRequirements

logger = logging.getLogger("atlas.distributed.fault_tolerance")


class AssignmentRecoveryState:
    """Tracking record for an assignment undergoing fault recovery."""

    def __init__(
        self,
        assignment_id: str,
        task_id: str,
        failed_worker_id: str,
        fencing_generation: int,
        requires_reconciliation: bool = False,
        reconciliation_reason: str | None = None,
    ) -> None:
        self.assignment_id = assignment_id
        self.task_id = task_id
        self.failed_worker_id = failed_worker_id
        self.fencing_generation = fencing_generation
        self.requires_reconciliation = requires_reconciliation
        self.reconciliation_reason = reconciliation_reason
        self.reconciled = False
        self.reconciled_at: datetime | None = None
        self.reconciled_status: str | None = None
        self.reconciliation_notes: str | None = None


class DistributedRecoveryManager:
    """Manages heartbeat monitoring, dead-worker eviction, monotonic fencing, and side-effect safe reassignment."""

    def __init__(
        self,
        enrollment_authority: WorkerEnrollmentAuthority,
        scheduler: DistributedScheduler,
        action_ledger: ActionLedger | None = None,
        heartbeat_timeout_seconds: float = 15.0,
    ) -> None:
        self.enrollment_authority = enrollment_authority
        self.scheduler = scheduler
        self.action_ledger = action_ledger
        self.heartbeat_timeout = timedelta(seconds=heartbeat_timeout_seconds)

        self._active_assignments: dict[str, AssignmentPayload] = {}
        self._task_active_generations: dict[str, int] = {}
        self._recovery_states: dict[str, AssignmentRecoveryState] = {}
        self._lock = threading.Lock()

    def register_assignment(self, assignment: AssignmentPayload) -> None:
        """Track dispatched assignment for fault detection and lease monitoring."""
        with self._lock:
            self._active_assignments[assignment.assignment_id] = assignment
            self._task_active_generations[assignment.task_id] = assignment.generation

    def validate_fencing_and_complete(self, result: AssignmentResult) -> bool:
        """Validate monotonic generation fencing before accepting assignment completion.

        Raises StaleWorkerError if completion generation does not match the active lease.
        """
        with self._lock:
            # Check if task generation has advanced
            active_gen = self._task_active_generations.get(result.task_id)
            if active_gen is not None and result.generation < active_gen:
                error_msg = (
                    f"Stale worker completion rejected for task {result.task_id}: "
                    f"result generation {result.generation} < active generation {active_gen}"
                )
                logger.error(error_msg)
                raise StaleWorkerError(error_msg)

            assignment = self._active_assignments.get(result.assignment_id)
            if not assignment:
                error_msg = (
                    f"Stale worker completion rejected: assignment {result.assignment_id} "
                    f"is no longer active or has been reassigned (generation {result.generation})"
                )
                logger.error(error_msg)
                raise StaleWorkerError(error_msg)

            # Monotonic fencing check
            if result.generation < assignment.generation:
                error_msg = (
                    f"Stale worker completion rejected for assignment {result.assignment_id}: "
                    f"worker {result.worker_id} generation {result.generation} < active generation {assignment.generation}"
                )
                logger.error(error_msg)
                raise StaleWorkerError(error_msg)

            if result.worker_id != assignment.worker_id:
                error_msg = (
                    f"Stale worker completion rejected: assignment {result.assignment_id} is leased to "
                    f"worker {assignment.worker_id}, but completed by {result.worker_id}"
                )
                logger.error(error_msg)
                raise StaleWorkerError(error_msg)

            # Valid commit: release scheduler lease
            self.scheduler.complete_task(result.assignment_id)
            self._active_assignments.pop(result.assignment_id, None)
            logger.info("Assignment %s successfully verified and completed", result.assignment_id)
            return True

    def detect_and_handle_dead_workers(self) -> list[str]:
        """Detect workers that missed heartbeat deadline, mark DISCONNECTED, and trigger recovery."""
        now = datetime.now(UTC)
        evicted_worker_ids: list[str] = []

        workers = self.enrollment_authority.list_workers()
        for worker in workers:
            if worker.is_revoked or worker.status == WorkerStatus.TERMINATED:
                continue

            time_since_heartbeat = now - worker.last_heartbeat_at
            if time_since_heartbeat > self.heartbeat_timeout:
                logger.warning(
                    "Worker %s timed out (last heartbeat %s ago); marking DISCONNECTED",
                    worker.worker_id,
                    time_since_heartbeat,
                )
                worker.status = WorkerStatus.DISCONNECTED
                evicted_worker_ids.append(worker.worker_id)
                self.recover_worker_assignments(worker.worker_id)

        return evicted_worker_ids

    def recover_worker_assignments(self, failed_worker_id: str) -> list[AssignmentRecoveryState]:
        """Examine assignments held by a failed worker and determine safe recovery plan."""
        recovered_states: list[AssignmentRecoveryState] = []

        with self._lock:
            affected_assignments = [
                a for a in self._active_assignments.values() if a.worker_id == failed_worker_id
            ]

        for assignment in affected_assignments:
            action_type = assignment.action_type
            action_id = assignment.parameters.get("action_id", f"act_{assignment.assignment_id}")

            # 1. Side-effect safety check
            # If action is non-idempotent, check ActionLedger status
            is_idempotent = is_action_idempotent(action_type)
            requires_reconciliation = False
            reconcile_reason = None

            if not is_idempotent:
                # Mark as uncertain: lease expired does NOT prove worker stopped executing!
                requires_reconciliation = True
                reconcile_reason = (
                    f"Non-idempotent action '{action_type}' was in flight when worker "
                    f"'{failed_worker_id}' partitioned. External physical state is UNKNOWN. Reconciliation required."
                )
                logger.warning(
                    "Side-Effect Uncertainty Guard: task %s, action %s requires external reconciliation",
                    assignment.task_id,
                    action_id,
                )

            rec_state = AssignmentRecoveryState(
                assignment_id=assignment.assignment_id,
                task_id=assignment.task_id,
                failed_worker_id=failed_worker_id,
                fencing_generation=assignment.generation,
                requires_reconciliation=requires_reconciliation,
                reconciliation_reason=reconcile_reason,
            )

            with self._lock:
                self._recovery_states[assignment.assignment_id] = rec_state
                # Evict from active assignments so old generation is dead
                self._active_assignments.pop(assignment.assignment_id, None)

            recovered_states.append(rec_state)

            # If idempotent and does not require manual reconciliation, we can safely reassign!
            if not requires_reconciliation:
                self.reassign_assignment(assignment)

        return recovered_states

    def reassign_assignment(
        self,
        old_assignment: AssignmentPayload,
        force_after_reconciliation: bool = False,
    ) -> AssignmentPayload:
        """Safely reassign task to a new eligible worker with monotonic fencing increment."""
        assignment_id = old_assignment.assignment_id
        rec_state = self._recovery_states.get(assignment_id)

        if rec_state and rec_state.requires_reconciliation and not rec_state.reconciled:
            if not force_after_reconciliation:
                raise NonIdempotentActionUncertaintyError(
                    f"Cannot reassign task '{old_assignment.task_id}': "
                    f"{rec_state.reconciliation_reason}"
                )

        with self._lock:
            self._active_assignments.pop(old_assignment.assignment_id, None)

        # Release old lease on scheduler
        self.scheduler.complete_task(old_assignment.assignment_id)

        # Reschedule task: DistributedScheduler will acquire a new lease with incremented generation
        requirements = TaskRequirements(
            task_id=old_assignment.task_id,
            tenant_id=old_assignment.tenant_id,
            objective=old_assignment.objective,
            action_type=old_assignment.action_type,
            required_drivers=old_assignment.required_capabilities,
            parameters=old_assignment.parameters,
        )

        _, new_payload = self.scheduler.schedule_task(requirements)
        self.register_assignment(new_payload)

        logger.info(
            "Task %s reassigned from worker %s to worker %s (new generation=%d > old=%d)",
            old_assignment.task_id,
            old_assignment.worker_id,
            new_payload.worker_id,
            new_payload.generation,
            old_assignment.generation,
        )
        return new_payload

    def reconcile_external_action(
        self,
        assignment_id: str,
        verified_status: str,
        notes: str = "",
    ) -> AssignmentRecoveryState:
        """Reconcile the physical external outcome of an in-doubt action after worker crash or partition."""
        with self._lock:
            rec_state = self._recovery_states.get(assignment_id)
            if not rec_state:
                raise ValueError(f"No recovery record found for assignment {assignment_id}")

            rec_state.reconciled = True
            rec_state.reconciled_at = datetime.now(UTC)
            rec_state.reconciled_status = verified_status
            rec_state.reconciliation_notes = notes

            logger.info(
                "Assignment %s reconciled: status=%s, notes=%s",
                assignment_id,
                verified_status,
                notes,
            )
            return rec_state

    def get_recovery_state(self, assignment_id: str) -> AssignmentRecoveryState | None:
        """Retrieve recovery and reconciliation state for an assignment."""
        with self._lock:
            return self._recovery_states.get(assignment_id)
