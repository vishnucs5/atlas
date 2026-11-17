"""ATLAS Process Intelligence and Analytics Engine.

Calculates cycle times, SLA compliance rates, bottleneck analysis, human intervention rates,
and tenant-scoped operational performance metrics.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from atlas_process.engine import ProcessInstance
from atlas_process.state_machine import ProcessStatus


class ProcessMetricsSummary(BaseModel):
    """Aggregated operational metrics for a process definition or tenant."""

    tenant_id: str
    total_instances: int = 0
    completed_instances: int = 0
    failed_instances: int = 0
    avg_cycle_time_seconds: float = 0.0
    sla_compliance_rate: float = 1.0
    human_intervention_rate: float = 0.0
    total_cost_usd: float = 0.0
    bottleneck_task_id: str | None = None
    step_duration_averages: dict[str, float] = Field(default_factory=dict)


class ProcessAnalyticsEngine:
    """Computes empirical metrics and bottleneck insights from recorded process instances."""

    def __init__(self) -> None:
        self._completed_instances: list[ProcessInstance] = []

    def record_completed_process(self, instance: ProcessInstance) -> None:
        """Register a completed or terminated process instance for analytics."""
        self._completed_instances.append(instance)

    def compute_summary(self, tenant_id: str) -> ProcessMetricsSummary:
        """Calculate comprehensive operational metrics for a tenant."""
        instances = [i for i in self._completed_instances if i.tenant_id == tenant_id]

        if not instances:
            return ProcessMetricsSummary(tenant_id=tenant_id)

        total = len(instances)
        completed = sum(1 for i in instances if i.status == ProcessStatus.COMPLETED)
        failed = sum(1 for i in instances if i.status == ProcessStatus.FAILED)

        # Cycle times
        cycle_times: list[float] = []
        for inst in instances:
            if inst.completed_at and inst.created_at:
                cycle_times.append(inst.completed_at - inst.created_at)

        avg_cycle_time = sum(cycle_times) / len(cycle_times) if cycle_times else 0.0

        # Step durations and bottleneck calculation
        task_durations: dict[str, list[float]] = {}
        human_tasks_count = 0
        total_tasks_count = 0

        for inst in instances:
            for tdef_id, tinst in inst.task_instances.items():
                total_tasks_count += 1
                if tinst.task_type.value == "HUMAN_APPROVAL":
                    human_tasks_count += 1

                if tinst.completed_at and tinst.started_at:
                    dur = tinst.completed_at - tinst.started_at
                    task_durations.setdefault(tdef_id, []).append(dur)

        step_averages: dict[str, float] = {}
        for tdef_id, durs in task_durations.items():
            step_averages[tdef_id] = sum(durs) / len(durs)

        bottleneck_task = (
            max(step_averages.items(), key=lambda x: x[1])[0] if step_averages else None
        )

        human_rate = human_tasks_count / total_tasks_count if total_tasks_count > 0 else 0.0

        # Simulated SLA compliance (assumes instances completed < 3600s complied)
        sla_compliant_count = sum(1 for ct in cycle_times if ct <= 3600.0)
        sla_rate = sla_compliant_count / total if total > 0 else 1.0

        return ProcessMetricsSummary(
            tenant_id=tenant_id,
            total_instances=total,
            completed_instances=completed,
            failed_instances=failed,
            avg_cycle_time_seconds=round(avg_cycle_time, 2),
            sla_compliance_rate=round(sla_rate, 4),
            human_intervention_rate=round(human_rate, 4),
            bottleneck_task_id=bottleneck_task,
            step_duration_averages=step_averages,
        )
