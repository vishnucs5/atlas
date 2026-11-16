"""Workload-Aware Worker Autoscaler for ATLAS."""

from __future__ import annotations

import enum
import math
import time

from pydantic import BaseModel, Field


class ScalingAction(enum.StrEnum):
    SCALE_UP = "SCALE_UP"
    SCALE_DOWN = "SCALE_DOWN"
    NOOP = "NOOP"


class WorkloadMetrics(BaseModel):
    """Real-time workload and utilization signals from ATLAS Control Plane."""

    queue_depth: int = Field(default=0, ge=0)
    pending_assignments: int = Field(default=0, ge=0)
    active_workers: int = Field(default=1, ge=0)
    worker_capacity_each: int = Field(default=2, ge=1)
    critical_priority_tasks: int = Field(default=0, ge=0)
    tasks_near_deadline: int = Field(default=0, ge=0)
    average_cpu_percent: float = Field(default=20.0, ge=0.0, le=100.0)
    average_memory_percent: float = Field(default=30.0, ge=0.0, le=100.0)
    available_gpus: int = Field(default=0, ge=0)
    tenant_quota_max_workers: int = Field(default=100, ge=1)


class ScalingDecision(BaseModel):
    """Result of an autoscaling evaluation."""

    action: ScalingAction
    current_replicas: int
    desired_replicas: int
    reason: str
    evaluated_at: float = Field(default_factory=time.time)


class WorkloadAwareAutoscaler:
    """Computes desired worker fleet replicas from autonomous workload signals."""

    def __init__(
        self,
        min_replicas: int = 1,
        max_replicas: int = 20,
        target_tasks_per_worker: int = 4,
        scale_up_cooldown_seconds: float = 30.0,
        scale_down_cooldown_seconds: float = 120.0,
        max_scale_up_step: int = 5,
        max_scale_down_step: int = 2,
    ) -> None:
        self.min_replicas = max(0, min_replicas)
        self.max_replicas = max(self.min_replicas, max_replicas)
        self.target_tasks_per_worker = max(1, target_tasks_per_worker)
        self.scale_up_cooldown_seconds = scale_up_cooldown_seconds
        self.scale_down_cooldown_seconds = scale_down_cooldown_seconds
        self.max_scale_up_step = max_scale_up_step
        self.max_scale_down_step = max_scale_down_step

        self._last_scale_up_time: float = 0.0
        self._last_scale_down_time: float = 0.0

    def evaluate(self, current_replicas: int, metrics: WorkloadMetrics) -> ScalingDecision:
        """Evaluate workload signals and return an anti-flapping scaling decision."""
        now = time.time()

        # 1. Calculate effective task backlog with priority & SLA weighting
        weighted_backlog = (
            metrics.queue_depth
            + metrics.pending_assignments
            + (metrics.critical_priority_tasks * 2)
            + (metrics.tasks_near_deadline * 2)
        )

        # 2. Compute workload-driven desired replicas
        if weighted_backlog == 0 and metrics.average_cpu_percent < 50.0:
            target_replicas = self.min_replicas
            base_reason = "Zero task backlog and normal CPU utilization"
        else:
            # Replicas required to clear backlog within SLA
            needed_for_backlog = math.ceil(weighted_backlog / self.target_tasks_per_worker)
            target_replicas = max(self.min_replicas, needed_for_backlog)
            base_reason = f"Backlog requires {needed_for_backlog} workers (queue={metrics.queue_depth}, urgent={metrics.critical_priority_tasks + metrics.tasks_near_deadline})"

        # 3. Consider CPU/Memory pressure
        if metrics.average_cpu_percent > 80.0 or metrics.average_memory_percent > 85.0:
            target_replicas = max(target_replicas, math.ceil(current_replicas * 1.5))
            base_reason += f" with resource pressure (cpu={metrics.average_cpu_percent}%, mem={metrics.average_memory_percent}%)"

        # 4. Respect tenant quota ceiling
        if target_replicas > metrics.tenant_quota_max_workers:
            target_replicas = metrics.tenant_quota_max_workers
            base_reason += f" (clamped by tenant quota: {metrics.tenant_quota_max_workers})"

        # 5. Clamp to absolute min/max bounds
        target_replicas = max(self.min_replicas, min(self.max_replicas, target_replicas))

        # 6. Evaluate scale-up vs scale-down vs noop
        if target_replicas > current_replicas:
            # Check scale-up cooldown
            elapsed_since_up = now - self._last_scale_up_time
            if self._last_scale_up_time > 0 and elapsed_since_up < self.scale_up_cooldown_seconds:
                return ScalingDecision(
                    action=ScalingAction.NOOP,
                    current_replicas=current_replicas,
                    desired_replicas=current_replicas,
                    reason=f"Scale-up cooldown active ({elapsed_since_up:.1f}s / {self.scale_up_cooldown_seconds:.1f}s)",
                    evaluated_at=now,
                )

            # Apply step limit
            allowed_up = min(target_replicas, current_replicas + self.max_scale_up_step)
            self._last_scale_up_time = now
            return ScalingDecision(
                action=ScalingAction.SCALE_UP,
                current_replicas=current_replicas,
                desired_replicas=allowed_up,
                reason=f"Scaling up: {base_reason}",
                evaluated_at=now,
            )

        elif target_replicas < current_replicas:
            # Check scale-down cooldown
            elapsed_since_down = now - self._last_scale_down_time
            if (
                self._last_scale_down_time > 0
                and elapsed_since_down < self.scale_down_cooldown_seconds
            ):
                return ScalingDecision(
                    action=ScalingAction.NOOP,
                    current_replicas=current_replicas,
                    desired_replicas=current_replicas,
                    reason=f"Scale-down cooldown active ({elapsed_since_down:.1f}s / {self.scale_down_cooldown_seconds:.1f}s)",
                    evaluated_at=now,
                )

            # Apply step limit
            allowed_down = max(target_replicas, current_replicas - self.max_scale_down_step)
            self._last_scale_down_time = now
            return ScalingDecision(
                action=ScalingAction.SCALE_DOWN,
                current_replicas=current_replicas,
                desired_replicas=allowed_down,
                reason=f"Scaling down: {base_reason}",
                evaluated_at=now,
            )

        return ScalingDecision(
            action=ScalingAction.NOOP,
            current_replicas=current_replicas,
            desired_replicas=current_replicas,
            reason="Worker fleet is right-sized for current workload",
            evaluated_at=now,
        )
