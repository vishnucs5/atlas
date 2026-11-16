"""ATLAS Agent Performance Intelligence.

Tracks specialist agent execution outcomes, aggregates performance metrics,
and enforces strict prohibitions against autonomous permission escalation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentMetrics(BaseModel):
    """Aggregated performance metrics for a specialist agent."""

    agent_id: str
    role: str
    task_count: int = 0
    successful_tasks: int = 0
    verified_tasks: int = 0
    total_cost_usd: float = 0.0
    total_duration_sec: float = 0.0
    recovery_count: int = 0
    policy_denials: int = 0
    assigned_permissions: list[str] = Field(default_factory=list)

    @property
    def completion_rate(self) -> float:
        return round(self.successful_tasks / max(self.task_count, 1), 4)

    @property
    def verification_rate(self) -> float:
        return round(self.verified_tasks / max(self.task_count, 1), 4)

    @property
    def avg_duration_sec(self) -> float:
        return round(self.total_duration_sec / max(self.task_count, 1), 2)

    @property
    def avg_cost_usd(self) -> float:
        return round(self.total_cost_usd / max(self.task_count, 1), 4)


class AgentPerformanceIntelligence:
    """Monitors specialist agents and prevents autonomous permission creep."""

    def __init__(self) -> None:
        self._metrics: dict[str, AgentMetrics] = {}

    def record_task_execution(
        self,
        agent_id: str,
        role: str,
        is_success: bool,
        is_verified: bool,
        duration_sec: float,
        cost_usd: float,
        recovery_count: int = 0,
        policy_denials: int = 0,
        assigned_permissions: list[str] | None = None,
    ) -> AgentMetrics:
        """Record an individual task execution outcome for an agent."""
        metrics = self._metrics.get(agent_id)
        if not metrics:
            metrics = AgentMetrics(
                agent_id=agent_id,
                role=role,
                assigned_permissions=assigned_permissions or [],
            )
            self._metrics[agent_id] = metrics

        metrics.task_count += 1
        if is_success:
            metrics.successful_tasks += 1
        if is_verified:
            metrics.verified_tasks += 1
        metrics.total_duration_sec += duration_sec
        metrics.total_cost_usd += cost_usd
        metrics.recovery_count += recovery_count
        metrics.policy_denials += policy_denials

        return metrics

    def get_agent_metrics(self, agent_id: str) -> AgentMetrics | None:
        """Retrieve aggregated metrics for an agent."""
        return self._metrics.get(agent_id)

    def recommend_capability_adjustments(self, agent_id: str) -> list[str]:
        """Generate non-authoritative recommendations for agent optimization."""
        metrics = self._metrics.get(agent_id)
        if not metrics or metrics.task_count < 3:
            return ["Insufficient task volume to recommend capability adjustments."]

        recommendations: list[str] = []
        if metrics.completion_rate < 0.70:
            recommendations.append(
                "High failure rate observed: Recommend lower task complexity or fallback routing."
            )
        if metrics.policy_denials > 0:
            recommendations.append(
                f"Agent incurred {metrics.policy_denials} policy denial(s): Review prompt grounding to avoid forbidden actions."
            )
        if metrics.completion_rate >= 0.95 and metrics.verification_rate >= 0.95:
            recommendations.append(
                "High reliability agent: Recommended for high-priority task scheduling."
            )

        return recommendations

    def attempt_permission_auto_expansion(
        self,
        agent_id: str,
        requested_permission: str,
    ) -> None:
        """Enforces invariant: autonomous self-expansion of agent permissions is FORBIDDEN."""
        raise PermissionError(
            f"Autonomous permission escalation is strictly prohibited for agent '{agent_id}'! "
            f"Cannot grant permission '{requested_permission}'. "
            "Agent permissions remain strictly governed by administrator policy."
        )
