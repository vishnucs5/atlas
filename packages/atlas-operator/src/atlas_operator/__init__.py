"""ATLAS Kubernetes Operator and Cloud-Native Infrastructure Controller."""

from __future__ import annotations

from atlas_operator.admission import AdmissionResult, AtlasAdmissionValidator
from atlas_operator.autoscaler import (
    ScalingAction,
    ScalingDecision,
    WorkloadAwareAutoscaler,
    WorkloadMetrics,
)
from atlas_operator.metrics import AtlasInfrastructureMetrics
from atlas_operator.models import (
    AtlasAgentPool,
    AtlasAgentPoolSpec,
    AtlasAgentPoolStatus,
    AtlasCluster,
    AtlasClusterCapabilities,
    AtlasClusterSpec,
    AtlasClusterStatus,
    AtlasDeployment,
    AtlasDeploymentSpec,
    AtlasDeploymentStatus,
    AtlasExecutionPolicy,
    AtlasExecutionPolicySpec,
    AtlasExecutionPolicyStatus,
    AtlasWorkerPool,
    AtlasWorkerPoolSpec,
    AtlasWorkerPoolStatus,
    ClusterPhase,
    DeploymentPhase,
    ResourceCondition,
    ScalingPhase,
)
from atlas_operator.reconciler import AtlasOperatorController

__version__ = "0.12.0"

__all__ = [
    "AdmissionResult",
    "AtlasAdmissionValidator",
    "AtlasAgentPool",
    "AtlasAgentPoolSpec",
    "AtlasAgentPoolStatus",
    "AtlasCluster",
    "AtlasClusterCapabilities",
    "AtlasClusterSpec",
    "AtlasClusterStatus",
    "AtlasDeployment",
    "AtlasDeploymentSpec",
    "AtlasDeploymentStatus",
    "AtlasExecutionPolicy",
    "AtlasExecutionPolicySpec",
    "AtlasExecutionPolicyStatus",
    "AtlasInfrastructureMetrics",
    "AtlasOperatorController",
    "AtlasWorkerPool",
    "AtlasWorkerPoolSpec",
    "AtlasWorkerPoolStatus",
    "ClusterPhase",
    "DeploymentPhase",
    "ResourceCondition",
    "ScalingAction",
    "ScalingDecision",
    "ScalingPhase",
    "WorkloadAwareAutoscaler",
    "WorkloadMetrics",
]
