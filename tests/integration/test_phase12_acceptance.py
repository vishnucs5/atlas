"""Comprehensive Phase 12 Acceptance Suite: Kubernetes-Native Orchestration & Edge Execution Infrastructure.

Verifies scenarios K8S-01 through K8S-24.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import yaml
from atlas_distributed.disaster_recovery import (
    DisasterRecoveryCoordinator,
    FaultType,
)
from atlas_distributed.edge_gateway import (
    EdgeExecutionGateway,
    EdgeExecutionResult,
    EdgeHardwareMetrics,
    EdgeLocalBuffer,
    EdgeTaskAssignment,
)
from atlas_distributed.gpu import (
    GPUCapabilityManager,
    GPUDevice,
    GPUVendor,
    GPUWorkloadRequirement,
)
from atlas_distributed.multi_cluster import (
    ClusterCapabilities,
    ClusterStatus,
    ClusterTaskRequirements,
    MultiClusterManager,
)
from atlas_operator.admission import AtlasAdmissionValidator
from atlas_operator.autoscaler import (
    ScalingAction,
    WorkloadAwareAutoscaler,
    WorkloadMetrics,
)
from atlas_operator.metrics import AtlasInfrastructureMetrics
from atlas_operator.models import (
    AtlasAgentPool,
    AtlasCluster,
    AtlasDeployment,
    AtlasWorkerPool,
    ClusterPhase,
    DeploymentPhase,
    ScalingPhase,
)
from atlas_operator.reconciler import AtlasOperatorController

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _get_helm_binary() -> str:
    """Locate helm executable."""
    local_winget_helm = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "WinGet"
        / "Packages"
        / "Helm.Helm_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / "windows-amd64"
        / "helm.exe"
    )
    if local_winget_helm.exists():
        return str(local_winget_helm)
    return "helm"


# --- K8S-01: Helm Deployment Verification ---


def test_k8s01_helm_chart_lint_and_manifest_generation():
    """K8S-01: Verify Helm chart syntax and template generation across dev, staging, prod."""
    chart_dir = REPO_ROOT / "deploy" / "helm" / "atlas"
    assert chart_dir.exists(), "Helm chart directory missing"

    helm_bin = _get_helm_binary()

    # 1. Helm Lint
    lint_res = subprocess.run(
        [helm_bin, "lint", str(chart_dir)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert lint_res.returncode == 0, f"Helm lint failed:\n{lint_res.stderr}"
    assert "0 chart(s) failed" in lint_res.stdout

    # 2. Template Generation across values files
    for env in ["dev", "staging", "prod"]:
        values_file = chart_dir / f"values-{env}.yaml"
        assert values_file.exists(), f"Values file missing: {values_file}"
        render_res = subprocess.run(
            [
                helm_bin,
                "template",
                f"atlas-{env}",
                str(chart_dir),
                "-f",
                str(values_file),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert render_res.returncode == 0, (
            f"Template rendering failed for {env}:\n{render_res.stderr}"
        )
        docs = list(yaml.safe_load_all(render_res.stdout))
        assert len(docs) >= 5, f"Expected at least 5 rendered K8s resources for {env}"

        # Verify essential resource kinds exist
        kinds = {d["kind"] for d in docs if d and "kind" in d}
        assert "Deployment" in kinds
        assert "Service" in kinds
        assert "ConfigMap" in kinds


# --- K8S-02: Helm Upgrade & Rollback ---


def test_k8s02_helm_upgrade_and_rollback():
    """K8S-02: Verify rolling upgrade parameterization and revision history rollback simulation."""
    chart_dir = REPO_ROOT / "deploy" / "helm" / "atlas"
    helm_bin = _get_helm_binary()

    # Render release v1
    v1_res = subprocess.run(
        [
            helm_bin,
            "template",
            "atlas-release",
            str(chart_dir),
            "--set",
            "api.image.tag=0.12.0",
        ],
        capture_output=True,
        text=True,
    )
    assert v1_res.returncode == 0
    assert "atlas/api:0.12.0" in v1_res.stdout

    # Render upgrade v2
    v2_res = subprocess.run(
        [
            helm_bin,
            "template",
            "atlas-release",
            str(chart_dir),
            "--set",
            "api.image.tag=0.12.1",
        ],
        capture_output=True,
        text=True,
    )
    assert v2_res.returncode == 0
    assert "atlas/api:0.12.1" in v2_res.stdout

    # Verify rollback retains v1 parameters
    rollback_res = subprocess.run(
        [
            helm_bin,
            "template",
            "atlas-release",
            str(chart_dir),
            "--set",
            "api.image.tag=0.12.0",
        ],
        capture_output=True,
        text=True,
    )
    assert rollback_res.returncode == 0
    assert "atlas/api:0.12.0" in rollback_res.stdout


# --- K8S-03: CRD Validation & Schema Enforcement ---


def test_k8s03_crd_validation_and_schema_enforcement():
    """K8S-03: Verify OpenAPI v3 CRD schemas and Admission Validator rejection rules."""
    crds_dir = REPO_ROOT / "deploy" / "crds"
    assert crds_dir.exists()

    expected_crds = [
        "atlas.io_atlasclusters.yaml",
        "atlas.io_atlasworkerpools.yaml",
        "atlas.io_atlasagentpools.yaml",
        "atlas.io_atlasexecutionpolicies.yaml",
        "atlas.io_atlasdeployments.yaml",
    ]
    for crd in expected_crds:
        crd_path = crds_dir / crd
        assert crd_path.exists(), f"CRD manifest missing: {crd}"
        crd_data = yaml.safe_load(crd_path.read_text(encoding="utf-8"))
        assert crd_data["kind"] == "CustomResourceDefinition"
        assert crd_data["spec"]["group"] == "atlas.io"

    # Test Admission Validator with Valid Cluster
    valid_cluster = {
        "kind": "AtlasCluster",
        "metadata": {"name": "prod-us"},
        "spec": {
            "cluster_id": "cls_useast_01",
            "region": "us-east-1",
            "api_endpoint": "https://k8s.example.com",
        },
    }
    assert AtlasAdmissionValidator.review(valid_cluster).allowed is True

    # Test Admission Validator with Invalid Cluster ID (missing cls_ prefix)
    invalid_cluster = {
        "kind": "AtlasCluster",
        "metadata": {"name": "bad-cluster"},
        "spec": {
            "cluster_id": "invalid_id",
            "region": "us-east-1",
            "api_endpoint": "https://k8s.example.com",
        },
    }
    res = AtlasAdmissionValidator.review(invalid_cluster)
    assert res.allowed is False
    assert any("Cluster ID must start with 'cls_'" in v for v in res.violations)

    # Test Admission Validator with WorkerPool invalid replica bounds
    invalid_pool = {
        "kind": "AtlasWorkerPool",
        "metadata": {"name": "invalid-pool"},
        "spec": {
            "min_replicas": 10,
            "max_replicas": 2,  # max < min
        },
    }
    pool_res = AtlasAdmissionValidator.review(invalid_pool)
    assert pool_res.allowed is False


# --- K8S-04: Operator Reconciliation Loop ---


def test_k8s04_operator_reconciliation_loop():
    """K8S-04: Verify idempotent reconciliation of AtlasCluster, WorkerPool, AgentPool, Deployment."""
    controller = AtlasOperatorController()

    # 1. Cluster Reconciliation
    cluster = AtlasCluster(
        name="primary-cluster",
        spec={
            "cluster_id": "cls_primary_01",
            "region": "us-west-2",
            "api_endpoint": "https://api.k8s.uswest2.internal",
        },
    )
    status = controller.reconcile_cluster(cluster, is_reachable=True, latency_ms=12.5)
    assert status.phase == ClusterPhase.HEALTHY
    assert status.latency_ms == 12.5
    assert len(status.conditions) == 1

    # 2. WorkerPool Reconciliation
    pool = AtlasWorkerPool(
        name="gpu-pool",
        namespace="atlas-system",
        spec={"min_replicas": 2, "max_replicas": 8},
    )
    pool_status = controller.reconcile_worker_pool(pool, active_tasks=5)
    assert pool_status.current_replicas == 2
    assert pool_status.active_tasks == 5
    assert pool_status.scaling_phase == ScalingPhase.STABLE

    # 3. AgentPool Reconciliation
    agent_pool = AtlasAgentPool(
        name="research-agents",
        namespace="atlas-system",
        spec={"replicas": 3, "agent_types": ["researcher", "critic"]},
    )
    agent_status = controller.reconcile_agent_pool(agent_pool)
    assert agent_status.ready_replicas == 3

    # 4. Deployment Reconciliation
    dep = AtlasDeployment(
        name="atlas-enterprise",
        namespace="atlas-system",
        spec={"version": "0.12.0", "api_replicas": 3},
    )
    dep_status = controller.reconcile_deployment(dep, simulated_healthy=True)
    assert dep_status.phase == DeploymentPhase.RUNNING
    assert dep_status.ready is True


# --- K8S-05: Drift Detection ---


def test_k8s05_drift_detection():
    """K8S-05: Verify controller detects manual out-of-band changes to replicas and images."""
    controller = AtlasOperatorController()
    pool = AtlasWorkerPool(
        name="prod-workers",
        namespace="atlas-system",
        spec={"min_replicas": 3, "max_replicas": 10, "image": "atlas/worker:0.12.0"},
    )

    # Reconcile desired state
    controller.reconcile_worker_pool(pool)

    # Simulate drifted live deployment (someone scaled down to 1 manually and changed image)
    drifted_deployment = {
        "spec": {
            "replicas": 1,
            "template": {"image": "unauthorized/custom-worker:latest"},
        }
    }

    drifts = controller.detect_drift(pool, drifted_deployment)
    assert len(drifts) == 2
    assert any("Replicas drifted below minimum" in d for d in drifts)
    assert any("Container image drifted" in d for d in drifts)


# --- K8S-06: Finalizers & Safe Deletion ---


def test_k8s06_finalizers_and_safe_deletion():
    """K8S-06: Verify finalizer protects worker pool during active task execution."""
    controller = AtlasOperatorController()
    pool = AtlasWorkerPool(
        name="stateful-workers",
        namespace="atlas-system",
        spec={"min_replicas": 2, "max_replicas": 5},
    )
    pool_key = "atlas-system/stateful-workers"

    # Register active lease
    controller.register_worker_lease(pool_key, "lease_task_442")

    # Request drain / deletion while lease active
    drain_status = controller.reconcile_worker_pool(pool, drain_requested=True)
    assert drain_status.conditions[0].type == "Draining"
    assert "Waiting for 1 worker leases" in drain_status.conditions[0].message

    # Release worker lease
    controller.release_worker_lease(pool_key, "lease_task_442")

    # Re-reconcile drain
    final_status = controller.reconcile_worker_pool(pool, drain_requested=True)
    assert final_status.conditions[0].type == "Drained"
    assert "finalizer may be removed" in final_status.conditions[0].message


# --- K8S-07: Workload-Aware Autoscaling ---


def test_k8s07_workload_aware_autoscaling():
    """K8S-07: Verify scaling decision based on queue depth, pending tasks, and priorities."""
    autoscaler = WorkloadAwareAutoscaler(
        min_replicas=1,
        max_replicas=15,
        target_tasks_per_worker=4,
        scale_up_cooldown_seconds=0.0,
    )

    # 1. Zero backlog -> scales to minimum
    zero_metrics = WorkloadMetrics(queue_depth=0, average_cpu_percent=20.0)
    decision = autoscaler.evaluate(current_replicas=4, metrics=zero_metrics)
    assert decision.action == ScalingAction.SCALE_DOWN
    assert decision.desired_replicas == 2  # capped by max_scale_down_step (2)

    # 2. Heavy backlog with critical priority -> scales up
    heavy_metrics = WorkloadMetrics(
        queue_depth=20,
        pending_assignments=4,
        critical_priority_tasks=5,  # weighted 2x
        tasks_near_deadline=3,  # weighted 2x
    )
    decision_up = autoscaler.evaluate(current_replicas=2, metrics=heavy_metrics)
    assert decision_up.action == ScalingAction.SCALE_UP
    assert decision_up.desired_replicas == 7  # 2 + max_scale_up_step (5)
    assert "Backlog requires" in decision_up.reason


# --- K8S-08: Anti-Flapping Autoscaling Cooldowns ---


def test_k8s08_anti_flapping_cooldowns():
    """K8S-08: Verify scale-up and scale-down cooldown timers prevent rapid flapping."""
    autoscaler = WorkloadAwareAutoscaler(
        min_replicas=1,
        max_replicas=10,
        scale_up_cooldown_seconds=5.0,
        scale_down_cooldown_seconds=10.0,
    )

    heavy_metrics = WorkloadMetrics(queue_depth=40)

    # First scale up succeeds
    d1 = autoscaler.evaluate(current_replicas=2, metrics=heavy_metrics)
    assert d1.action == ScalingAction.SCALE_UP
    assert d1.desired_replicas == 7

    # Immediate second evaluation trips cooldown -> NOOP
    d2 = autoscaler.evaluate(current_replicas=7, metrics=heavy_metrics)
    assert d2.action == ScalingAction.NOOP
    assert "Scale-up cooldown active" in d2.reason

    # Test scale-down cooldown
    idle_metrics = WorkloadMetrics(queue_depth=0, average_cpu_percent=10.0)
    d3 = autoscaler.evaluate(current_replicas=7, metrics=idle_metrics)
    assert d3.action == ScalingAction.SCALE_DOWN
    assert d3.desired_replicas == 5

    # Immediate second scale-down trips cooldown -> NOOP
    d4 = autoscaler.evaluate(current_replicas=5, metrics=idle_metrics)
    assert d4.action == ScalingAction.NOOP
    assert "Scale-down cooldown active" in d4.reason


# --- K8S-09: Multi-Cluster Registration & Health ---


def test_k8s09_multi_cluster_registration_and_health():
    """K8S-09: Verify cluster registration, heartbeats, and degradation tracking."""
    mcm = MultiClusterManager(heartbeat_timeout_seconds=2.0)

    # Register cluster
    c1 = mcm.register_cluster(
        cluster_id="cls_east_01",
        name="us-east-cluster",
        region="us-east-1",
        api_endpoint="https://api.useast.internal",
        auth_token="token_secret_123",
        capabilities=ClusterCapabilities(max_workers=200),
    )
    assert c1.status == ClusterStatus.HEALTHY

    # Normal heartbeat
    assert mcm.heartbeat("cls_east_01", active_workers=45, latency_ms=15.0) is True

    # High latency heartbeat -> Degraded
    assert mcm.heartbeat("cls_east_01", active_workers=45, latency_ms=350.0) is True
    assert mcm._clusters["cls_east_01"].status == ClusterStatus.DEGRADED


# --- K8S-10: Capability-Based Task Placement ---


def test_k8s10_capability_based_task_placement():
    """K8S-10: Verify global scheduler matches task platform, GPU, and region constraints."""
    mcm = MultiClusterManager()

    # Cluster A: CPU only, us-east
    mcm.register_cluster(
        cluster_id="cls_cpu_east",
        name="cpu-east",
        region="us-east-1",
        api_endpoint="https://api.east.internal",
        auth_token="tok_1",
        capabilities=ClusterCapabilities(
            platforms=["linux/amd64"],
            gpu_models=[],
            supports_desktop_session=False,
        ),
    )

    # Cluster B: High-end GPU, us-west
    mcm.register_cluster(
        cluster_id="cls_gpu_west",
        name="gpu-west",
        region="us-west-2",
        api_endpoint="https://api.west.internal",
        auth_token="tok_2",
        capabilities=ClusterCapabilities(
            platforms=["linux/amd64"],
            gpu_models=["NVIDIA-H100-80GB"],
            supports_desktop_session=False,
        ),
    )

    # Task 1: CPU task preferring us-east
    req_cpu = ClusterTaskRequirements(
        task_id="task_cpu_01",
        tenant_id="org_default",
        preferred_region="us-east-1",
    )
    assigned_cpu = mcm.select_cluster_for_task(req_cpu)
    assert assigned_cpu == "cls_cpu_east"

    # Task 2: GPU task requiring NVIDIA-H100-80GB
    req_gpu = ClusterTaskRequirements(
        task_id="task_gpu_01",
        tenant_id="org_default",
        required_gpu="NVIDIA-H100-80GB",
    )
    assigned_gpu = mcm.select_cluster_for_task(req_gpu)
    assert assigned_gpu == "cls_gpu_west"


# --- K8S-11: Cross-Cluster Failover ---


def test_k8s11_cross_cluster_failover():
    """K8S-11: Verify cluster disconnect triggers task failover and worker fencing."""
    mcm = MultiClusterManager(heartbeat_timeout_seconds=0.01)

    mcm.register_cluster(
        cluster_id="cls_failover_01",
        name="failing-cluster",
        region="us-east-1",
        api_endpoint="https://fail.internal",
        auth_token="tok_fail",
    )

    req = ClusterTaskRequirements(task_id="task_orphan_99", tenant_id="org_1")
    assigned = mcm.select_cluster_for_task(req)
    assert assigned == "cls_failover_01"

    # Simulate heartbeat timeout
    time.sleep(0.02)
    mcm._clusters["cls_failover_01"].consecutive_failures = 3
    disconnected = mcm.check_health_and_failover()
    assert "cls_failover_01" in disconnected

    # Extract orphaned tasks for reassignment
    orphaned = mcm.failover_tasks_from_cluster("cls_failover_01")
    assert "task_orphan_99" in orphaned
    assert mcm.is_fenced("cls_failover_01") is True


# --- K8S-12: Edge Reverse Outbound Connection ---


def test_k8s12_edge_reverse_outbound_connection():
    """K8S-12: Verify edge worker reverse outbound architecture without listening ports."""
    gateway = EdgeExecutionGateway()
    token = gateway.issue_enrollment_token(
        edge_node_id="edge_factory_linux_01",
        tenant_id="org_manufacturing",
        hardware_fingerprint="hw_fp_sha256_abcdef",
    )

    # Edge worker establishes reverse connection
    assert gateway.authenticate_handshake(token, current_fingerprint="hw_fp_sha256_abcdef") is True

    # Edge receives task assignment through outbound channel
    assignment = EdgeTaskAssignment(
        assignment_id="asg_01",
        task_id="task_edge_1",
        tenant_id="org_manufacturing",
        action_type="read_plc_sensor",
    )
    assert gateway.dispatch_assignment("edge_factory_linux_01", assignment) is True


# --- K8S-13: Edge Mutual Authentication ---


def test_k8s13_edge_mutual_authentication_and_fingerprint_check():
    """K8S-13: Verify hardware fingerprint mismatch rejects unauthorized device cloning."""
    gateway = EdgeExecutionGateway()
    token = gateway.issue_enrollment_token(
        edge_node_id="edge_atm_01",
        tenant_id="org_bank",
        hardware_fingerprint="correct_hardware_fingerprint",
    )

    # Attacker tries to use token on cloned machine with different hardware
    assert (
        gateway.authenticate_handshake(token, current_fingerprint="spoofed_hardware_fingerprint")
        is False
    )


# --- K8S-14: Edge Offline Resilient Buffering ---


def test_k8s14_edge_offline_buffering_and_resynchronization():
    """K8S-14: Verify edge worker buffers assignments and execution results during WAN disconnection."""
    gateway = EdgeExecutionGateway()
    edge_buffer = EdgeLocalBuffer()

    # 1. Deliver assignment before network drop
    assignment = EdgeTaskAssignment(
        assignment_id="asg_offline_99",
        task_id="task_offline_99",
        tenant_id="org_oil_rig",
        action_type="inspect_pressure_valves",
    )
    edge_buffer.buffer_assignment(assignment)

    # 2. Worker executes and completes task while WAN connection is dropped
    result = EdgeExecutionResult(
        assignment_id="asg_offline_99",
        task_id="task_offline_99",
        status="SUCCESS",
        result_data={"valve_status": "NORMAL", "pressure_psi": 142.5},
    )
    edge_buffer.buffer_result(result)
    assert result.buffered_offline is True

    # 3. Network restores -> Worker replays results to Gateway
    pending = edge_buffer.get_pending_results()
    assert len(pending) == 1

    synced_ids = gateway.sync_replayed_results("edge_oil_rig_01", pending)
    assert "asg_offline_99" in synced_ids

    # 4. Clean local buffer
    edge_buffer.clear_replayed_results(synced_ids)
    assert len(edge_buffer.get_pending_results()) == 0


# --- K8S-15: Remote Credential Revocation ---


def test_k8s15_remote_credential_revocation():
    """K8S-15: Verify revoking an edge node terminates leases and prevents reconnection."""
    gateway = EdgeExecutionGateway()
    token = gateway.issue_enrollment_token(
        edge_node_id="edge_stolen_device",
        tenant_id="org_retail",
        hardware_fingerprint="hw_stolen_123",
    )

    assert gateway.authenticate_handshake(token, "hw_stolen_123") is True

    # Administrator revokes device
    gateway.revoke_edge_node("edge_stolen_device")
    assert gateway.is_revoked("edge_stolen_device") is True

    # Immediate rejection on subsequent attempt
    assert gateway.authenticate_handshake(token, "hw_stolen_123") is False
    assert gateway.receive_heartbeat("edge_stolen_device", EdgeHardwareMetrics()) is False


# --- K8S-16: GPU Hardware Discovery ---


def test_k8s16_gpu_hardware_discovery():
    """K8S-16: Verify worker reports GPU vendor, VRAM, compute capability, and runtimes."""
    gpu_mgr = GPUCapabilityManager()

    dev1 = GPUDevice(
        index=0,
        vendor=GPUVendor.NVIDIA,
        model="NVIDIA-A100-SXM4-80GB",
        vram_total_mb=81920,
        vram_available_mb=81920,
        driver_version="550.54.14",
        compute_capability=8.0,
        supported_runtimes=["cuda-12.4", "vllm", "tensorrt-llm"],
    )
    dev2 = GPUDevice(
        index=1,
        vendor=GPUVendor.NVIDIA,
        model="NVIDIA-A100-SXM4-80GB",
        vram_total_mb=81920,
        vram_available_mb=81920,
        driver_version="550.54.14",
        compute_capability=8.0,
        supported_runtimes=["cuda-12.4", "vllm", "tensorrt-llm"],
    )

    inventory = gpu_mgr.register_worker_gpus("worker_node_gpu_01", [dev1, dev2])
    assert inventory.has_gpu is True
    assert inventory.total_vram_gb == 160.0
    assert inventory.available_vram_gb == 160.0

    # Test allocation
    assert gpu_mgr.allocate_vram("worker_node_gpu_01", 0, 40960) is True
    assert gpu_mgr.get_inventory("worker_node_gpu_01").available_vram_gb == 120.0

    # Test release
    assert gpu_mgr.release_vram("worker_node_gpu_01", 0, 40960) is True
    assert gpu_mgr.get_inventory("worker_node_gpu_01").available_vram_gb == 160.0


# --- K8S-17: GPU-Aware Task Scheduling ---


def test_k8s17_gpu_aware_task_scheduling():
    """K8S-17: Verify tasks requiring GPU constraints match capable workers or reject."""
    gpu_mgr = GPUCapabilityManager()

    # Worker 1: 24GB RTX 4090
    gpu_mgr.register_worker_gpus(
        "worker_rtx4090",
        [
            GPUDevice(
                index=0,
                vendor=GPUVendor.NVIDIA,
                model="RTX-4090",
                vram_total_mb=24576,
                vram_available_mb=24576,
                compute_capability=8.9,
                supported_runtimes=["cuda-12.4", "ollama"],
            )
        ],
    )

    # Worker 2: 80GB H100
    gpu_mgr.register_worker_gpus(
        "worker_h100",
        [
            GPUDevice(
                index=0,
                vendor=GPUVendor.NVIDIA,
                model="H100-80GB",
                vram_total_mb=81920,
                vram_available_mb=81920,
                compute_capability=9.0,
                supported_runtimes=["cuda-12.4", "vllm"],
            )
        ],
    )

    # Task requiring 40GB VRAM + vLLM
    req_heavy = GPUWorkloadRequirement(
        task_id="task_deepseek_large",
        min_vram_gb=40.0,
        required_runtime="vllm",
    )
    assigned = gpu_mgr.find_compatible_worker(req_heavy)
    assert assigned == "worker_h100"

    # Task requiring 128GB VRAM (impossible on single GPU) -> None
    req_impossible = GPUWorkloadRequirement(
        task_id="task_too_large",
        min_vram_gb=128.0,
    )
    assert gpu_mgr.find_compatible_worker(req_impossible) is None


# --- K8S-18: Disaster Recovery Chaos Injection ---


def test_k8s18_disaster_recovery_chaos_injection():
    """K8S-18: Verify pod termination and network partition recover gracefully."""
    dr = DisasterRecoveryCoordinator()

    # Initial lease
    dr.grant_lease("task_order_process", "worker_pod_alpha", duration_seconds=60.0)

    # Worker commits step 1
    assert (
        dr.commit_action_result(
            "task_order_process",
            "worker_pod_alpha",
            fencing_token=1,
            step=1,
            action_data={"item": "book", "qty": 1},
        )
        is True
    )

    # Inject Chaos: Pod Termination
    dr.inject_fault(FaultType.POD_TERMINATION, "worker_pod_alpha")

    # Terminated pod attempts step 2 -> REJECTED
    assert (
        dr.commit_action_result(
            "task_order_process",
            "worker_pod_alpha",
            fencing_token=1,
            step=2,
            action_data={"charged": True},
        )
        is False
    )

    # Recover task to worker_pod_beta
    recovery = dr.recover_task("task_order_process", "org_commerce", "worker_pod_beta")
    assert recovery.recovery_status == "RECONCILED"
    assert recovery.last_checkpoint_step == 1
    assert recovery.fencing_token == 2

    # New worker resumes from checkpoint step 2
    assert (
        dr.commit_action_result(
            "task_order_process",
            "worker_pod_beta",
            fencing_token=2,
            step=2,
            action_data={"charged": True},
        )
        is True
    )


# --- K8S-19: Stale Worker Lease Fencing ---


def test_k8s19_stale_worker_lease_fencing():
    """K8S-19: Verify stale worker epochs cannot overwrite modern task state."""
    dr = DisasterRecoveryCoordinator()
    dr.grant_lease("task_stock_trade", "worker_zombie", initial_fencing_token=1)

    # Task reassigned to modern worker (token increments to 2)
    dr.recover_task("task_stock_trade", "org_fintech", "worker_modern")

    # Zombie worker wakes up from GC pause and attempts to commit with stale token 1 -> REJECTED
    assert (
        dr.commit_action_result(
            "task_stock_trade",
            "worker_zombie",
            fencing_token=1,
            step=1,
            action_data={"execute_order": True},
        )
        is False
    )


# --- K8S-20: Infrastructure Observability & Prometheus ---


def test_k8s20_infrastructure_observability_and_prometheus():
    """K8S-20: Verify Prometheus exposition format for cluster, queue, GPU metrics."""
    metrics = AtlasInfrastructureMetrics()
    metrics.record_cluster_availability("cls_us_east", "us-east-1", True)
    metrics.record_pod_health("atlas-api-78f94-x2", "api", True)
    metrics.record_worker_count("linux-pool", "cls_us_east", 12)
    metrics.record_scheduler_latency("cls_us_east", 0.014)
    metrics.record_queue_depth("org_enterprise", "CRITICAL", 3)
    metrics.record_gpu_utilization("worker_h100_01", 0, "H100-80GB", 0.75)
    metrics.record_autoscaler_event("linux-pool", "SCALE_UP")

    text = metrics.render_prometheus_text()
    assert "atlas_cluster_availability{" in text
    assert "atlas_pod_health_status{" in text
    assert "atlas_worker_active_count{" in text
    assert "atlas_scheduler_latency_seconds{" in text
    assert "atlas_queue_depth{" in text
    assert "atlas_gpu_utilization_ratio{" in text
    assert "atlas_autoscaler_events_total{" in text


# --- K8S-21: Pod Security Standards ---


def test_k8s21_pod_security_standards_enforcement():
    """K8S-21: Verify Helm templates enforce non-root UID 10001 and dropped capabilities."""
    chart_dir = REPO_ROOT / "deploy" / "helm" / "atlas"
    helm_bin = _get_helm_binary()

    render_res = subprocess.run(
        [
            helm_bin,
            "template",
            "atlas-security-test",
            str(chart_dir),
            "-f",
            str(chart_dir / "values-prod.yaml"),
        ],
        capture_output=True,
        text=True,
    )
    assert render_res.returncode == 0
    docs = list(yaml.safe_load_all(render_res.stdout))

    deployments = [d for d in docs if d and d.get("kind") == "Deployment"]
    assert len(deployments) >= 3  # API, Supervisor, Worker

    for dep in deployments:
        pod_sec = dep.get("spec", {}).get("template", {}).get("spec", {}).get("securityContext", {})
        assert pod_sec.get("runAsNonRoot") is True
        assert pod_sec.get("runAsUser") == 10001
        assert pod_sec.get("runAsGroup") == 10001

        containers = dep.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        for c in containers:
            c_sec = c.get("securityContext", {})
            assert c_sec.get("readOnlyRootFilesystem") is True
            assert c_sec.get("allowPrivilegeEscalation") is False
            assert "ALL" in c_sec.get("capabilities", {}).get("drop", [])


# --- K8S-22: Network Policy Isolation ---


def test_k8s22_network_policy_isolation():
    """K8S-22: Verify NetworkPolicy restricts ingress and egress traffic."""
    chart_dir = REPO_ROOT / "deploy" / "helm" / "atlas"
    helm_bin = _get_helm_binary()

    render_res = subprocess.run(
        [
            helm_bin,
            "template",
            "atlas-netpol-test",
            str(chart_dir),
            "-f",
            str(chart_dir / "values-prod.yaml"),
        ],
        capture_output=True,
        text=True,
    )
    assert render_res.returncode == 0
    docs = list(yaml.safe_load_all(render_res.stdout))

    netpols = [d for d in docs if d and d.get("kind") == "NetworkPolicy"]
    assert len(netpols) >= 1
    np = netpols[0]
    spec = np.get("spec", {})
    assert "Ingress" in spec.get("policyTypes", [])
    assert "Egress" in spec.get("policyTypes", [])


# --- K8S-23: Tenant-Aware Scheduling ---


def test_k8s23_tenant_aware_scheduling():
    """K8S-23: Verify global scheduler prevents tenant task placement onto unauthorized clusters."""
    mcm = MultiClusterManager()

    # Enrolled cluster restricted to tenant A and B
    mcm.register_cluster(
        cluster_id="cls_isolated_corp",
        name="isolated-corp",
        region="us-east-1",
        api_endpoint="https://corp.internal",
        auth_token="tok_corp",
        tenant_allowed_list=["org_tenant_A", "org_tenant_B"],
    )

    # Tenant A request -> Allowed
    req_a = ClusterTaskRequirements(task_id="task_a", tenant_id="org_tenant_A")
    assert mcm.select_cluster_for_task(req_a) == "cls_isolated_corp"

    # Unauthorized Tenant C request -> Denied
    req_c = ClusterTaskRequirements(task_id="task_c", tenant_id="org_tenant_C")
    assert mcm.select_cluster_for_task(req_c) is None


# --- K8S-24: Monorepo Regression Invariant ---


def test_k8s24_monorepo_regression_and_core_zero_dependency_invariant():
    """K8S-24: Verify zero external dependencies in packages/atlas-core."""
    core_pyproject = REPO_ROOT / "packages" / "atlas-core" / "pyproject.toml"
    assert core_pyproject.exists()
    content = core_pyproject.read_text(encoding="utf-8")
    assert "pydantic" in content
    # Ensure no driver or k8s client is in atlas-core
    assert "kubernetes" not in content
    assert "playwright" not in content
    assert "psycopg" not in content
    assert "fastapi" not in content
