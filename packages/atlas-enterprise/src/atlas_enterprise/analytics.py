"""Enterprise Operational and Compliance Analytics Engine."""

import logging
import threading
from typing import Any

from atlas_enterprise.audit import EnterpriseAuditLedger
from atlas_enterprise.cost import EnterpriseCostManager
from atlas_enterprise.iam import EnterpriseIAMEngine
from atlas_enterprise.models import PermissionAction
from atlas_enterprise.organization import EnterpriseOrganizationManager

logger = logging.getLogger("atlas.enterprise.analytics")


class EnterpriseAnalyticsEngine:
    """Computes real-time operational performance, worker utilization, and compliance posture."""

    def __init__(
        self,
        org_manager: EnterpriseOrganizationManager,
        iam_engine: EnterpriseIAMEngine,
        audit_ledger: EnterpriseAuditLedger,
        cost_manager: EnterpriseCostManager,
    ) -> None:
        self.org_manager = org_manager
        self.iam_engine = iam_engine
        self.audit_ledger = audit_ledger
        self.cost_manager = cost_manager
        self._lock = threading.RLock()

    def get_operational_metrics(
        self,
        caller_user_id: str,
        org_id: str,
        department_id: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate cross-system metrics into a unified operational dashboard dataset."""
        with self._lock:
            self.iam_engine.assert_permission(
                user_id=caller_user_id,
                org_id=org_id,
                action=PermissionAction.ORG_READ,
            )

            # Audit chain integrity check
            chain_intact, broken_seq, _ = self.audit_ledger.verify_chain_integrity(org_id)

            # Cost summary
            cost_summary = self.cost_manager.get_cost_summary(
                caller_user_id=caller_user_id,
                org_id=org_id,
                department_id=department_id,
            )

            # Query recent audit records
            records = self.audit_ledger.query_records(
                caller_user_id=caller_user_id,
                org_id=org_id,
                limit=1000,
                department_id=department_id,
            )

            total_actions = len(records)
            action_counts: dict[str, int] = {}
            for r in records:
                action_counts[r.action] = action_counts.get(r.action, 0) + 1

            # Compliance score: 100 if chain intact, 0 if chain broken
            compliance_score = 100.0 if chain_intact else 0.0

            return {
                "org_id": org_id,
                "department_id": department_id,
                "audit_chain_verified": chain_intact,
                "broken_sequence": broken_seq,
                "compliance_score": compliance_score,
                "total_audit_events": total_actions,
                "event_distribution": action_counts,
                "cost_and_usage": cost_summary,
            }
