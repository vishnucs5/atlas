"""Infrastructure and Kubernetes Prometheus Metrics for ATLAS."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field


class MetricSample(BaseModel):
    name: str
    value: float
    labels: dict[str, str] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class AtlasInfrastructureMetrics:
    """Collects and formats Prometheus metrics for Kubernetes clusters, workers, and autoscaling."""

    def __init__(self) -> None:
        self._samples: list[MetricSample] = []

    def record_cluster_availability(self, cluster_id: str, region: str, is_available: bool) -> None:
        self._samples.append(
            MetricSample(
                name="atlas_cluster_availability",
                value=1.0 if is_available else 0.0,
                labels={"cluster_id": cluster_id, "region": region},
            )
        )

    def record_pod_health(self, pod_name: str, component: str, is_ready: bool) -> None:
        self._samples.append(
            MetricSample(
                name="atlas_pod_health_status",
                value=1.0 if is_ready else 0.0,
                labels={"pod_name": pod_name, "component": component},
            )
        )

    def record_worker_count(self, pool_name: str, cluster_id: str, count: int) -> None:
        self._samples.append(
            MetricSample(
                name="atlas_worker_active_count",
                value=float(count),
                labels={"pool_name": pool_name, "cluster_id": cluster_id},
            )
        )

    def record_scheduler_latency(self, cluster_id: str, latency_seconds: float) -> None:
        self._samples.append(
            MetricSample(
                name="atlas_scheduler_latency_seconds",
                value=latency_seconds,
                labels={"cluster_id": cluster_id},
            )
        )

    def record_queue_depth(self, tenant_id: str, priority: str, depth: int) -> None:
        self._samples.append(
            MetricSample(
                name="atlas_queue_depth",
                value=float(depth),
                labels={"tenant_id": tenant_id, "priority": priority},
            )
        )

    def record_gpu_utilization(
        self, worker_id: str, gpu_index: int, model: str, ratio: float
    ) -> None:
        self._samples.append(
            MetricSample(
                name="atlas_gpu_utilization_ratio",
                value=max(0.0, min(1.0, ratio)),
                labels={
                    "worker_id": worker_id,
                    "gpu_index": str(gpu_index),
                    "model": model,
                },
            )
        )

    def record_autoscaler_event(self, pool_name: str, action: str) -> None:
        self._samples.append(
            MetricSample(
                name="atlas_autoscaler_events_total",
                value=1.0,
                labels={"pool_name": pool_name, "action": action},
            )
        )

    def render_prometheus_text(self) -> str:
        """Render metrics in standard Prometheus exposition format."""
        lines = []
        # Group by metric name
        by_name: dict[str, list[MetricSample]] = {}
        for s in self._samples:
            by_name.setdefault(s.name, []).append(s)

        for name, samples in by_name.items():
            lines.append(f"# HELP {name} ATLAS infrastructure metric")
            lines.append(f"# TYPE {name} {'counter' if name.endswith('_total') else 'gauge'}")
            for s in samples:
                label_str = ",".join(f'{k}="{v}"' for k, v in s.labels.items())
                if label_str:
                    lines.append(f"{name}{{{label_str}}} {s.value}")
                else:
                    lines.append(f"{name} {s.value}")

        return "\n".join(lines) + "\n"
