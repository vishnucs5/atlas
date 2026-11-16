"""GPU Capability Discovery, Inventory and Workload Placement for ATLAS."""

from __future__ import annotations

import enum
import logging

from pydantic import BaseModel, Field

logger = logging.getLogger("atlas.distributed.gpu")


class GPUVendor(enum.StrEnum):
    NVIDIA = "NVIDIA"
    AMD = "AMD"
    APPLE = "APPLE"
    INTEL = "INTEL"


class GPUDevice(BaseModel):
    """Specification of an individual physical or virtual GPU."""

    index: int = 0
    vendor: GPUVendor = GPUVendor.NVIDIA
    model: str  # e.g., "A100-SXM4-80GB", "H100-PCIe-80GB", "RTX-4090"
    vram_total_mb: int = 81920
    vram_available_mb: int = 81920
    driver_version: str = "550.54.14"
    compute_capability: float = 8.0  # e.g., 8.0 for Ampere, 9.0 for Hopper
    supported_runtimes: list[str] = Field(
        default_factory=lambda: ["cuda-12.4", "vllm", "tensorrt-llm"]
    )
    supported_models: list[str] = Field(
        default_factory=lambda: ["llama-3", "mistral", "qwen-2.5", "deepseek"]
    )


class WorkerGPUInventory(BaseModel):
    """GPU configuration of an enrolled execution worker."""

    worker_id: str
    devices: list[GPUDevice] = Field(default_factory=list)
    has_gpu: bool = True

    @property
    def total_vram_gb(self) -> float:
        return sum(d.vram_total_mb for d in self.devices) / 1024.0

    @property
    def available_vram_gb(self) -> float:
        return sum(d.vram_available_mb for d in self.devices) / 1024.0


class GPUWorkloadRequirement(BaseModel):
    """GPU constraints required by an autonomous agent task."""

    task_id: str
    min_vram_gb: float = 0.0
    required_vendor: GPUVendor | None = None
    required_runtime: str | None = None
    min_compute_capability: float | None = None
    min_gpu_count: int = 1


class GPUCapabilityManager:
    """Discovers, tracks, and schedules GPU-accelerated autonomous workloads."""

    def __init__(self) -> None:
        self._inventories: dict[str, WorkerGPUInventory] = {}

    def register_worker_gpus(self, worker_id: str, devices: list[GPUDevice]) -> WorkerGPUInventory:
        """Register or update GPU devices for a worker."""
        inventory = WorkerGPUInventory(
            worker_id=worker_id,
            devices=devices,
            has_gpu=len(devices) > 0,
        )
        self._inventories[worker_id] = inventory
        logger.info(
            f"Worker '{worker_id}' registered {len(devices)} GPUs (total {inventory.total_vram_gb:.1f} GB VRAM)"
        )
        return inventory

    def get_inventory(self, worker_id: str) -> WorkerGPUInventory | None:
        return self._inventories.get(worker_id)

    def allocate_vram(self, worker_id: str, device_index: int, vram_mb: int) -> bool:
        """Reserve VRAM on a specific worker GPU."""
        inventory = self._inventories.get(worker_id)
        if not inventory or device_index >= len(inventory.devices):
            return False

        device = inventory.devices[device_index]
        if device.vram_available_mb < vram_mb:
            return False

        device.vram_available_mb -= vram_mb
        return True

    def release_vram(self, worker_id: str, device_index: int, vram_mb: int) -> bool:
        """Free previously allocated VRAM on a worker GPU."""
        inventory = self._inventories.get(worker_id)
        if not inventory or device_index >= len(inventory.devices):
            return False

        device = inventory.devices[device_index]
        device.vram_available_mb = min(device.vram_total_mb, device.vram_available_mb + vram_mb)
        return True

    def find_compatible_worker(self, req: GPUWorkloadRequirement) -> str | None:
        """Find best worker capable of hosting the requested GPU workload."""
        candidates: list[tuple[float, str]] = []

        for wid, inv in self._inventories.items():
            if not inv.has_gpu or len(inv.devices) < req.min_gpu_count:
                continue

            # Check if sufficient matching devices exist on this worker
            matching_devices = 0
            worker_available_vram = 0

            for dev in inv.devices:
                # 1. Vendor match
                if req.required_vendor and dev.vendor != req.required_vendor:
                    continue

                # 2. VRAM match
                if (dev.vram_available_mb / 1024.0) < req.min_vram_gb:
                    continue

                # 3. Runtime match
                if req.required_runtime and req.required_runtime not in dev.supported_runtimes:
                    continue

                # 4. Compute capability match
                if (
                    req.min_compute_capability
                    and dev.compute_capability < req.min_compute_capability
                ):
                    continue

                matching_devices += 1
                worker_available_vram += dev.vram_available_mb

            if matching_devices >= req.min_gpu_count:
                # Rank candidates by most available VRAM (headroom optimization)
                candidates.append((-worker_available_vram, wid))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
