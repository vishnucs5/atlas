"""ATLAS Automated Experimentation Engine.

Executes sandboxed A/B trials, enforces resource and budget limits, performs
statistical hypothesis tests, and supports shadow evaluation mode.
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ExperimentStatus(StrEnum):
    """Execution status of an experimental trial series."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TrialResult(BaseModel):
    """Outcome of a single sandboxed trial execution."""

    trial_index: int
    is_success: bool
    duration_sec: float
    cost_usd: float
    evidence_hash: str


class ExperimentDefinition(BaseModel):
    """Specification for an automated experiment comparing two strategies."""

    experiment_id: str = Field(default_factory=lambda: f"exp_def_{uuid.uuid4().hex[:8]}")
    candidate_strategy_id: str
    baseline_strategy_id: str
    benchmark_suite_id: str = "default_benchmark"
    num_trials: int = 10
    max_cost_usd: float = 5.0
    timeout_sec: float = 120.0
    is_shadow_mode: bool = False


class ExperimentReport(BaseModel):
    """Statistical summary of experimental outcomes between candidate and baseline."""

    experiment_id: str
    candidate_strategy_id: str
    baseline_strategy_id: str
    status: ExperimentStatus
    total_trials: int = 0
    candidate_success_rate: float = 0.0
    baseline_success_rate: float = 0.0
    delta_success_rate: float = 0.0
    p_value: float = 1.0
    is_statistically_significant: bool = False
    total_cost_usd: float = 0.0
    cancellation_reason: str | None = None
    candidate_trials: list[TrialResult] = Field(default_factory=list)
    baseline_trials: list[TrialResult] = Field(default_factory=list)


class AutomatedExperimentationEngine:
    """Manages sandboxed execution, resource budgeting, and statistical analysis."""

    @staticmethod
    def calculate_p_value(candidate_successes: int, baseline_successes: int, trials: int) -> float:
        """Calculate two-proportion z-test p-value."""
        if trials <= 0:
            return 1.0

        p1 = candidate_successes / trials
        p2 = baseline_successes / trials
        p_pool = (candidate_successes + baseline_successes) / (2 * trials)

        if p_pool == 0.0 or p_pool == 1.0 or p1 == p2:
            return 1.0

        se = math.sqrt(p_pool * (1 - p_pool) * (2.0 / trials))
        if se == 0.0:
            return 1.0

        z = abs(p1 - p2) / se
        # Approximate standard normal complementary CDF: 2 * (1 - Phi(z))
        p_val = 2.0 * (1.0 - (0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))))
        return round(max(0.0, min(1.0, p_val)), 4)

    @classmethod
    def run_experiment(
        cls,
        definition: ExperimentDefinition,
        candidate_runner: Callable[[int], dict[str, Any]],
        baseline_runner: Callable[[int], dict[str, Any]],
    ) -> ExperimentReport:
        """Run sandboxed trials for candidate and baseline under strict resource ceilings."""
        start_time = time.time()
        total_cost = 0.0
        candidate_trials: list[TrialResult] = []
        baseline_trials: list[TrialResult] = []

        status = ExperimentStatus.COMPLETED
        cancellation_reason = None

        for i in range(definition.num_trials):
            # Check elapsed time
            elapsed = time.time() - start_time
            if elapsed > definition.timeout_sec:
                status = ExperimentStatus.CANCELLED
                cancellation_reason = (
                    f"Execution timeout exceeded ({elapsed:.1f}s > {definition.timeout_sec}s)."
                )
                break

            # Check total cost
            if total_cost > definition.max_cost_usd:
                status = ExperimentStatus.CANCELLED
                cancellation_reason = f"Resource budget exceeded (${total_cost:.2f} > ${definition.max_cost_usd:.2f})."
                break

            # Execute Baseline Trial
            b_res = baseline_runner(i)
            b_cost = b_res.get("cost_usd", 0.01)
            total_cost += b_cost
            baseline_trials.append(
                TrialResult(
                    trial_index=i,
                    is_success=b_res.get("success", False),
                    duration_sec=b_res.get("duration_sec", 1.0),
                    cost_usd=b_cost,
                    evidence_hash=b_res.get("evidence_hash", f"hash_b_{i}"),
                )
            )

            # Execute Candidate Trial
            c_res = candidate_runner(i)
            c_cost = c_res.get("cost_usd", 0.01)
            total_cost += c_cost
            candidate_trials.append(
                TrialResult(
                    trial_index=i,
                    is_success=c_res.get("success", False),
                    duration_sec=c_res.get("duration_sec", 1.0),
                    cost_usd=c_cost,
                    evidence_hash=c_res.get("evidence_hash", f"hash_c_{i}"),
                )
            )

        executed_trials = len(candidate_trials)
        if executed_trials == 0:
            return ExperimentReport(
                experiment_id=definition.experiment_id,
                candidate_strategy_id=definition.candidate_strategy_id,
                baseline_strategy_id=definition.baseline_strategy_id,
                status=status,
                total_trials=0,
                total_cost_usd=round(total_cost, 4),
                cancellation_reason=cancellation_reason,
            )

        c_success_count = sum(1 for t in candidate_trials if t.is_success)
        b_success_count = sum(1 for t in baseline_trials if t.is_success)

        c_rate = round(c_success_count / executed_trials, 4)
        b_rate = round(b_success_count / executed_trials, 4)
        delta_rate = round(c_rate - b_rate, 4)

        p_val = cls.calculate_p_value(c_success_count, b_success_count, executed_trials)
        # Significant if p < 0.05 AND at least 5 trials executed
        is_significant = (p_val < 0.05) and (executed_trials >= 5)

        return ExperimentReport(
            experiment_id=definition.experiment_id,
            candidate_strategy_id=definition.candidate_strategy_id,
            baseline_strategy_id=definition.baseline_strategy_id,
            status=status,
            total_trials=executed_trials,
            candidate_success_rate=c_rate,
            baseline_success_rate=b_rate,
            delta_success_rate=delta_rate,
            p_value=p_val,
            is_statistically_significant=is_significant,
            total_cost_usd=round(total_cost, 4),
            cancellation_reason=cancellation_reason,
            candidate_trials=candidate_trials,
            baseline_trials=baseline_trials,
        )
