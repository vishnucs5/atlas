"""Enterprise Cost Management, Measured Resource Attribution, and Departmental Budget Envelopes."""

import logging
import threading
import uuid
from typing import Any

from atlas_enterprise.iam import EnterpriseIAMEngine
from atlas_enterprise.models import (
    CostRecord,
    DepartmentBudget,
    PermissionAction,
)
from atlas_enterprise.organization import (
    CrossTenantAccessViolationError,
    EnterpriseOrganizationManager,
)

logger = logging.getLogger("atlas.enterprise.cost")


class EnterpriseCostError(Exception):
    """Base exception for enterprise cost and budget errors."""


class BudgetCapExceededError(EnterpriseCostError):
    """Raised when an operation would exceed an active departmental spending cap."""


# Pricing catalog: USD per 1,000 tokens
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-1.5-pro": {"prompt": 0.0035, "completion": 0.0105},
    "gemini-1.5-flash": {"prompt": 0.000075, "completion": 0.0003},
    "claude-3-5-sonnet": {"prompt": 0.003, "completion": 0.015},
    "gpt-4o": {"prompt": 0.005, "completion": 0.015},
    "default": {"prompt": 0.002, "completion": 0.006},
}

# Compute cost per millisecond ($0.00000002 / ms = $0.072 / hour)
COMPUTE_COST_PER_MS = 0.00000002


class EnterpriseCostManager:
    """Manages multi-tenant operational cost attribution and departmental spending envelopes."""

    def __init__(
        self,
        org_manager: EnterpriseOrganizationManager,
        iam_engine: EnterpriseIAMEngine,
        storage: Any = None,
    ) -> None:
        self.org_manager = org_manager
        self.iam_engine = iam_engine
        self.storage = storage or getattr(org_manager, "storage", None)
        self._lock = threading.RLock()
        self._budgets: dict[str, DepartmentBudget] = {}  # dept_id -> DepartmentBudget
        self._cost_records: dict[str, list[CostRecord]] = {}  # org_id -> list of CostRecord

    def set_department_budget(
        self,
        caller_user_id: str,
        org_id: str,
        department_id: str,
        allocated_usd: float,
        alert_threshold_pct: float = 80.0,
        hard_cap_enabled: bool = True,
    ) -> DepartmentBudget:
        """Configure a departmental budget envelope with alert thresholds and hard spending cap."""
        with self._lock:
            self.iam_engine.assert_permission(
                user_id=caller_user_id,
                org_id=org_id,
                action=PermissionAction.BUDGET_MANAGE,
            )

            # Verify department belongs to org
            dept = self.org_manager.get_department(department_id, caller_org_id=org_id)
            if not dept:
                raise EnterpriseCostError(
                    f"Department '{department_id}' not found in org '{org_id}'"
                )

            budget_id = f"bgt_{uuid.uuid4().hex[:12]}"
            budget = DepartmentBudget(
                budget_id=budget_id,
                org_id=org_id,
                department_id=department_id,
                allocated_usd=allocated_usd,
                spent_usd=0.0,
                alert_threshold_pct=alert_threshold_pct,
                hard_cap_enabled=hard_cap_enabled,
            )

            self._budgets[department_id] = budget
            if self.storage:
                self.storage.save_budget(budget)
            logger.info(
                "Configured budget %s for dept %s: $%s (cap=%s, alert=%s%%)",
                budget_id,
                department_id,
                allocated_usd,
                hard_cap_enabled,
                alert_threshold_pct,
            )
            return budget

    def get_department_budget(self, org_id: str, department_id: str) -> DepartmentBudget | None:
        """Retrieve department budget, checking tenant boundary."""
        with self._lock:
            budget = self._budgets.get(department_id)
            if not budget and self.storage:
                budget = self.storage.get_budget(org_id, department_id)
                if budget:
                    self._budgets[department_id] = budget
            if budget and budget.org_id != org_id:
                raise CrossTenantAccessViolationError(
                    f"Cross-tenant access violation: caller org {org_id} != budget org {budget.org_id}"
                )
            return budget

    def check_budget_headroom(
        self,
        org_id: str,
        department_id: str | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> tuple[bool, str | None, bool]:
        """Check if an action is within budget limits.

        Returns (is_allowed, reason, is_alert_triggered).
        """
        with self._lock:
            if not department_id:
                return True, None, False

            budget = self._budgets.get(department_id)
            if not budget:
                return True, None, False

            if budget.org_id != org_id:
                raise CrossTenantAccessViolationError("Cross-tenant budget check denied")

            projected_spend = budget.spent_usd + estimated_cost_usd
            is_alert = (
                projected_spend / budget.allocated_usd * 100.0
            ) >= budget.alert_threshold_pct

            if budget.hard_cap_enabled and projected_spend > budget.allocated_usd:
                return (
                    False,
                    f"Department '{department_id}' budget cap exceeded: spending ${projected_spend:.2f} > limit ${budget.allocated_usd:.2f}",
                    is_alert,
                )

            return True, None, is_alert

    def record_usage(
        self,
        org_id: str,
        task_id: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        compute_duration_ms: int,
        department_id: str | None = None,
        agent_id: str | None = None,
    ) -> tuple[CostRecord, bool]:
        """Record resource consumption, calculate accurate pricing, and deduct from budget.

        Returns (CostRecord, is_alert_triggered).
        """
        with self._lock:
            rates = MODEL_PRICING.get(model_name, MODEL_PRICING["default"])
            token_cost = (prompt_tokens / 1000.0 * rates["prompt"]) + (
                completion_tokens / 1000.0 * rates["completion"]
            )
            compute_cost = compute_duration_ms * COMPUTE_COST_PER_MS
            total_cost = token_cost + compute_cost

            # Check and update budget
            is_alert = False
            if department_id:
                budget = self._budgets.get(department_id)
                if budget:
                    if budget.org_id != org_id:
                        raise CrossTenantAccessViolationError("Cross-tenant budget access denied")

                    if budget.hard_cap_enabled and (
                        budget.spent_usd + total_cost > budget.allocated_usd
                    ):
                        raise BudgetCapExceededError(
                            f"Execution halted: adding ${total_cost:.4f} breaches department budget cap (${budget.allocated_usd:.2f})"
                        )

                    budget.spent_usd += total_cost
                    if (
                        budget.spent_usd / budget.allocated_usd * 100.0
                    ) >= budget.alert_threshold_pct:
                        is_alert = True
                        logger.warning(
                            "Department %s spending reached %.1f%% of budget envelope ($%.2f / $%.2f)",
                            department_id,
                            (budget.spent_usd / budget.allocated_usd * 100.0),
                            budget.spent_usd,
                            budget.allocated_usd,
                        )

            rec = CostRecord(
                record_id=f"cst_{uuid.uuid4().hex[:12]}",
                org_id=org_id,
                department_id=department_id,
                task_id=task_id,
                agent_id=agent_id,
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                compute_duration_ms=compute_duration_ms,
                token_cost_usd=round(token_cost, 6),
                compute_cost_usd=round(compute_cost, 6),
                total_cost_usd=round(total_cost, 6),
            )

            records = self._cost_records.setdefault(org_id, [])
            records.append(rec)
            if self.storage:
                self.storage.save_cost_record(rec)
                if department_id and budget:
                    self.storage.save_budget(budget)
            return rec, is_alert

    def get_cost_summary(
        self,
        caller_user_id: str,
        org_id: str,
        department_id: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate total cost, token consumption, and compute metrics for reporting."""
        with self._lock:
            self.iam_engine.assert_permission(
                user_id=caller_user_id,
                org_id=org_id,
                action=PermissionAction.COST_READ,
            )

            records = self._cost_records.get(org_id, [])
            total_spend = 0.0
            total_prompt_tokens = 0
            total_completion_tokens = 0
            total_compute_ms = 0
            by_model: dict[str, float] = {}

            for rec in records:
                if department_id and rec.department_id != department_id:
                    continue
                total_spend += rec.total_cost_usd
                total_prompt_tokens += rec.prompt_tokens
                total_completion_tokens += rec.completion_tokens
                total_compute_ms += rec.compute_duration_ms
                by_model[rec.model_name] = by_model.get(rec.model_name, 0.0) + rec.total_cost_usd

            budget_info = None
            if department_id and department_id in self._budgets:
                b = self._budgets[department_id]
                budget_info = {
                    "allocated_usd": b.allocated_usd,
                    "spent_usd": b.spent_usd,
                    "remaining_usd": max(0.0, b.allocated_usd - b.spent_usd),
                    "utilization_pct": round((b.spent_usd / b.allocated_usd * 100.0), 2)
                    if b.allocated_usd > 0
                    else 0.0,
                }

            return {
                "org_id": org_id,
                "department_id": department_id,
                "total_spend_usd": round(total_spend, 4),
                "total_tokens": total_prompt_tokens + total_completion_tokens,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_compute_ms": total_compute_ms,
                "cost_by_model": {k: round(v, 4) for k, v in by_model.items()},
                "budget": budget_info,
            }
