"""RecoveryCoordinator orchestrating the 8-stage ATLAS recovery lifecycle."""

import uuid
from datetime import UTC, datetime
from typing import Any

from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.ledger import ActionExecutionStatus
from atlas_core.contracts.recovery import (
    FailureClassification,
    ReconciliationDecision,
    RecoveryStrategy,
)
from atlas_core.contracts.task import TaskStatus
from atlas_policy.firewall import ActionFirewall
from atlas_storage.interfaces import (
    CorruptedCheckpointError,
    EventStoreProtocol,
    LeaseExpiredError,
    StaleWorkerError,
    TaskStoreProtocol,
)

from atlas_coordination.action_ledger import (
    ActionLedger,
    NonIdempotentActionUncertaintyError,
)
from atlas_coordination.checkpoint_manager import CheckpointManager
from atlas_coordination.lease_manager import WorkerLeaseManager
from atlas_coordination.reconciler import EnvironmentReconciler


class RecoveryCoordinator:
    """Orchestrates detection, classification, evidence collection, firewall checks, and recovery execution."""

    def __init__(
        self,
        checkpoint_manager: CheckpointManager,
        action_ledger: ActionLedger,
        reconciler: EnvironmentReconciler,
        lease_manager: WorkerLeaseManager | None = None,
        firewall: ActionFirewall | None = None,
        task_store: TaskStoreProtocol | None = None,
        event_store: EventStoreProtocol | None = None,
        max_retries: int = 3,
    ) -> None:
        self.checkpoint_manager = checkpoint_manager
        self.action_ledger = action_ledger
        self.reconciler = reconciler
        self.lease_manager = lease_manager
        self.firewall = firewall
        self.task_store = task_store
        self.event_store = event_store
        self.max_retries = max_retries

    def classify_failure(
        self,
        error: Exception | str,
        context: dict[str, Any] | None = None,
    ) -> FailureClassification:
        """Classify failure condition into standard FailureClassification."""
        err_str = str(error).lower()

        if (
            isinstance(error, CorruptedCheckpointError)
            or "integrity" in err_str
            or "corrupted" in err_str
        ):
            return FailureClassification.CORRUPTED_CHECKPOINT

        if (
            isinstance(error, (LeaseExpiredError, StaleWorkerError))
            or "fencing" in err_str
            or "lease" in err_str
        ):
            return FailureClassification.LEASE_EXPIRED

        if (
            isinstance(error, NonIdempotentActionUncertaintyError)
            or "uncertain" in err_str
            or "unknown" in err_str
        ):
            return FailureClassification.UNKNOWN_ACTION_OUTCOME

        if "verification" in err_str or "postcondition" in err_str:
            return FailureClassification.VERIFICATION_FAILED

        if "browser" in err_str or "playwright" in err_str or "target closed" in err_str:
            return FailureClassification.BROWSER_DISCONNECTION

        if "network" in err_str or "connection" in err_str or "econnrefused" in err_str:
            return FailureClassification.NETWORK_DISCONNECTION

        if "api restart" in err_str:
            return FailureClassification.API_RESTART

        return FailureClassification.WORKER_CRASH

    def select_strategy(
        self,
        classification: FailureClassification,
        retry_count: int = 0,
    ) -> RecoveryStrategy:
        """Select recovery strategy based on failure classification and retry boundaries."""
        # Bounded recovery invariant: prevent infinite recovery cycles
        if retry_count >= self.max_retries:
            return RecoveryStrategy.FAIL_TASK

        if classification == FailureClassification.CORRUPTED_CHECKPOINT:
            return RecoveryStrategy.RESUME_FROM_CHECKPOINT

        if classification == FailureClassification.UNKNOWN_ACTION_OUTCOME:
            return RecoveryStrategy.RECONCILE_ENVIRONMENT

        if classification in (
            FailureClassification.BROWSER_DISCONNECTION,
            FailureClassification.WORKER_CRASH,
            FailureClassification.NETWORK_DISCONNECTION,
            FailureClassification.API_RESTART,
        ):
            return RecoveryStrategy.RECONCILE_ENVIRONMENT

        if classification == FailureClassification.VERIFICATION_FAILED:
            return RecoveryStrategy.RETRY_ACTION

        if classification == FailureClassification.LEASE_EXPIRED:
            return RecoveryStrategy.REQUEST_APPROVAL

        return RecoveryStrategy.RESUME_FROM_CHECKPOINT

    def execute_recovery(
        self,
        task_id: str,
        error: Exception | str,
        current_worker_id: str | None = None,
        expected_lease_generation: int = 1,
        live_environment: dict[str, Any] | None = None,
        operator_approved: bool = False,
        retry_count: int = 0,
    ) -> tuple[RecoveryStrategy, Checkpoint | None, str]:
        """Execute the full 8-stage ATLAS recovery lifecycle."""
        now = datetime.now(UTC)

        # Stage 1: DETECT
        err_msg = str(error)

        # Stage 2: CLASSIFY
        classification = self.classify_failure(error)

        # Stage 3: COLLECT EVIDENCE
        evidence: dict[str, Any] = {
            "error": err_msg,
            "classification": classification.value,
            "retry_count": retry_count,
            "timestamp": now.isoformat(),
            "worker_id": current_worker_id,
            "lease_generation": expected_lease_generation,
            "has_live_env": live_environment is not None,
        }

        # Stage 4: SELECT STRATEGY
        strategy = self.select_strategy(classification, retry_count=retry_count)

        # Stage 5: APPLY POLICY (Action Firewall)
        # Rule 2: Recovery actions must never bypass policy engine
        if self.firewall is not None and not operator_approved:
            # High-risk recovery: e.g. unknown outcomes, lease expiry, or non-idempotent re-execution
            if classification in (
                FailureClassification.UNKNOWN_ACTION_OUTCOME,
                FailureClassification.LEASE_EXPIRED,
            ):
                # Request operator approval if firewall is in enforcing mode
                strategy = RecoveryStrategy.REQUEST_APPROVAL
                evidence["policy_override"] = (
                    "Action Firewall required human approval for high-risk recovery"
                )

        # Stage 6: RECOVER
        recovered_checkpoint: Checkpoint | None = None
        recovery_summary = ""

        if strategy == RecoveryStrategy.FAIL_TASK:
            if self.task_store is not None:
                try:
                    self.task_store.update_task_status(task_id, TaskStatus.FAILED)
                except Exception:
                    pass
            recovery_summary = (
                f"Task recovery aborted: maximum retry count ({self.max_retries}) exceeded."
            )

        elif strategy == RecoveryStrategy.REQUEST_APPROVAL:
            # Roll back to last valid checkpoint and pause
            try:
                recovered_checkpoint = self.checkpoint_manager.rollback_to_last_valid(task_id)
            except Exception:
                recovered_checkpoint = None

            if self.task_store is not None:
                try:
                    self.task_store.update_task_status(task_id, TaskStatus.WAITING_APPROVAL)
                except Exception:
                    pass
            recovery_summary = "Recovery requires operator approval before resuming execution."

        elif strategy == RecoveryStrategy.RESUME_FROM_CHECKPOINT:
            recovered_checkpoint = self.checkpoint_manager.rollback_to_last_valid(task_id)
            recovery_summary = f"Rolled back to valid checkpoint '{recovered_checkpoint.checkpoint_id}' (sequence: {recovered_checkpoint.sequence})."

        elif strategy == RecoveryStrategy.RETRY_ACTION:
            recovered_checkpoint = self.checkpoint_manager.rollback_to_last_valid(task_id)
            recovery_summary = (
                f"Retrying action from checkpoint '{recovered_checkpoint.checkpoint_id}'."
            )

        elif strategy == RecoveryStrategy.RECONCILE_ENVIRONMENT:
            # Retrieve latest valid checkpoint
            valid_chk = self.checkpoint_manager.rollback_to_last_valid(task_id)

            # Retrieve pending / uncertain actions for this task
            task_actions = self.action_ledger.get_task_actions(task_id)
            reconcile_result = self.reconciler.reconcile(
                checkpoint=valid_chk,
                live_environment=live_environment,
                pending_actions=task_actions,
            )

            evidence["reconciliation_decision"] = reconcile_result.decision.value
            evidence["reconciliation_reason"] = reconcile_result.reason

            if reconcile_result.decision == ReconciliationDecision.RESUME:
                # If physical confirmation proved uncertain action executed, mark it VERIFIED
                if reconcile_result.pending_action_handled:
                    uncertain_ids = reconcile_result.details.get("reconciled_actions", [])
                    for act in task_actions:
                        if (
                            act.action_id in uncertain_ids
                            and act.status == ActionExecutionStatus.UNKNOWN
                        ):
                            self.action_ledger.mark_verified(
                                task_id=task_id,
                                idempotency_key=act.idempotency_key,
                                attempt=act.attempt,
                                verification_result={"reconciled_from_environment": True},
                                lease_generation=expected_lease_generation,
                                worker_id=current_worker_id,
                            )
                recovered_checkpoint = valid_chk
                strategy = RecoveryStrategy.RESUME_FROM_CHECKPOINT
                recovery_summary = f"Environment reconciled successfully: {reconcile_result.reason}"

            elif reconcile_result.decision == ReconciliationDecision.REQUEST_APPROVAL:
                if self.task_store is not None:
                    self.task_store.update_task_status(task_id, TaskStatus.WAITING_APPROVAL)
                recovered_checkpoint = valid_chk
                strategy = RecoveryStrategy.REQUEST_APPROVAL
                recovery_summary = (
                    f"Reconciliation requires operator approval: {reconcile_result.reason}"
                )

            else:  # RESTART_STEP or ABORT
                recovered_checkpoint = valid_chk
                strategy = RecoveryStrategy.RESUME_FROM_CHECKPOINT
                recovery_summary = (
                    f"Reconciliation determined step restart: {reconcile_result.reason}"
                )

        # Stage 7: VERIFY
        # Deterministically verify that recovered checkpoint passed integrity checks
        if recovered_checkpoint is not None:
            if not recovered_checkpoint.verify_hash():
                raise CorruptedCheckpointError(
                    f"Post-recovery verification failed: checkpoint '{recovered_checkpoint.checkpoint_id}' is corrupt."
                )

        # Stage 8: RECORD
        if self.event_store is not None:
            latest_seq = self.event_store.get_latest_sequence(task_id)
            event = ExecutionEvent(
                event_id=f"evt_rec_{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                sequence=latest_seq + 1,
                event_type=EventType.RECOVERY_STARTED,
                timestamp=now,
                payload={
                    "classification": classification.value,
                    "strategy": strategy.value,
                    "recovered_checkpoint_id": recovered_checkpoint.checkpoint_id
                    if recovered_checkpoint
                    else None,
                    "evidence": evidence,
                    "summary": recovery_summary,
                },
                correlation_id=task_id,
            )
            self.event_store.append_event(event)

        return strategy, recovered_checkpoint, recovery_summary
