"""ATLAS Distributed - Distributed Execution Network, Worker Agent & Scheduling Fabric."""

from __future__ import annotations

from atlas_distributed.disaster_recovery import (
    DisasterRecoveryCoordinator,
    FaultType,
    TaskRecoveryState,
)
from atlas_distributed.edge_gateway import (
    EdgeEnrollmentToken,
    EdgeExecutionGateway,
    EdgeExecutionResult,
    EdgeHardwareMetrics,
    EdgeLocalBuffer,
    EdgeNodeStatus,
    EdgeTaskAssignment,
)
from atlas_distributed.gpu import (
    GPUCapabilityManager,
    GPUDevice,
    GPUVendor,
    GPUWorkloadRequirement,
    WorkerGPUInventory,
)
from atlas_distributed.multi_cluster import (
    ClusterCapabilities,
    ClusterNodeRecord,
    ClusterStatus,
    ClusterTaskRequirements,
    MultiClusterManager,
)

__version__ = "0.12.0"

__all__ = [
    "ClusterCapabilities",
    "ClusterNodeRecord",
    "ClusterStatus",
    "ClusterTaskRequirements",
    "DisasterRecoveryCoordinator",
    "EdgeEnrollmentToken",
    "EdgeExecutionGateway",
    "EdgeExecutionResult",
    "EdgeHardwareMetrics",
    "EdgeLocalBuffer",
    "EdgeNodeStatus",
    "EdgeTaskAssignment",
    "FaultType",
    "GPUCapabilityManager",
    "GPUDevice",
    "GPUVendor",
    "GPUWorkloadRequirement",
    "MultiClusterManager",
    "TaskRecoveryState",
    "WorkerGPUInventory",
]
