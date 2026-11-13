"""Prometheus metrics collection and text exposition for ATLAS runtime observability."""

import threading
from collections import defaultdict


class MetricsRegistry:
    """Thread-safe Prometheus metrics registry supporting counters, gauges, and histograms."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[tuple[tuple[str, str], ...], float]] = defaultdict(
            lambda: defaultdict(float)
        )
        self._gauges: dict[str, dict[tuple[tuple[str, str], ...], float]] = defaultdict(
            lambda: defaultdict(float)
        )
        self._descriptions: dict[str, str] = {}
        self._types: dict[str, str] = {}

    def _normalize_labels(self, labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        if not labels:
            return ()
        return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

    def counter(self, name: str, description: str = "") -> None:
        """Register a counter metric."""
        with self._lock:
            self._types[name] = "counter"
            if description:
                self._descriptions[name] = description

    def gauge(self, name: str, description: str = "") -> None:
        """Register a gauge metric."""
        with self._lock:
            self._types[name] = "gauge"
            if description:
                self._descriptions[name] = description

    def inc_counter(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        """Increment a counter by value."""
        norm_labels = self._normalize_labels(labels)
        with self._lock:
            if name not in self._types:
                self._types[name] = "counter"
            self._counters[name][norm_labels] += value

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Set a gauge to an absolute value."""
        norm_labels = self._normalize_labels(labels)
        with self._lock:
            if name not in self._types:
                self._types[name] = "gauge"
            self._gauges[name][norm_labels] = value

    def inc_gauge(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        """Increment a gauge by value."""
        norm_labels = self._normalize_labels(labels)
        with self._lock:
            if name not in self._types:
                self._types[name] = "gauge"
            self._gauges[name][norm_labels] += value

    def dec_gauge(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        """Decrement a gauge by value."""
        norm_labels = self._normalize_labels(labels)
        with self._lock:
            if name not in self._types:
                self._types[name] = "gauge"
            self._gauges[name][norm_labels] -= value

    def export_prometheus_text(self) -> str:
        """Render all metrics in Prometheus text exposition format (version 0.0.4)."""
        lines: list[str] = []
        with self._lock:
            for name, mtype in sorted(self._types.items()):
                desc = self._descriptions.get(name, f"ATLAS metric {name}")
                lines.append(f"# HELP {name} {desc}")
                lines.append(f"# TYPE {name} {mtype}")

                series = (
                    self._counters.get(name, {})
                    if mtype == "counter"
                    else self._gauges.get(name, {})
                )
                if series:
                    for labels, val in sorted(series.items()):
                        if labels:
                            lbl_str = ",".join(f'{k}="{v}"' for k, v in labels)
                            lines.append(f"{name}{{{lbl_str}}} {val}")
                        else:
                            lines.append(f"{name} {val}")
                else:
                    lines.append(f"{name} 0")

        lines.append("")  # Trailing newline required by Prometheus spec
        return "\n".join(lines)


# Global process metrics registry
REGISTRY = MetricsRegistry()

# Standard ATLAS metrics registration
REGISTRY.counter("atlas_tasks_total", "Total tasks processed by status and priority")
REGISTRY.counter(
    "atlas_action_executions_total", "Total physical actions attempted by type and status"
)
REGISTRY.counter(
    "atlas_policy_evaluations_total", "Total policy evaluations by decision and risk level"
)
REGISTRY.counter(
    "atlas_queue_backpressure_rejections_total",
    "Total task submissions rejected due to queue saturation",
)
REGISTRY.gauge("atlas_active_workers", "Number of currently registered healthy worker nodes")
REGISTRY.gauge(
    "atlas_pending_approvals", "Number of human approval requests awaiting operator decision"
)
REGISTRY.gauge("atlas_active_tasks", "Number of currently active executing tasks")
