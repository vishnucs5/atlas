"""ATLAS Task Evaluation Engine.

Evaluates task outcomes using deterministic verification evidence, enforces
multi-criteria scoring rubrics, and detects false-success claims.
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EvaluationError(Exception):
    """Base exception for evaluation operations."""


class TaskDomain(StrEnum):
    """Domains of automated tasks supported by ATLAS."""

    BROWSER = "BROWSER"
    DESKTOP = "DESKTOP"
    RESEARCH = "RESEARCH"
    CODING = "CODING"
    DOCUMENT = "DOCUMENT"
    DATA = "DATA"
    ENTERPRISE = "ENTERPRISE"


class TaskEvaluationMetric(BaseModel):
    """Quantitative performance measurements of a task execution."""

    execution_duration_sec: float = 0.0
    token_cost_usd: float = 0.0
    retry_count: int = 0
    recovery_count: int = 0
    policy_denials: int = 0
    human_interventions: int = 0


class TaskEvaluationResult(BaseModel):
    """Comprehensive evaluation report for a task execution."""

    evaluation_id: str = Field(default_factory=lambda: f"eval_{uuid.uuid4().hex[:10]}")
    task_id: str
    tenant_id: str
    domain: TaskDomain = TaskDomain.ENTERPRISE
    timestamp: float = Field(default_factory=time.time)
    is_completed: bool
    is_false_success: bool = False
    overall_score: float = 0.0  # [0.0, 1.0]
    functional_score: float = 0.0
    efficiency_score: float = 0.0
    reliability_score: float = 0.0
    compliance_score: float = 0.0
    verification_evidence_refs: list[str] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)
    metrics: TaskEvaluationMetric = Field(default_factory=TaskEvaluationMetric)


class TaskEvaluationEngine:
    """Evaluates task executions based on deterministic evidence and domain rubrics."""

    # Weights across standard dimensions
    WEIGHT_FUNCTIONAL = 0.40
    WEIGHT_EFFICIENCY = 0.20
    WEIGHT_RELIABILITY = 0.20
    WEIGHT_COMPLIANCE = 0.20

    @classmethod
    def evaluate_task(
        cls,
        task_id: str,
        tenant_id: str,
        reported_completed: bool,
        verification_evidence_refs: list[str],
        metrics: TaskEvaluationMetric,
        domain: TaskDomain = TaskDomain.ENTERPRISE,
        baseline_duration_sec: float = 30.0,
        baseline_cost_usd: float = 0.05,
        user_feedback_score: float | None = None,
        context: dict[str, Any] | None = None,
    ) -> TaskEvaluationResult:
        """Evaluate task performance against objective execution evidence."""
        failure_reasons: list[str] = []

        # 1. False Success Detection
        # If an agent claims completion without verifiable evidence, flag as false success
        is_false_success = False
        if reported_completed and not verification_evidence_refs:
            is_false_success = True
            failure_reasons.append(
                "False success detected: Task reported completed without verifiable execution evidence."
            )

        if not reported_completed:
            functional_score = 0.0
            failure_reasons.append("Task lifecycle status is not completed.")
        elif is_false_success:
            functional_score = 0.0
        else:
            functional_score = 1.0

        # 2. Compliance Score (penalize policy denials)
        if metrics.policy_denials > 0:
            compliance_score = max(0.0, 1.0 - (metrics.policy_denials * 0.5))
            failure_reasons.append(f"Recorded {metrics.policy_denials} policy denial(s).")
        else:
            compliance_score = 1.0

        # 3. Reliability Score (penalize retries, recoveries, human interventions)
        penalties = (
            (metrics.retry_count * 0.15)
            + (metrics.recovery_count * 0.30)
            + (metrics.human_interventions * 0.25)
        )
        reliability_score = max(0.0, 1.0 - penalties)

        # 4. Efficiency Score (measured against baselines)
        duration_ratio = baseline_duration_sec / max(metrics.execution_duration_sec, 0.1)
        cost_ratio = baseline_cost_usd / max(metrics.token_cost_usd, 0.0001)
        efficiency_score = min(1.0, max(0.0, (duration_ratio * 0.5) + (cost_ratio * 0.5)))

        # 5. Compute Overall Weighted Score
        if is_false_success or not reported_completed:
            overall_score = 0.0
        else:
            raw_score = (
                (functional_score * cls.WEIGHT_FUNCTIONAL)
                + (compliance_score * cls.WEIGHT_COMPLIANCE)
                + (reliability_score * cls.WEIGHT_RELIABILITY)
                + (efficiency_score * cls.WEIGHT_EFFICIENCY)
            )
            if user_feedback_score is not None:
                # Blend user feedback (20% weighting if provided)
                raw_score = (raw_score * 0.8) + (min(1.0, max(0.0, user_feedback_score)) * 0.2)
            overall_score = round(min(1.0, max(0.0, raw_score)), 4)

        return TaskEvaluationResult(
            task_id=task_id,
            tenant_id=tenant_id,
            domain=domain,
            is_completed=reported_completed and not is_false_success,
            is_false_success=is_false_success,
            overall_score=overall_score,
            functional_score=functional_score,
            efficiency_score=round(efficiency_score, 4),
            reliability_score=round(reliability_score, 4),
            compliance_score=round(compliance_score, 4),
            verification_evidence_refs=verification_evidence_refs,
            failure_reasons=failure_reasons,
            metrics=metrics,
        )
