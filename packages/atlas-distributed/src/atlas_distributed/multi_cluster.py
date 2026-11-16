"""Multi-Cluster Orchestration and Global Task Placement Engine for ATLAS."""

from __future__ import annotations

import enum
import logging
import time

from pydantic import BaseModel, Field

logger = logging.getLogger("atlas.distributed.multi_cluster")


class ClusterStatus(enum.StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    REVOKED = "REVOKED"


class ClusterCapabilities(BaseModel):
    """Hardware and software capabilities of a registered cluster."""

    platforms: list[str] = Field(default_factory=lambda: ["linux/amd64"])
    gpu_models: list[str] = Field(default_factory=list)
    runtimes: list[str] = Field(default_factory=lambda: ["playwright", "python", "cli"])
    max_workers: int = 100
    supports_desktop_session: bool = False


class ClusterNodeRecord(BaseModel):
    """Metadata and operational state of an enrolled cluster."""

    cluster_id: str
    name: str
    region: str
    api_endpoint: str
    auth_token: str
    status: ClusterStatus = ClusterStatus.HEALTHY
    capabilities: ClusterCapabilities = Field(default_factory=ClusterCapabilities)
    tenant_allowed_list: list[str] = Field(default_factory=list)  # Empty means all tenants
    active_workers: int = 0
    latency_ms: float = 10.0
    last_heartbeat: float = Field(default_factory=time.time)
    consecutive_failures: int = 0


class ClusterTaskRequirements(BaseModel):
    """Task requirements evaluated by the global cluster placement engine."""

    task_id: str
    tenant_id: str
    preferred_region: str | None = None
    required_platform: str = "linux/amd64"
    required_gpu: str | None = None
    required_runtime: str | None = None
    requires_desktop: bool = False
    max_latency_ms: float = 500.0


class MultiClusterManager:
    """Manages the federated cluster registry, health monitoring, and global scheduling."""

    def __init__(self, heartbeat_timeout_seconds: float = 30.0) -> None:
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._clusters: dict[str, ClusterNodeRecord] = {}
        self._cluster_assignments: dict[str, str] = {}  # task_id -> cluster_id
        self._fenced_workers: set[str] = set()

    def register_cluster(
        self,
        cluster_id: str,
        name: str,
        region: str,
        api_endpoint: str,
        auth_token: str,
        capabilities: ClusterCapabilities | None = None,
        tenant_allowed_list: list[str] | None = None,
    ) -> ClusterNodeRecord:
        """Register or update an enrolled Kubernetes cluster."""
        if not cluster_id.startswith("cls_"):
            raise ValueError(f"Cluster ID must start with 'cls_': {cluster_id}")

        record = ClusterNodeRecord(
            cluster_id=cluster_id,
            name=name,
            region=region,
            api_endpoint=api_endpoint,
            auth_token=auth_token,
            capabilities=capabilities or ClusterCapabilities(),
            tenant_allowed_list=tenant_allowed_list or [],
        )
        self._clusters[cluster_id] = record
        logger.info(f"Registered cluster '{name}' ({cluster_id}) in region '{region}'")
        return record

    def heartbeat(self, cluster_id: str, active_workers: int, latency_ms: float = 10.0) -> bool:
        """Process cluster heartbeat and update health state."""
        cluster = self._clusters.get(cluster_id)
        if not cluster:
            return False

        if cluster.status == ClusterStatus.REVOKED:
            logger.warning(f"Heartbeat rejected for REVOKED cluster '{cluster_id}'")
            return False

        cluster.last_heartbeat = time.time()
        cluster.active_workers = active_workers
        cluster.latency_ms = latency_ms
        cluster.consecutive_failures = 0
        cluster.status = ClusterStatus.HEALTHY if latency_ms < 300.0 else ClusterStatus.DEGRADED
        return True

    def check_health_and_failover(self) -> list[str]:
        """Audit cluster heartbeats, mark dead clusters disconnected, and trigger failover."""
        now = time.time()
        disconnected_clusters = []

        for cid, cluster in self._clusters.items():
            if cluster.status in (
                ClusterStatus.DISCONNECTED,
                ClusterStatus.REVOKED,
            ):
                continue

            if now - cluster.last_heartbeat > self.heartbeat_timeout_seconds:
                cluster.consecutive_failures += 1
                if cluster.consecutive_failures >= 3:
                    cluster.status = ClusterStatus.DISCONNECTED
                    disconnected_clusters.append(cid)
                    logger.error(
                        f"Cluster '{cid}' marked DISCONNECTED after {cluster.consecutive_failures} failed heartbeats"
                    )

        return disconnected_clusters

    def select_cluster_for_task(self, req: ClusterTaskRequirements) -> str | None:
        """Global scheduler placing task onto the optimal cluster matching capabilities and tenant policy."""
        now = time.time()
        eligible_candidates: list[tuple[float, str]] = []

        for cid, cluster in self._clusters.items():
            # 1. Cluster must be healthy or degraded (not disconnected/revoked)
            if cluster.status not in (
                ClusterStatus.HEALTHY,
                ClusterStatus.DEGRADED,
            ):
                continue

            # 2. Heartbeat freshness
            if now - cluster.last_heartbeat > self.heartbeat_timeout_seconds:
                continue

            # 3. Tenant authorization check
            if cluster.tenant_allowed_list and req.tenant_id not in cluster.tenant_allowed_list:
                continue

            # 4. Latency check
            if cluster.latency_ms > req.max_latency_ms:
                continue

            # 5. Platform capability match
            if req.required_platform not in cluster.capabilities.platforms:
                continue

            # 6. Desktop session match
            if req.requires_desktop and not cluster.capabilities.supports_desktop_session:
                continue

            # 7. GPU requirement match
            if req.required_gpu and req.required_gpu not in cluster.capabilities.gpu_models:
                continue

            # 8. Runtime match
            if req.required_runtime and req.required_runtime not in cluster.capabilities.runtimes:
                continue

            # Compute affinity score (lower is better)
            score = cluster.latency_ms
            # Prefer locality
            if req.preferred_region and cluster.region == req.preferred_region:
                score -= 50.0  # Regional affinity bonus

            # Prefer less utilized clusters
            utilization_penalty = (
                cluster.active_workers / max(1, cluster.capabilities.max_workers)
            ) * 20.0
            score += utilization_penalty

            eligible_candidates.append((score, cid))

        if not eligible_candidates:
            return None

        eligible_candidates.sort(key=lambda x: x[0])
        best_cluster_id = eligible_candidates[0][1]
        self._cluster_assignments[req.task_id] = best_cluster_id
        return best_cluster_id

    def failover_tasks_from_cluster(self, disconnected_cluster_id: str) -> list[str]:
        """Fence disconnected cluster and extract tasks requiring reassignment."""
        orphaned_tasks = []
        for task_id, cid in list(self._cluster_assignments.items()):
            if cid == disconnected_cluster_id:
                orphaned_tasks.append(task_id)
                del self._cluster_assignments[task_id]

        # Fence all workers associated with this cluster
        self._fenced_workers.add(disconnected_cluster_id)
        logger.info(
            f"Fenced cluster '{disconnected_cluster_id}' and extracted {len(orphaned_tasks)} tasks for failover"
        )
        return orphaned_tasks

    def revoke_cluster(self, cluster_id: str) -> bool:
        """Revoke a cluster, blacklisting its credentials and aborting assigned tasks."""
        cluster = self._clusters.get(cluster_id)
        if not cluster:
            return False

        cluster.status = ClusterStatus.REVOKED
        self._fenced_workers.add(cluster_id)
        logger.warning(f"Cluster '{cluster_id}' has been permanently REVOKED")
        return True

    def is_fenced(self, cluster_id: str) -> bool:
        """Check if cluster or its workers are fenced."""
        return cluster_id in self._fenced_workers
