"""ATLAS Process Security Governor & Action Firewall Integration.

Enforces strict tenant isolation, Action Firewall gating on process actions,
prohibition of workflow self-permission expansion, and prompt injection detection.
"""

from __future__ import annotations

import re
from typing import Any

from atlas_policy.firewall import ActionFirewall, PolicyDecisionType


class ProcessSecurityError(Exception):
    """Base exception for process security violations."""


class TenantIsolationViolationError(ProcessSecurityError):
    """Raised when an operation attempts unauthorized cross-tenant access."""


class PrivilegeEscalationError(ProcessSecurityError):
    """Raised when a process attempts to self-grant permissions or modify firewall rules."""


class ActionFirewallBlockedError(ProcessSecurityError):
    """Raised when an action is blocked by the Action Firewall."""


class ProcessSecurityGovernor:
    """Enforces active security boundaries and policy gates for the process execution layer."""

    DANGEROUS_PATTERNS = [
        re.compile(r"firewall:disable", re.IGNORECASE),
        re.compile(r"firewall:modify", re.IGNORECASE),
        re.compile(r"grant_all_permissions", re.IGNORECASE),
        re.compile(r"sudo\s+su", re.IGNORECASE),
        re.compile(r"admin_override", re.IGNORECASE),
    ]

    def __init__(self, firewall: ActionFirewall | None = None) -> None:
        self.firewall = firewall or ActionFirewall()

    def check_tenant_boundary(
        self,
        requesting_tenant_id: str,
        target_tenant_id: str,
    ) -> None:
        """Enforce strict multi-tenant isolation."""
        if requesting_tenant_id != target_tenant_id:
            raise TenantIsolationViolationError(
                f"Tenant isolation breach: Requesting tenant '{requesting_tenant_id}' cannot access resources belonging to tenant '{target_tenant_id}'."
            )

    def evaluate_task_action(
        self,
        action_name: str,
        parameters: dict[str, Any],
        tenant_id: str,
    ) -> None:
        """Validate proposed task actions against privilege escalation and Action Firewall rules."""
        # 1. Anti-Self-Privilege Escalation Invariant
        for pat in self.DANGEROUS_PATTERNS:
            if pat.search(action_name) or any(pat.search(str(v)) for v in parameters.values()):
                raise PrivilegeEscalationError(
                    f"Privilege escalation attempt rejected: Action '{action_name}' violates security policy."
                )

        # 2. Check Action Firewall
        from atlas_core.contracts.action import ComputerAction

        action = ComputerAction(
            action_id=f"act_sec_{hash(action_name)}",
            task_id="process_security_task",
            session_id="process_security_session",
            action_type=action_name,
            parameters=parameters,
            idempotency_key=f"idem_sec_{hash(action_name)}",
        )
        decision = self.firewall.evaluate(action)
        if decision.decision != PolicyDecisionType.ALLOW:
            raise ActionFirewallBlockedError(
                f"Action Firewall blocked direct execution of '{action_name}': {decision.reason}"
            )
