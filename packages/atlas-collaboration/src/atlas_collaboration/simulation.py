"""Hermetic Policy Simulation Sandbox for Monte Carlo Governance Replay."""

from __future__ import annotations

from typing import Any


class SimulationSandboxViolationError(RuntimeError):
    """Raised when an unmocked live production connector or live credential is used in simulation."""


class DryRunConnectorDriver:
    """Mock connector driver executing strictly in-memory without external network egress."""

    def __init__(self, connector_type: str, mock_data: dict[str, Any] | None = None) -> None:
        self.connector_type = connector_type
        self.mock_data = mock_data or {}
        self.executed_calls: list[dict[str, Any]] = []

    def execute(self, action: str, parameters: dict[str, Any]) -> dict[str, Any]:
        self.executed_calls.append({"action": action, "parameters": parameters})
        return self.mock_data.get(action, {"status": "SIMULATED_SUCCESS", "action": action})


class PolicySimulationEngine:
    """Evaluates draft policies against historical workflow runs without side effects."""

    def __init__(self, connectors: dict[str, DryRunConnectorDriver]) -> None:
        for name, driver in connectors.items():
            if not isinstance(driver, DryRunConnectorDriver):
                raise SimulationSandboxViolationError(
                    f"Connector '{name}' must be an instance of DryRunConnectorDriver in simulation."
                )
        self.connectors = connectors

    def evaluate_draft_policy(
        self,
        policy_rule: dict[str, Any],
        historical_runs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run Monte Carlo simulation of policy rule over historical execution logs."""
        total_evaluated = len(historical_runs)
        allowed_count = 0
        denied_count = 0
        approvals_required = 0

        max_amount = policy_rule.get("max_amount_usd", float("inf"))
        restricted_actions = set(policy_rule.get("restricted_actions", []))

        for run in historical_runs:
            amount = run.get("parameters", {}).get("amount_usd", 0.0)
            action = run.get("action", "")

            if action in restricted_actions:
                denied_count += 1
            elif amount > max_amount:
                approvals_required += 1
            else:
                allowed_count += 1

        pass_rate = (allowed_count / total_evaluated) if total_evaluated > 0 else 1.0

        return {
            "total_evaluated": total_evaluated,
            "allowed": allowed_count,
            "denied": denied_count,
            "approvals_required": approvals_required,
            "estimated_pass_rate": round(pass_rate, 4),
            "safe_for_deployment": denied_count == 0,
        }
