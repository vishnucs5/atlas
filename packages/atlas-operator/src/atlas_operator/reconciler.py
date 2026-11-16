"""ATLAS Kubernetes Operator Reconciliation Engine."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from atlas_operator.models import (
    AtlasAgentPool,
    AtlasAgentPoolStatus,
    AtlasCluster,
    AtlasClusterStatus,
    AtlasDeployment,
    AtlasDeploymentStatus,
    AtlasExecutionPolicy,
    AtlasExecutionPolicyStatus,
    AtlasWorkerPool,
    AtlasWorkerPoolStatus,
    ClusterPhase,
    DeploymentPhase,
    ResourceCondition,
    ScalingPhase,
)

logger = logging.getLogger("atlas.operator.reconciler")


class AtlasOperatorController:
    """Core controller loop executing idempotent reconciliation for ATLAS Custom Resources."""

    FINALIZER_NAME = "atlas.io/finalizer"

    def __init__(self) -> None:
        # In-memory simulated cluster state store for testing and disconnected controller execution
        self._managed_deployments: dict[str, dict[str, Any]] = {}
        self._managed_network_policies: dict[str, dict[str, Any]] = {}
        self._active_worker_leases: dict[str, set[str]] = {}  # pool_key -> {lease_id, ...}
        self._revision_history: dict[
            str, list[dict[str, Any]]
        ] = {}  # deployment_name -> [revisions]
        self._reconcile_count = 0

    # --- 1. AtlasCluster Reconciliation ---

    def reconcile_cluster(
        self,
        cluster: AtlasCluster,
        is_reachable: bool = True,
        latency_ms: float = 10.0,
    ) -> AtlasClusterStatus:
        """Reconcile AtlasCluster custom resource."""
        self._reconcile_count += 1
        status = cluster.status.model_copy()

        if not is_reachable:
            status.phase = ClusterPhase.DISCONNECTED
            status.conditions = [
                ResourceCondition(
                    type="Ready",
                    status="False",
                    reason="ClusterUnreachable",
                    message=f"Failed to probe API endpoint {cluster.spec.api_endpoint}",
                )
            ]
            return status

        status.phase = ClusterPhase.HEALTHY
        status.last_heartbeat = datetime.now(UTC).isoformat()
        status.latency_ms = latency_ms
        status.conditions = [
            ResourceCondition(
                type="Ready",
                status="True",
                reason="ClusterHealthy",
                message="Cluster API endpoint reachable and responsive",
            )
        ]
        return status

    # --- 2. AtlasWorkerPool Reconciliation ---

    def reconcile_worker_pool(
        self,
        pool: AtlasWorkerPool,
        active_tasks: int = 0,
        drain_requested: bool = False,
    ) -> AtlasWorkerPoolStatus:
        """Idempotently reconcile AtlasWorkerPool and manage underlying Deployment."""
        self._reconcile_count += 1
        pool_key = f"{pool.namespace}/{pool.name}"
        status = pool.status.model_copy()

        # Handle finalizer & drain if resource is being deleted
        if drain_requested:
            remaining_leases = self._active_worker_leases.get(pool_key, set())
            if remaining_leases:
                status.scaling_phase = ScalingPhase.STABLE
                status.conditions = [
                    ResourceCondition(
                        type="Draining",
                        status="True",
                        reason="WorkersDraining",
                        message=f"Waiting for {len(remaining_leases)} worker leases to drain before deletion",
                    )
                ]
                return status
            else:
                # Drained completely; safe to delete underlying deployment
                self._managed_deployments.pop(pool_key, None)
                status.current_replicas = 0
                status.ready_replicas = 0
                status.conditions = [
                    ResourceCondition(
                        type="Drained",
                        status="True",
                        reason="SafeToDelete",
                        message="All worker leases drained cleanly; finalizer may be removed",
                    )
                ]
                return status

        # Check replica bounds
        desired_replicas = max(
            pool.spec.min_replicas,
            min(pool.spec.max_replicas, status.current_replicas),
        )

        # Reconcile underlying deployment
        deployment_manifest = {
            "metadata": {
                "name": f"{pool.name}-deployment",
                "namespace": pool.namespace,
                "labels": {
                    "app.kubernetes.io/name": "atlas-worker",
                    "atlas.io/worker-pool": pool.name,
                },
                "annotations": {
                    "atlas.io/platform": pool.spec.capabilities.platform,
                    "atlas.io/gpu-required": str(pool.spec.capabilities.gpu_required),
                },
            },
            "spec": {
                "replicas": desired_replicas,
                "template": {
                    "image": pool.spec.image,
                    "resources": pool.spec.resources,
                },
            },
        }

        self._managed_deployments[pool_key] = deployment_manifest

        status.current_replicas = desired_replicas
        status.ready_replicas = desired_replicas
        status.active_tasks = active_tasks
        status.scaling_phase = ScalingPhase.STABLE
        status.conditions = [
            ResourceCondition(
                type="Ready",
                status="True",
                reason="WorkerPoolReconciled",
                message=f"Worker pool reconciled to {desired_replicas} replicas",
            )
        ]
        return status

    def detect_drift(self, pool: AtlasWorkerPool, live_deployment: dict[str, Any]) -> list[str]:
        """Detect drift between desired WorkerPool spec and actual live Deployment."""
        drifts = []
        live_replicas = live_deployment.get("spec", {}).get("replicas")
        live_image = live_deployment.get("spec", {}).get("template", {}).get("image", "")

        if live_replicas is not None and live_replicas < pool.spec.min_replicas:
            drifts.append(
                f"Replicas drifted below minimum: live={live_replicas}, min={pool.spec.min_replicas}"
            )
        elif live_replicas is not None and live_replicas > pool.spec.max_replicas:
            drifts.append(
                f"Replicas drifted above maximum: live={live_replicas}, max={pool.spec.max_replicas}"
            )

        if live_image and live_image != pool.spec.image:
            drifts.append(f"Container image drifted: live={live_image}, desired={pool.spec.image}")

        return drifts

    def register_worker_lease(self, pool_key: str, lease_id: str) -> None:
        """Register active worker lease in pool."""
        if pool_key not in self._active_worker_leases:
            self._active_worker_leases[pool_key] = set()
        self._active_worker_leases[pool_key].add(lease_id)

    def release_worker_lease(self, pool_key: str, lease_id: str) -> None:
        """Release worker lease upon task completion."""
        if pool_key in self._active_worker_leases:
            self._active_worker_leases[pool_key].discard(lease_id)

    # --- 3. AtlasAgentPool Reconciliation ---

    def reconcile_agent_pool(self, pool: AtlasAgentPool) -> AtlasAgentPoolStatus:
        """Reconcile AtlasAgentPool custom resource."""
        self._reconcile_count += 1
        status = pool.status.model_copy()
        status.ready_replicas = pool.spec.replicas
        status.observed_generation += 1
        status.conditions = [
            ResourceCondition(
                type="Ready",
                status="True",
                reason="AgentsReady",
                message=f"Agent pool active with {pool.spec.replicas} replicas across types {pool.spec.agent_types}",
            )
        ]
        return status

    # --- 4. AtlasExecutionPolicy Reconciliation ---

    def reconcile_execution_policy(
        self, policy: AtlasExecutionPolicy
    ) -> AtlasExecutionPolicyStatus:
        """Reconcile AtlasExecutionPolicy into Kubernetes NetworkPolicy."""
        self._reconcile_count += 1
        policy_key = f"{policy.namespace}/{policy.name}"
        status = policy.status.model_copy()

        # Build Kubernetes NetworkPolicy spec
        egress_rules = []
        if policy.spec.allow_network_egress:
            for _domain in policy.spec.egress_allowlist:
                egress_rules.append({"to": [{"ipBlock": {"cidr": "0.0.0.0/0"}}], "ports": []})

        netpol_manifest = {
            "metadata": {
                "name": f"atlas-netpol-{policy.name}",
                "namespace": policy.namespace,
                "labels": {
                    "atlas.io/tenant": policy.spec.tenant_id,
                },
            },
            "spec": {
                "podSelector": {"matchLabels": {"atlas.io/tenant": policy.spec.tenant_id}},
                "policyTypes": ["Egress"],
                "egress": egress_rules,
            },
        }

        self._managed_network_policies[policy_key] = netpol_manifest
        status.enforced = True
        status.active_violations = 0
        status.conditions = [
            ResourceCondition(
                type="Enforced",
                status="True",
                reason="NetworkPolicyReconciled",
                message=f"Enforced egress policy for tenant {policy.spec.tenant_id}",
            )
        ]
        return status

    # --- 5. AtlasDeployment Reconciliation, Upgrade & Rollback ---

    def reconcile_deployment(
        self, deployment: AtlasDeployment, simulated_healthy: bool = True
    ) -> AtlasDeploymentStatus:
        """Reconcile AtlasDeployment with rolling upgrade and rollback support."""
        self._reconcile_count += 1
        dep_key = f"{deployment.namespace}/{deployment.name}"
        status = deployment.status.model_copy()

        # Initialize history
        if dep_key not in self._revision_history:
            self._revision_history[dep_key] = []

        history = self._revision_history[dep_key]

        # Check if version upgrade is underway
        if status.current_version and status.current_version != deployment.spec.version:
            if not simulated_healthy:
                # Rolling upgrade failed -> Rollback
                prev_version = history[-1]["version"] if history else status.current_version
                status.phase = DeploymentPhase.ROLLING_BACK
                status.ready = True
                status.current_version = prev_version
                status.conditions = [
                    ResourceCondition(
                        type="Rollback",
                        status="True",
                        reason="UpgradeFailed",
                        message=f"Healthcheck failed for {deployment.spec.version}; safely rolled back to {prev_version}",
                    )
                ]
                return status
            else:
                # Upgrade succeeded
                status.phase = DeploymentPhase.RUNNING
                status.ready = True
                status.current_version = deployment.spec.version
                history.append(
                    {
                        "version": deployment.spec.version,
                        "time": datetime.now(UTC).isoformat(),
                    }
                )
                status.conditions = [
                    ResourceCondition(
                        type="Ready",
                        status="True",
                        reason="UpgradeSucceeded",
                        message=f"Successfully rolled forward to {deployment.spec.version}",
                    )
                ]
                return status

        # Initial deployment
        if not status.current_version:
            status.current_version = deployment.spec.version
            history.append(
                {
                    "version": deployment.spec.version,
                    "time": datetime.now(UTC).isoformat(),
                }
            )

        status.phase = DeploymentPhase.RUNNING if simulated_healthy else DeploymentPhase.FAILED
        status.ready = simulated_healthy
        status.conditions = [
            ResourceCondition(
                type="Ready",
                status="True" if simulated_healthy else "False",
                reason="DeploymentReconciled",
                message=f"Deployment is {status.phase.value}",
            )
        ]
        return status
