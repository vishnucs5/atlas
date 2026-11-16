"""Kubernetes Custom Resource Definition (CRD) domain models for ATLAS."""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ClusterPhase(enum.StrEnum):
    HEALTHY = "Healthy"
    DEGRADED = "Degraded"
    DISCONNECTED = "Disconnected"
    REVOKED = "Revoked"


class ScalingPhase(enum.StrEnum):
    STABLE = "Stable"
    SCALING_UP = "ScalingUp"
    SCALING_DOWN = "ScalingDown"
    COOLDOWN = "Cooldown"


class DeploymentPhase(enum.StrEnum):
    PENDING = "Pending"
    DEPLOYING = "Deploying"
    RUNNING = "Running"
    FAILED = "Failed"
    UPGRADING = "Upgrading"
    ROLLING_BACK = "RollingBack"


class ResourceCondition(BaseModel):
    """Kubernetes standard status condition."""

    type: str
    status: str = "True"  # "True", "False", "Unknown"
    last_transition_time: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    reason: str = "Reconciled"
    message: str = "Resource is up to date"


# --- AtlasCluster ---


class AtlasClusterCapabilities(BaseModel):
    platforms: list[str] = Field(default_factory=lambda: ["linux/amd64"])
    gpu_models: list[str] = Field(default_factory=list)
    max_concurrent_workers: int = Field(default=100, ge=1)
    supports_desktop_session: bool = False


class AtlasClusterSpec(BaseModel):
    cluster_id: str
    region: str
    provider: str = "generic-k8s"
    api_endpoint: str
    credentials_secret_ref: dict[str, str] = Field(default_factory=dict)
    capabilities: AtlasClusterCapabilities = Field(default_factory=AtlasClusterCapabilities)
    tenant_allowed_list: list[str] = Field(default_factory=list)

    @field_validator("cluster_id")
    @classmethod
    def validate_cluster_id(cls, v: str) -> str:
        if not v.startswith("cls_"):
            raise ValueError(f"Cluster ID must start with 'cls_', got: {v}")
        return v


class AtlasClusterStatus(BaseModel):
    phase: ClusterPhase = ClusterPhase.HEALTHY
    registered_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_heartbeat: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    active_workers: int = 0
    latency_ms: float = 0.0
    conditions: list[ResourceCondition] = Field(default_factory=list)


class AtlasCluster(BaseModel):
    api_version: str = "atlas.io/v1alpha1"
    kind: str = "AtlasCluster"
    name: str
    spec: AtlasClusterSpec
    status: AtlasClusterStatus = Field(default_factory=AtlasClusterStatus)


# --- AtlasWorkerPool ---


class WorkerCapabilitiesSpec(BaseModel):
    platform: str = "linux/amd64"
    gpu_required: bool = False
    min_vram_gb: int = 0
    supported_runtimes: list[str] = Field(default_factory=list)


class AtlasWorkerPoolSpec(BaseModel):
    cluster_ref: str = "default"
    min_replicas: int = Field(default=1, ge=0)
    max_replicas: int = Field(default=10, ge=1)
    target_queue_depth_per_worker: int = Field(default=4, ge=1)
    cooldown_period_seconds: int = Field(default=60, ge=10)
    capabilities: WorkerCapabilitiesSpec = Field(default_factory=WorkerCapabilitiesSpec)
    image: str = "atlas/worker:0.12.0"
    resources: dict[str, Any] = Field(default_factory=dict)

    @field_validator("max_replicas")
    @classmethod
    def validate_replica_bounds(cls, v: int, info: Any) -> int:
        min_rep = info.data.get("min_replicas", 0)
        if v < min_rep:
            raise ValueError(
                f"max_replicas ({v}) must be greater than or equal to min_replicas ({min_rep})"
            )
        return v


class AtlasWorkerPoolStatus(BaseModel):
    current_replicas: int = 1
    ready_replicas: int = 1
    active_tasks: int = 0
    scaling_phase: ScalingPhase = ScalingPhase.STABLE
    last_scale_time: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    conditions: list[ResourceCondition] = Field(default_factory=list)


class AtlasWorkerPool(BaseModel):
    api_version: str = "atlas.io/v1alpha1"
    kind: str = "AtlasWorkerPool"
    name: str
    namespace: str = "default"
    spec: AtlasWorkerPoolSpec
    status: AtlasWorkerPoolStatus = Field(default_factory=AtlasWorkerPoolStatus)


# --- AtlasAgentPool ---


class AtlasAgentPoolSpec(BaseModel):
    replicas: int = Field(default=1, ge=1)
    agent_types: list[str] = Field(default_factory=list)
    model_router_ref: str = "default-router"

    @field_validator("agent_types")
    @classmethod
    def validate_agent_types(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("agent_types must not be empty")
        return v


class AtlasAgentPoolStatus(BaseModel):
    ready_replicas: int = 0
    observed_generation: int = 1
    conditions: list[ResourceCondition] = Field(default_factory=list)


class AtlasAgentPool(BaseModel):
    api_version: str = "atlas.io/v1alpha1"
    kind: str = "AtlasAgentPool"
    name: str
    namespace: str = "default"
    spec: AtlasAgentPoolSpec
    status: AtlasAgentPoolStatus = Field(default_factory=AtlasAgentPoolStatus)


# --- AtlasExecutionPolicy ---


class AtlasExecutionPolicySpec(BaseModel):
    tenant_id: str
    allow_network_egress: bool = False
    egress_allowlist: list[str] = Field(default_factory=list)
    require_gpu_encryption: bool = True
    max_execution_duration_seconds: int = Field(default=1800, ge=60)


class AtlasExecutionPolicyStatus(BaseModel):
    enforced: bool = True
    active_violations: int = 0
    conditions: list[ResourceCondition] = Field(default_factory=list)


class AtlasExecutionPolicy(BaseModel):
    api_version: str = "atlas.io/v1alpha1"
    kind: str = "AtlasExecutionPolicy"
    name: str
    namespace: str = "default"
    spec: AtlasExecutionPolicySpec
    status: AtlasExecutionPolicyStatus = Field(default_factory=AtlasExecutionPolicyStatus)


# --- AtlasDeployment ---


class AtlasDeploymentSpec(BaseModel):
    version: str
    api_replicas: int = Field(default=2, ge=1)
    supervisor_replicas: int = Field(default=2, ge=1)
    storage_type: str = "postgresql"
    postgresql_connection_secret_ref: str = "postgres-credentials"


class AtlasDeploymentStatus(BaseModel):
    phase: DeploymentPhase = DeploymentPhase.PENDING
    ready: bool = False
    current_version: str = ""
    conditions: list[ResourceCondition] = Field(default_factory=list)


class AtlasDeployment(BaseModel):
    api_version: str = "atlas.io/v1alpha1"
    kind: str = "AtlasDeployment"
    name: str
    namespace: str = "default"
    spec: AtlasDeploymentSpec
    status: AtlasDeploymentStatus = Field(default_factory=AtlasDeploymentStatus)
