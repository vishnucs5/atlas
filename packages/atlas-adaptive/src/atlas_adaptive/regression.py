"""ATLAS Regression Intelligence System.

Monitors operational metrics against established versioned baselines and emits
structured alerts on performance degradation or safety violations.
"""

from __future__ import annotations

from pydantic import BaseModel


class RegressionAlert(BaseModel):
    """An alert detailing detected metric degradation against a fixed baseline."""

    metric_name: str
    baseline_value: float
    observed_value: float
    degradation_percent: float
    severity: str = "WARNING"  # WARNING, HIGH, CRITICAL
    message: str


class BaselineMetric(BaseModel):
    """A benchmark reference metric value with allowable degradation threshold."""

    metric_name: str
    baseline_value: float
    max_allowed_degradation_pct: float = 5.0  # e.g. 5% drop allowed before alert
    is_lower_better: bool = False  # True for latency, cost, retry_count; False for success_rate


class RegressionIntelligenceSystem:
    """Continuously evaluates execution batches against versioned benchmarks."""

    def __init__(self) -> None:
        self._baselines: dict[str, BaselineMetric] = {}

    def register_baseline(
        self,
        metric_name: str,
        baseline_value: float,
        max_allowed_degradation_pct: float = 5.0,
        is_lower_better: bool = False,
    ) -> None:
        """Register or update a benchmark baseline metric."""
        self._baselines[metric_name] = BaselineMetric(
            metric_name=metric_name,
            baseline_value=baseline_value,
            max_allowed_degradation_pct=max_allowed_degradation_pct,
            is_lower_better=is_lower_better,
        )

    def evaluate_metrics(
        self,
        observed_metrics: dict[str, float],
    ) -> list[RegressionAlert]:
        """Compare observed operational metrics against baselines and detect regressions."""
        alerts: list[RegressionAlert] = []

        for metric_name, observed_val in observed_metrics.items():
            baseline = self._baselines.get(metric_name)
            if not baseline or baseline.baseline_value == 0:
                continue

            if baseline.is_lower_better:
                # Latency, cost, error count: degradation means observed > baseline
                degradation = (
                    (observed_val - baseline.baseline_value) / baseline.baseline_value
                ) * 100.0
            else:
                # Success rate, quality score: degradation means observed < baseline
                degradation = (
                    (baseline.baseline_value - observed_val) / baseline.baseline_value
                ) * 100.0

            if degradation > baseline.max_allowed_degradation_pct:
                severity = (
                    "CRITICAL"
                    if degradation >= 15.0
                    else ("HIGH" if degradation >= 10.0 else "WARNING")
                )
                msg = (
                    f"Regression detected in '{metric_name}': Observed {observed_val:.4f} "
                    f"degraded by {degradation:.1f}% against baseline {baseline.baseline_value:.4f} "
                    f"(allowed threshold: {baseline.max_allowed_degradation_pct}%)."
                )
                alerts.append(
                    RegressionAlert(
                        metric_name=metric_name,
                        baseline_value=baseline.baseline_value,
                        observed_value=observed_val,
                        degradation_percent=round(degradation, 2),
                        severity=severity,
                        message=msg,
                    )
                )

        return alerts

    @staticmethod
    def has_critical_regression(alerts: list[RegressionAlert]) -> bool:
        """Check if any alert in the list has HIGH or CRITICAL severity."""
        return any(a.severity in ("HIGH", "CRITICAL") for a in alerts)
