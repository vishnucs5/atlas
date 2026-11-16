"""ATLAS Strategy Optimization Engine.

Performs multi-objective optimization across candidate strategies against fixed
baselines, enforcing Pareto superiority and preventing safety degradation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StrategyCandidate(BaseModel):
    """A parameterized operational strategy proposed for task execution."""

    strategy_id: str
    name: str
    version: str = "1.0.0"
    parameters: dict[str, Any] = Field(default_factory=dict)
    success_rate: float = 0.0  # [0.0, 1.0]
    avg_duration_sec: float = 0.0
    avg_cost_usd: float = 0.0
    recovery_rate: float = 0.0
    verification_quality: float = 1.0  # [0.0, 1.0]
    policy_compliance_rate: float = 1.0  # [0.0, 1.0]


class OptimizationResult(BaseModel):
    """Result of comparing an optimization candidate against an established baseline."""

    selected_strategy_id: str
    baseline_strategy_id: str
    is_pareto_improvement: bool
    is_acceptable: bool
    composite_utility_score: float
    delta_metrics: dict[str, float] = Field(default_factory=dict)
    decision_rationale: str


class StrategyOptimizationEngine:
    """Compares candidate strategies against fixed baselines with safety constraints."""

    DEFAULT_WEIGHTS = {
        "success_rate": 0.40,
        "verification_quality": 0.25,
        "duration": 0.15,
        "cost": 0.20,
    }

    @classmethod
    def compute_utility(
        cls,
        candidate: StrategyCandidate,
        max_duration: float = 60.0,
        max_cost: float = 0.10,
        weights: dict[str, float] | None = None,
    ) -> float:
        """Compute normalized composite utility score in range [0.0, 1.0]."""
        w = weights or cls.DEFAULT_WEIGHTS

        # Normalize duration and cost (lower is better)
        norm_duration = max(
            0.0, min(1.0, 1.0 - (candidate.avg_duration_sec / max(max_duration, 1.0)))
        )
        norm_cost = max(0.0, min(1.0, 1.0 - (candidate.avg_cost_usd / max(max_cost, 0.001))))

        utility = (
            (candidate.success_rate * w["success_rate"])
            + (candidate.verification_quality * w["verification_quality"])
            + (norm_duration * w["duration"])
            + (norm_cost * w["cost"])
        )
        return round(utility, 4)

    @classmethod
    def compare_strategies(
        cls,
        candidate: StrategyCandidate,
        baseline: StrategyCandidate,
        weights: dict[str, float] | None = None,
    ) -> OptimizationResult:
        """Compare candidate against baseline, enforcing strict non-degradation of safety."""
        delta_success = candidate.success_rate - baseline.success_rate
        delta_duration = baseline.avg_duration_sec - candidate.avg_duration_sec  # positive = faster
        delta_cost = baseline.avg_cost_usd - candidate.avg_cost_usd  # positive = cheaper
        delta_verification = candidate.verification_quality - baseline.verification_quality
        delta_compliance = candidate.policy_compliance_rate - baseline.policy_compliance_rate

        deltas = {
            "delta_success_rate": round(delta_success, 4),
            "delta_duration_sec": round(delta_duration, 4),
            "delta_cost_usd": round(delta_cost, 4),
            "delta_verification_quality": round(delta_verification, 4),
            "delta_policy_compliance": round(delta_compliance, 4),
        }

        # 1. Non-negotiable safety invariant:
        # A candidate must NEVER degrade policy compliance or verification quality
        if delta_compliance < 0.0:
            return OptimizationResult(
                selected_strategy_id=baseline.strategy_id,
                baseline_strategy_id=baseline.strategy_id,
                is_pareto_improvement=False,
                is_acceptable=False,
                composite_utility_score=cls.compute_utility(baseline, weights=weights),
                delta_metrics=deltas,
                decision_rationale=(
                    f"Rejected candidate '{candidate.strategy_id}': Policy compliance degraded "
                    f"by {abs(delta_compliance):.2%}. Safety is non-compensable."
                ),
            )

        if delta_verification < -0.01:
            return OptimizationResult(
                selected_strategy_id=baseline.strategy_id,
                baseline_strategy_id=baseline.strategy_id,
                is_pareto_improvement=False,
                is_acceptable=False,
                composite_utility_score=cls.compute_utility(baseline, weights=weights),
                delta_metrics=deltas,
                decision_rationale=(
                    f"Rejected candidate '{candidate.strategy_id}': Verification quality degraded "
                    f"by {abs(delta_verification):.2%}. Cannot trade correctness for performance."
                ),
            )

        # 2. Check Pareto dominance
        is_pareto = (
            delta_success >= 0
            and delta_duration >= 0
            and delta_cost >= 0
            and delta_verification >= 0
            and any([delta_success > 0, delta_duration > 0, delta_cost > 0])
        )

        cand_utility = cls.compute_utility(candidate, weights=weights)
        base_utility = cls.compute_utility(baseline, weights=weights)

        is_acceptable = is_pareto or (cand_utility > base_utility and delta_success >= 0)

        selected = candidate.strategy_id if is_acceptable else baseline.strategy_id
        rationale = (
            f"Candidate '{candidate.strategy_id}' accepted: Pareto improvement or higher utility "
            f"({cand_utility} vs {base_utility}) without safety degradation."
            if is_acceptable
            else f"Baseline '{baseline.strategy_id}' retained: Candidate did not demonstrate superior utility."
        )

        return OptimizationResult(
            selected_strategy_id=selected,
            baseline_strategy_id=baseline.strategy_id,
            is_pareto_improvement=is_pareto,
            is_acceptable=is_acceptable,
            composite_utility_score=cand_utility if is_acceptable else base_utility,
            delta_metrics=deltas,
            decision_rationale=rationale,
        )
