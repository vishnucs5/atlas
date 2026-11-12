"""EnvironmentReconciler for comparing live browser/DOM state against checkpoint expectations."""

from datetime import UTC, datetime
from typing import Any

from atlas_core.contracts.checkpoint import Checkpoint
from atlas_core.contracts.ledger import ActionExecutionRecord, ActionExecutionStatus
from atlas_core.contracts.recovery import ReconciliationDecision, ReconciliationResult

from atlas_coordination.action_ledger import is_action_idempotent


class EnvironmentReconciler:
    """Inspects live environment state and compares with checkpoint expectations prior to resumption."""

    def reconcile(
        self,
        checkpoint: Checkpoint,
        live_environment: dict[str, Any] | None = None,
        pending_actions: list[ActionExecutionRecord] | None = None,
    ) -> ReconciliationResult:
        """Deterministically reconcile live physical environment against checkpoint expectations."""
        now = datetime.now(UTC)

        # If live environment is completely unreachable or dead
        if not live_environment:
            return ReconciliationResult(
                matches_expected=False,
                observed_url=None,
                observed_title=None,
                pending_action_handled=False,
                decision=ReconciliationDecision.RESTART_STEP,
                reason="Live environment is unreachable; session must be re-launched from checkpoint.",
                details={"checkpoint_id": checkpoint.checkpoint_id},
                timestamp=now,
            )

        observed_url = live_environment.get("url")
        observed_title = live_environment.get("title")
        dom_snippet = (live_environment.get("dom") or "").lower()
        status_code = live_environment.get("status_code", 200)

        expected_url = checkpoint.state_snapshot.get("url")
        expected_title = checkpoint.state_snapshot.get("title")

        # 1. Check for severe authentication/authorization drops
        if (
            status_code in (401, 403)
            or "session expired" in dom_snippet
            or "access denied" in dom_snippet
        ):
            return ReconciliationResult(
                matches_expected=False,
                observed_url=observed_url,
                observed_title=observed_title,
                pending_action_handled=False,
                decision=ReconciliationDecision.REQUEST_APPROVAL,
                reason="Live environment session expired or access was denied. Human operator intervention required.",
                details={"status_code": status_code, "checkpoint_id": checkpoint.checkpoint_id},
                timestamp=now,
            )

        # 2. Check for 5xx server errors
        if status_code >= 500:
            return ReconciliationResult(
                matches_expected=False,
                observed_url=observed_url,
                observed_title=observed_title,
                pending_action_handled=False,
                decision=ReconciliationDecision.RESTART_STEP,
                reason=f"Physical environment encountered HTTP {status_code}. Step should be restarted.",
                details={"status_code": status_code},
                timestamp=now,
            )

        # 3. Handle uncertain / pending actions
        uncertain_records = [
            a
            for a in (pending_actions or [])
            if a.status in (ActionExecutionStatus.UNKNOWN, ActionExecutionStatus.STARTED)
        ]

        if uncertain_records:
            has_non_idempotent = any(
                not is_action_idempotent(a.action_type) for a in uncertain_records
            )

            if has_non_idempotent:
                # Check if physical environment shows concrete evidence that the action succeeded before crash
                # Evidence: URL changed to confirmation/next step or success indicator in DOM
                evidence_found = False
                success_keywords = (
                    "success",
                    "submitted",
                    "confirmed",
                    "order-placed",
                    "complete",
                    "receipt",
                )

                if expected_url and observed_url and observed_url != expected_url:
                    evidence_found = True
                elif any(kw in dom_snippet for kw in success_keywords):
                    evidence_found = True

                if evidence_found:
                    return ReconciliationResult(
                        matches_expected=True,
                        observed_url=observed_url,
                        observed_title=observed_title,
                        pending_action_handled=True,
                        decision=ReconciliationDecision.RESUME,
                        reason="Physical environment confirms uncertain non-idempotent action was executed prior to crash. Resuming workflow.",
                        details={"reconciled_actions": [a.action_id for a in uncertain_records]},
                        timestamp=now,
                    )
                else:
                    return ReconciliationResult(
                        matches_expected=False,
                        observed_url=observed_url,
                        observed_title=observed_title,
                        pending_action_handled=False,
                        decision=ReconciliationDecision.REQUEST_APPROVAL,
                        reason="Non-idempotent action outcome is UNKNOWN without conclusive physical DOM confirmation. Requiring approval to prevent double-execution.",
                        details={"uncertain_actions": [a.action_id for a in uncertain_records]},
                        timestamp=now,
                    )
            else:
                # All uncertain actions are idempotent -> safe to restart step
                return ReconciliationResult(
                    matches_expected=True,
                    observed_url=observed_url,
                    observed_title=observed_title,
                    pending_action_handled=False,
                    decision=ReconciliationDecision.RESTART_STEP,
                    reason="Uncertain actions are all idempotent. Safely restarting step execution.",
                    details={"idempotent_actions": [a.action_id for a in uncertain_records]},
                    timestamp=now,
                )

        # 4. No pending uncertain actions: compare observed vs expected
        url_match = (expected_url is None) or (expected_url == observed_url)
        title_match = (expected_title is None) or (expected_title == observed_title)

        if url_match and title_match:
            return ReconciliationResult(
                matches_expected=True,
                observed_url=observed_url,
                observed_title=observed_title,
                pending_action_handled=False,
                decision=ReconciliationDecision.RESUME,
                reason="Live environment matches checkpoint state. Resuming execution.",
                details={"checkpoint_id": checkpoint.checkpoint_id},
                timestamp=now,
            )

        return ReconciliationResult(
            matches_expected=False,
            observed_url=observed_url,
            observed_title=observed_title,
            pending_action_handled=False,
            decision=ReconciliationDecision.RESTART_STEP,
            reason=f"Environment drifted from checkpoint: expected URL '{expected_url}', observed '{observed_url}'. Restarting step.",
            details={"expected_url": expected_url, "observed_url": observed_url},
            timestamp=now,
        )
