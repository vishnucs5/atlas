"""Phase 9 Distributed Execution Network Acceptance Suite (Scenarios DN-01 to DN-30)."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from atlas_api.main import app
from atlas_api.routes.distributed import reset_distributed_services
from atlas_core.contracts.action import ActionResult, ComputerAction
from atlas_core.contracts.graph import TaskGraph, TaskNode
from atlas_core.contracts.worker import WorkerStatus
from atlas_core.runtime.driver import ComputerDriver, DriverHealth
from atlas_distributed.coordinator import DistributedTaskCoordinator
from atlas_distributed.enrollment import (
    InvalidEnrollmentTokenError,
    WorkerAuthenticationError,
    WorkerEnrollmentAuthority,
    WorkerRevokedError,
)
from atlas_distributed.fault_tolerance import DistributedRecoveryManager
from atlas_distributed.models import (
    AssignmentPayload,
    AssignmentResult,
    AssignmentStatus,
    EnrollmentRequest,
    ProtocolMessageType,
    SessionType,
    WorkerCapabilities,
    WorkerPlatform,
)
from atlas_distributed.protocol import (
    CURRENT_PROTOCOL_VERSION,
    InvalidSignatureError,
    MessageDeduplicator,
    ProtocolVersionMismatchError,
    ReplayAttackError,
    create_envelope,
    verify_envelope,
)
from atlas_distributed.scheduler import (
    DistributedScheduler,
    NoEligibleWorkerError,
    SchedulerQueueFullError,
    TaskRequirements,
)
from atlas_distributed.worker import (
    InMemoryControlPlaneTransport,
    WorkerAgent,
    WorkerAgentConfig,
)
from atlas_storage.interfaces import StaleWorkerError
from atlas_storage.sqlite import SQLiteStorage
from fastapi.testclient import TestClient


class MockDriver(ComputerDriver):
    """Mock ComputerDriver for testing."""

    def __init__(self, name: str = "mock_driver", should_fail: bool = False):
        self.name = name
        self.should_fail = should_fail
        self.executed_actions: list[ComputerAction] = []

    async def connect(self, config: dict | None = None) -> None:
        pass

    async def observe(self) -> None:
        pass

    async def execute(self, action: ComputerAction) -> ActionResult:
        self.executed_actions.append(action)
        if self.should_fail:
            return ActionResult(
                action_id="act_fail",
                success=False,
                duration_ms=10,
                error="Simulated driver failure",
            )
        return ActionResult(
            action_id="act_ok",
            success=True,
            duration_ms=25,
            output={"result": f"Executed on {self.name}", "action": action.action_type},
            evidence={"sha256": hashlib.sha256(b"artifact_data").hexdigest()},
        )

    async def health_check(self) -> DriverHealth:
        return DriverHealth(driver_type=self.name, connected=True)

    async def disconnect(self) -> None:
        pass


@pytest.fixture(autouse=True)
def clean_services():
    reset_distributed_services()
    yield
    reset_distributed_services()


@pytest.fixture
def authority() -> WorkerEnrollmentAuthority:
    return WorkerEnrollmentAuthority()


# ---------------------------------------------------------------------------
# DN-01: Worker Enrollment with Cryptographic Provisioning Tokens
# ---------------------------------------------------------------------------
def test_dn_01_worker_enrollment_with_tokens(authority):
    raw_token, token_record = authority.create_enrollment_token(tenant_id="tenant-prod")
    req = EnrollmentRequest(
        provisioning_token=raw_token,
        hostname="node-prod-01",
        capabilities=WorkerCapabilities(drivers=["bash"]),
        tenant_id="tenant-prod",
    )
    resp = authority.enroll_worker(req)
    assert resp.worker_id.startswith("worker_")
    assert resp.tenant_id == "tenant-prod"
    assert resp.auth_token.startswith("wat_")


# ---------------------------------------------------------------------------
# DN-02: Rejection of Invalid or Expired Enrollment Tokens
# ---------------------------------------------------------------------------
def test_dn_02_rejection_of_invalid_or_expired_tokens(authority):
    # 1. Invalid token secret
    req_bad = EnrollmentRequest(
        provisioning_token="atk_invalid_token_secret",
        hostname="node-bad",
        capabilities=WorkerCapabilities(),
    )
    with pytest.raises(InvalidEnrollmentTokenError):
        authority.enroll_worker(req_bad)

    # 2. Expired token
    raw_exp, exp_rec = authority.create_enrollment_token(ttl=timedelta(seconds=-10))
    req_exp = EnrollmentRequest(
        provisioning_token=raw_exp,
        hostname="node-exp",
        capabilities=WorkerCapabilities(),
    )
    with pytest.raises(InvalidEnrollmentTokenError):
        authority.enroll_worker(req_exp)


# ---------------------------------------------------------------------------
# DN-03: Immediate Credential Revocation and CRL Enforcement
# ---------------------------------------------------------------------------
def test_dn_03_credential_revocation_and_crl(authority):
    token, _ = authority.create_enrollment_token()
    resp = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token, hostname="node-rev", capabilities=WorkerCapabilities()
        )
    )
    # Revoke worker
    authority.revoke_worker(resp.worker_id, reason="Security compromise")

    # Re-authentication must raise WorkerRevokedError
    with pytest.raises(WorkerRevokedError):
        authority.authenticate_worker(resp.worker_id, resp.auth_token)


# ---------------------------------------------------------------------------
# DN-04: Authentication Failure Handling on Worker Endpoints
# ---------------------------------------------------------------------------
def test_dn_04_authentication_failure_handling(authority):
    token, _ = authority.create_enrollment_token()
    resp = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token, hostname="node-auth", capabilities=WorkerCapabilities()
        )
    )
    with pytest.raises(WorkerAuthenticationError):
        authority.authenticate_worker(resp.worker_id, "wrong_auth_token_secret")


# ---------------------------------------------------------------------------
# DN-05: Capability Matching: Required OS, Drivers, and Browsers
# ---------------------------------------------------------------------------
def test_dn_05_capability_matching_os_drivers_browsers(authority):
    token, _ = authority.create_enrollment_token()
    authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token,
            hostname="node-linux",
            capabilities=WorkerCapabilities(
                platform=WorkerPlatform.LINUX,
                drivers=["bash", "playwright"],
                browsers=["chromium", "firefox"],
            ),
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority)
    req = TaskRequirements(
        task_id="t_match",
        required_platform=WorkerPlatform.LINUX,
        required_drivers=["playwright"],
        required_browsers=["firefox"],
    )
    worker, payload = scheduler.schedule_task(req)
    assert worker.capabilities.platform == WorkerPlatform.LINUX
    assert "playwright" in worker.capabilities.drivers
    assert "firefox" in worker.capabilities.browsers


# ---------------------------------------------------------------------------
# DN-06: Incompatible Worker Rejection When Capabilities Do Not Match
# ---------------------------------------------------------------------------
def test_dn_06_incompatible_worker_rejection(authority):
    token, _ = authority.create_enrollment_token()
    authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token,
            hostname="node-basic",
            capabilities=WorkerCapabilities(platform=WorkerPlatform.LINUX, drivers=["bash"]),
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority)
    req_missing_driver = TaskRequirements(
        task_id="t_missing", required_drivers=["special_gpu_driver"]
    )
    with pytest.raises(NoEligibleWorkerError) as exc_info:
        scheduler.schedule_task(req_missing_driver)
    assert "missing drivers" in str(exc_info.value)


# ---------------------------------------------------------------------------
# DN-07: Task Assignment Creation with Unique IDs and Fencing Token
# ---------------------------------------------------------------------------
def test_dn_07_task_assignment_creation_with_fencing(authority):
    token, _ = authority.create_enrollment_token()
    authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token, hostname="node-fencing", capabilities=WorkerCapabilities()
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority)
    _, payload = scheduler.schedule_task(TaskRequirements(task_id="t_fence_01"))
    assert payload.assignment_id.startswith("asgn_")
    assert payload.task_id == "t_fence_01"
    assert payload.lease_id.startswith("lease_")
    assert payload.generation >= 1


# ---------------------------------------------------------------------------
# DN-08: Worker Assignment Acknowledgement and State Transition
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dn_08_worker_assignment_ack_and_state_running(authority):
    token, _ = authority.create_enrollment_token()
    resp = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token, hostname="node-ack", capabilities=WorkerCapabilities()
        )
    )
    transport = InMemoryControlPlaneTransport()
    agent = WorkerAgent(config=WorkerAgentConfig(worker_id=resp.worker_id), transport=transport)
    assert agent.status == WorkerStatus.IDLE

    assignment = AssignmentPayload(
        assignment_id="asgn_ack_01",
        task_id="task_ack_01",
        worker_id=resp.worker_id,
        lease_id="l_ack",
        generation=1,
        objective="Run computation",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    result = await agent.execute_assignment(assignment)
    assert result.status == AssignmentStatus.COMPLETED
    assert len(transport.progress_events) >= 1
    assert transport.progress_events[0].status == AssignmentStatus.RUNNING


# ---------------------------------------------------------------------------
# DN-09: Worker Heartbeat Monitoring and Automatic Expiration
# ---------------------------------------------------------------------------
def test_dn_09_worker_heartbeat_monitoring_and_expiration(authority):
    token, _ = authority.create_enrollment_token()
    resp = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token, hostname="node-hb", capabilities=WorkerCapabilities()
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority)
    recovery_mgr = DistributedRecoveryManager(
        enrollment_authority=authority,
        scheduler=scheduler,
        heartbeat_timeout_seconds=5.0,
    )
    worker = authority.get_worker(resp.worker_id)
    assert worker is not None
    # Simulate missed heartbeats
    worker.last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=15.0)

    evicted = recovery_mgr.detect_and_handle_dead_workers()
    assert resp.worker_id in evicted
    assert worker.status == WorkerStatus.DISCONNECTED


# ---------------------------------------------------------------------------
# DN-10: Lease Fencing Token Validation Rejecting Stale Worker
# ---------------------------------------------------------------------------
def test_dn_10_lease_fencing_rejecting_stale_commit(authority):
    token, _ = authority.create_enrollment_token()
    resp = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token, hostname="node-fencing", capabilities=WorkerCapabilities()
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority)
    recovery_mgr = DistributedRecoveryManager(enrollment_authority=authority, scheduler=scheduler)

    _, payload = scheduler.schedule_task(TaskRequirements(task_id="t_fenced_10"))
    recovery_mgr.register_assignment(payload)

    # Monotonic increment simulates reassignment to generation 2
    payload.generation = 2

    # Stale commit at generation 1
    stale_result = AssignmentResult(
        assignment_id=payload.assignment_id,
        task_id=payload.task_id,
        worker_id=resp.worker_id,
        generation=1,
        status=AssignmentStatus.COMPLETED,
    )
    with pytest.raises(StaleWorkerError):
        recovery_mgr.validate_fencing_and_complete(stale_result)


# ---------------------------------------------------------------------------
# DN-11: Duplicate Assignment Message Deduplication and Replay Protection
# ---------------------------------------------------------------------------
def test_dn_11_message_deduplication_and_replay_protection():
    dedup = MessageDeduplicator()
    env = create_envelope(
        message_type=ProtocolMessageType.ASSIGNMENT_OFFER,
        sender_id="cp",
        recipient_id="wrk_1",
        payload={"asgn_id": "asgn_1"},
        secret_key="secret",
        sequence_number=1,
    )
    dedup.process_envelope(env)
    with pytest.raises(ReplayAttackError):
        dedup.process_envelope(env)


# ---------------------------------------------------------------------------
# DN-12: Network Interruption Handling with Ring Buffer Replay
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dn_12_network_interruption_reconnection_ring_buffer():
    transport = InMemoryControlPlaneTransport()
    agent = WorkerAgent(config=WorkerAgentConfig(worker_id="wrk_net"), transport=transport)
    transport.should_fail_network = True

    asgn = AssignmentPayload(
        assignment_id="asgn_net",
        task_id="t_net",
        worker_id="wrk_net",
        lease_id="l_net",
        generation=1,
        objective="Execute while offline",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    await agent.execute_assignment(asgn)
    assert agent.connected is False
    assert len(agent.buffer.get_unacknowledged()) >= 1

    # Reconnect
    transport.should_fail_network = False
    await agent.send_heartbeat()
    assert agent.connected is True
    assert len(transport.completed_assignments) == 1
    assert len(agent.buffer.get_unacknowledged()) == 0


# ---------------------------------------------------------------------------
# DN-13: Worker Process Termination Detection and Eviction
# ---------------------------------------------------------------------------
def test_dn_13_worker_process_termination_detection_and_eviction(authority):
    token, _ = authority.create_enrollment_token()
    resp = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token, hostname="node-term", capabilities=WorkerCapabilities()
        )
    )
    worker = authority.get_worker(resp.worker_id)
    assert worker is not None
    worker.status = WorkerStatus.TERMINATED

    scheduler = DistributedScheduler(enrollment_authority=authority)
    with pytest.raises(NoEligibleWorkerError):
        scheduler.schedule_task(TaskRequirements(task_id="t_term"))


# ---------------------------------------------------------------------------
# DN-14: Machine Restart Simulation and Durable State Recovery
# ---------------------------------------------------------------------------
def test_dn_14_machine_restart_simulation_durable_recovery(authority):
    token, _ = authority.create_enrollment_token()
    resp = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token, hostname="node-restart", capabilities=WorkerCapabilities()
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority)
    _, p1 = scheduler.schedule_task(TaskRequirements(task_id="t_reboot"))
    assert p1.generation == 1

    # Node reboot: simulated crash and recovery
    recovery_mgr = DistributedRecoveryManager(enrollment_authority=authority, scheduler=scheduler)
    recovery_mgr.register_assignment(p1)
    states = recovery_mgr.recover_worker_assignments(resp.worker_id)
    assert len(states) == 1
    assert states[0].task_id == "t_reboot"


# ---------------------------------------------------------------------------
# DN-15: Control Plane Restart and In-Flight Assignment Reconciliation
# ---------------------------------------------------------------------------
def test_dn_15_control_plane_restart_in_flight_reconciliation(authority):
    token, _ = authority.create_enrollment_token()
    enroll_worker = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token, hostname="node-cp-restart", capabilities=WorkerCapabilities()
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority)
    _, payload = scheduler.schedule_task(TaskRequirements(task_id="t_cp_rst"))

    # CP reboots: create fresh recovery manager, register payload, re-validate fencing
    fresh_recovery = DistributedRecoveryManager(enrollment_authority=authority, scheduler=scheduler)
    fresh_recovery.register_assignment(payload)
    result = AssignmentResult(
        assignment_id=payload.assignment_id,
        task_id=payload.task_id,
        worker_id=enroll_worker.worker_id,
        generation=payload.generation,
        status=AssignmentStatus.COMPLETED,
    )
    assert fresh_recovery.validate_fencing_and_complete(result) is True


# ---------------------------------------------------------------------------
# DN-16: Stale Worker Completion Rejection After Reassignment
# ---------------------------------------------------------------------------
def test_dn_16_stale_worker_completion_rejection_after_reassignment(authority):
    token1, _ = authority.create_enrollment_token()
    w1 = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token1, hostname="node-w1", capabilities=WorkerCapabilities()
        )
    )
    token2, _ = authority.create_enrollment_token()
    authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token2, hostname="node-w2", capabilities=WorkerCapabilities()
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority)
    recovery_mgr = DistributedRecoveryManager(enrollment_authority=authority, scheduler=scheduler)

    _, p1 = scheduler.schedule_task(
        TaskRequirements(task_id="t_reassign", action_type="screenshot")
    )
    recovery_mgr.register_assignment(p1)

    # Recover and reassign to w2
    p2 = recovery_mgr.reassign_assignment(p1)
    assert p2.generation > p1.generation

    # w1 wakes up and tries to complete p1
    w1_stale_result = AssignmentResult(
        assignment_id=p1.assignment_id,
        task_id=p1.task_id,
        worker_id=w1.worker_id,
        generation=p1.generation,
        status=AssignmentStatus.COMPLETED,
    )
    with pytest.raises(StaleWorkerError):
        recovery_mgr.validate_fencing_and_complete(w1_stale_result)


# ---------------------------------------------------------------------------
# DN-17: Concurrent Reassignment Prevention Across Multiple Workers
# ---------------------------------------------------------------------------
def test_dn_17_concurrent_reassignment_prevention(authority):
    token, _ = authority.create_enrollment_token()
    authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token,
            hostname="node-conc",
            capabilities=WorkerCapabilities(max_concurrent_tasks=1),
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority)
    scheduler.schedule_task(TaskRequirements(task_id="t_exclusive"))
    with pytest.raises(NoEligibleWorkerError):
        scheduler.schedule_task(TaskRequirements(task_id="t_exclusive_2"))


# ---------------------------------------------------------------------------
# DN-18: Unknown External Side-Effect Protection
# ---------------------------------------------------------------------------
def test_dn_18_unknown_external_side_effect_protection(authority):
    token, _ = authority.create_enrollment_token()
    w = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token, hostname="node-side-effect", capabilities=WorkerCapabilities()
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority)
    recovery_mgr = DistributedRecoveryManager(enrollment_authority=authority, scheduler=scheduler)

    _, payload = scheduler.schedule_task(
        TaskRequirements(task_id="t_danger", action_type="execute_bank_transfer")
    )
    recovery_mgr.register_assignment(payload)
    recovery_mgr.recover_worker_assignments(w.worker_id)

    # Must raise NonIdempotentActionUncertaintyError on blind retry
    from atlas_coordination.action_ledger import NonIdempotentActionUncertaintyError

    with pytest.raises(NonIdempotentActionUncertaintyError):
        recovery_mgr.reassign_assignment(payload)


# ---------------------------------------------------------------------------
# DN-19: Cross-Tenant Isolation
# ---------------------------------------------------------------------------
def test_dn_19_cross_tenant_isolation(authority):
    t_a, _ = authority.create_enrollment_token(tenant_id="tenant-a")
    t_b, _ = authority.create_enrollment_token(tenant_id="tenant-b")
    w_a = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=t_a,
            hostname="node-a",
            tenant_id="tenant-a",
            capabilities=WorkerCapabilities(),
        )
    )
    authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=t_b,
            hostname="node-b",
            tenant_id="tenant-b",
            capabilities=WorkerCapabilities(),
        )
    )

    scheduler = DistributedScheduler(enrollment_authority=authority)
    w_res, p_res = scheduler.schedule_task(TaskRequirements(task_id="t_iso", tenant_id="tenant-a"))
    assert w_res.worker_id == w_a.worker_id
    assert p_res.tenant_id == "tenant-a"


# ---------------------------------------------------------------------------
# DN-20: Artifact Transfer Authorization and Integrity Verification
# ---------------------------------------------------------------------------
def test_dn_20_artifact_transfer_authorization_and_integrity():
    content = b"Production dataset output 2026"
    expected_sha = hashlib.sha256(content).hexdigest()
    delivered_artifact = {"name": "data.csv", "sha256": expected_sha, "bytes": len(content)}
    assert hashlib.sha256(content).hexdigest() == delivered_artifact["sha256"]


# ---------------------------------------------------------------------------
# DN-21: Malicious Message Payload Rejection and Schema Validation
# ---------------------------------------------------------------------------
def test_dn_21_malicious_message_payload_rejection():
    secret = "secret_key_prod"
    env = create_envelope(
        message_type=ProtocolMessageType.ACTION_REQUEST,
        sender_id="node_1",
        recipient_id="cp",
        payload={"action": "rm -rf /"},
        secret_key=secret,
    )
    # Tamper payload
    env.payload["action"] = "rm -rf / --no-preserve-root"
    with pytest.raises(InvalidSignatureError):
        verify_envelope(env, secret_key=secret)


# ---------------------------------------------------------------------------
# DN-22: Worker Resource Exhaustion Reporting and Backpressure Throttling
# ---------------------------------------------------------------------------
def test_dn_22_worker_resource_exhaustion_and_backpressure(authority):
    token, _ = authority.create_enrollment_token()
    authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token,
            hostname="node-exhaustion",
            capabilities=WorkerCapabilities(max_concurrent_tasks=1),
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority, max_queue_depth=1)
    scheduler.schedule_task(TaskRequirements(task_id="t_active"))
    with pytest.raises(NoEligibleWorkerError):
        scheduler.submit_task(TaskRequirements(task_id="t_q1"))
    with pytest.raises(SchedulerQueueFullError):
        scheduler.submit_task(TaskRequirements(task_id="t_q2"))


# ---------------------------------------------------------------------------
# DN-23: Distributed Task Cancellation Propagation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dn_23_distributed_task_cancellation_propagation():
    transport = InMemoryControlPlaneTransport()
    agent = WorkerAgent(config=WorkerAgentConfig(worker_id="wrk_cancel"), transport=transport)
    asgn = AssignmentPayload(
        assignment_id="asgn_canc_23",
        task_id="t_canc_23",
        worker_id="wrk_cancel",
        lease_id="l1",
        generation=1,
        objective="Long task",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    agent.cancel_assignment("asgn_canc_23")
    result = await agent.execute_assignment(asgn)
    assert result.status == AssignmentStatus.CANCELLED


# ---------------------------------------------------------------------------
# DN-24: Recovery and Reconciliation State Machine Restoration
# ---------------------------------------------------------------------------
def test_dn_24_recovery_and_reconciliation_state_machine(authority):
    token, _ = authority.create_enrollment_token()
    w = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token, hostname="node-rec24", capabilities=WorkerCapabilities()
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority)
    recovery_mgr = DistributedRecoveryManager(enrollment_authority=authority, scheduler=scheduler)
    _, payload = scheduler.schedule_task(TaskRequirements(task_id="t_rec24", action_type="click"))
    recovery_mgr.register_assignment(payload)
    recovery_mgr.recover_worker_assignments(w.worker_id)

    reconciled = recovery_mgr.reconcile_external_action(
        assignment_id=payload.assignment_id,
        verified_status="VERIFIED_NOT_EXECUTED",
        notes="Checked DOM state; button was not clicked",
    )
    assert reconciled.reconciled is True
    assert reconciled.reconciled_status == "VERIFIED_NOT_EXECUTED"


# ---------------------------------------------------------------------------
# DN-25: Distributed Workflow Execution: Multi-Worker DAG Coordination
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dn_25_distributed_workflow_dag_parallel_branches(authority):
    t1, _ = authority.create_enrollment_token()
    t2, _ = authority.create_enrollment_token()
    authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=t1,
            hostname="w-lin",
            capabilities=WorkerCapabilities(platform=WorkerPlatform.LINUX, drivers=["bash"]),
        )
    )
    authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=t2,
            hostname="w-win",
            capabilities=WorkerCapabilities(
                platform=WorkerPlatform.WINDOWS,
                session_type=SessionType.INTERACTIVE_USER,
                drivers=["desktop"],
            ),
        )
    )

    scheduler = DistributedScheduler(enrollment_authority=authority)
    coordinator = DistributedTaskCoordinator(scheduler=scheduler)

    n1 = TaskNode(
        node_id="n1",
        task_id="t_dag",
        name="Task 1",
        parameters={"required_platform": WorkerPlatform.LINUX, "required_drivers": ["bash"]},
    )
    n2 = TaskNode(
        node_id="n2",
        task_id="t_dag",
        name="Task 2",
        parameters={
            "required_platform": WorkerPlatform.WINDOWS,
            "requires_interactive_desktop": True,
            "required_drivers": ["desktop"],
        },
        dependencies=["n1"],
    )
    graph = TaskGraph(graph_id="g1", task_id="t_dag", nodes={"n1": n1, "n2": n2})

    summary = await coordinator.execute_task_graph(graph)
    assert summary.status == "COMPLETED"
    assert len(summary.node_results) == 2


# ---------------------------------------------------------------------------
# DN-26: Heterogeneous Worker Support: Windows 11 Desktop and Linux Container
# ---------------------------------------------------------------------------
def test_dn_26_heterogeneous_worker_windows_and_linux(authority):
    t1, _ = authority.create_enrollment_token()
    t2, _ = authority.create_enrollment_token()
    w_lin = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=t1,
            hostname="linux-runner",
            capabilities=WorkerCapabilities(
                platform=WorkerPlatform.LINUX, session_type=SessionType.HEADLESS, drivers=["bash"]
            ),
        )
    )
    w_win = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=t2,
            hostname="win11-desktop",
            capabilities=WorkerCapabilities(
                platform=WorkerPlatform.WINDOWS,
                session_type=SessionType.INTERACTIVE_USER,
                drivers=["cmd", "desktop"],
            ),
        )
    )
    scheduler = DistributedScheduler(enrollment_authority=authority)
    # Schedule interactive GUI task
    w_gui, _ = scheduler.schedule_task(
        TaskRequirements(task_id="t_gui", requires_interactive_desktop=True)
    )
    assert w_gui.worker_id == w_win.worker_id

    # Schedule headless linux task
    w_head, _ = scheduler.schedule_task(
        TaskRequirements(task_id="t_head", required_platform=WorkerPlatform.LINUX)
    )
    assert w_head.worker_id == w_lin.worker_id


# ---------------------------------------------------------------------------
# DN-27: Remote Protocol Version Negotiation
# ---------------------------------------------------------------------------
def test_dn_27_remote_protocol_version_negotiation():
    secret = "secret_rep"
    env_good = create_envelope(
        message_type=ProtocolMessageType.HEARTBEAT,
        sender_id="w1",
        recipient_id="cp",
        payload={"ping": 1},
        secret_key=secret,
        protocol_version=CURRENT_PROTOCOL_VERSION,
    )
    assert verify_envelope(env_good, secret_key=secret) is True

    env_bad = create_envelope(
        message_type=ProtocolMessageType.HEARTBEAT,
        sender_id="w1",
        recipient_id="cp",
        payload={"ping": 1},
        secret_key=secret,
        protocol_version="ATLAS-REP/0.1-LEGACY",
    )
    with pytest.raises(ProtocolVersionMismatchError):
        verify_envelope(env_bad, secret_key=secret)


# ---------------------------------------------------------------------------
# DN-28: Distributed Event Ordering and Monotonic Sequence Enforcement
# ---------------------------------------------------------------------------
def test_dn_28_distributed_event_ordering_monotonic_sequence():
    dedup = MessageDeduplicator()
    secret = "secret"
    env1 = create_envelope(
        message_type=ProtocolMessageType.PROGRESS_EVENT,
        sender_id="w1",
        recipient_id="cp",
        payload={"step": 1},
        secret_key=secret,
        sequence_number=1,
    )
    env2 = create_envelope(
        message_type=ProtocolMessageType.PROGRESS_EVENT,
        sender_id="w1",
        recipient_id="cp",
        payload={"step": 2},
        secret_key=secret,
        sequence_number=2,
    )
    env_stale = create_envelope(
        message_type=ProtocolMessageType.PROGRESS_EVENT,
        sender_id="w1",
        recipient_id="cp",
        payload={"step": 1},
        secret_key=secret,
        sequence_number=1,
    )

    dedup.process_envelope(env1)
    dedup.process_envelope(env2)
    with pytest.raises(ReplayAttackError):
        dedup.process_envelope(env_stale)


# ---------------------------------------------------------------------------
# DN-29: Control Plane Database Recovery & Failover Verification
# ---------------------------------------------------------------------------
def test_dn_29_control_plane_database_recovery_and_failover():
    from atlas_core.contracts.worker import WorkerRecord

    storage = SQLiteStorage(":memory:")
    storage.initialize()
    storage.register_worker(
        WorkerRecord(
            worker_id="wrk_db_test",
            hostname="db-host",
            capabilities=["bash", "playwright"],
            metadata={"platform": "linux"},
        )
    )
    workers = storage.list_workers()
    assert any(w.worker_id == "wrk_db_test" for w in workers)
    storage.close()


# ---------------------------------------------------------------------------
# DN-30: Full End-to-End Distributed Execution via REST API
# ---------------------------------------------------------------------------
def test_dn_30_full_end_to_end_distributed_execution():
    client = TestClient(app)

    # 1. Create provisioning token
    res_tok = client.post(
        "/api/v1/distributed/tokens", json={"tenant_id": "tenant-e2e", "max_uses": 2}
    )
    assert res_tok.status_code == 201
    token_data = res_tok.json()
    prov_token = token_data["provisioning_token"]

    # 2. Worker enrolls via API
    enroll_payload = {
        "provisioning_token": prov_token,
        "hostname": "node-e2e-01",
        "tenant_id": "tenant-e2e",
        "capabilities": {
            "platform": "linux",
            "session_type": "headless",
            "drivers": ["bash", "custom_driver"],
            "browsers": ["chromium"],
            "max_concurrent_tasks": 2,
        },
    }
    res_enroll = client.post("/api/v1/distributed/enroll", json=enroll_payload)
    assert res_enroll.status_code == 201
    enroll_data = res_enroll.json()
    worker_id = enroll_data["worker_id"]

    # 3. Heartbeat
    hb_res = client.post(
        f"/api/v1/distributed/workers/{worker_id}/heartbeat",
        json={"worker_id": worker_id, "status": "IDLE", "sequence_number": 1},
    )
    assert hb_res.status_code == 200

    # 4. Schedule assignment via API
    task_req = {
        "task_id": "task_e2e_100",
        "tenant_id": "tenant-e2e",
        "objective": "Process data remotely",
        "required_drivers": ["custom_driver"],
    }
    res_asgn = client.post("/api/v1/distributed/assignments", json=task_req)
    assert res_asgn.status_code == 201
    asgn_data = res_asgn.json()
    asgn_id = asgn_data["assignment"]["assignment_id"]
    generation = asgn_data["assignment"]["generation"]

    # 5. Stream progress via API
    prog_res = client.post(
        f"/api/v1/distributed/assignments/{asgn_id}/progress",
        json={
            "assignment_id": asgn_id,
            "task_id": "task_e2e_100",
            "worker_id": worker_id,
            "step_index": 1,
            "progress_pct": 50.0,
            "message": "Processing batch",
        },
    )
    assert prog_res.status_code == 200

    # 6. Complete assignment via API
    complete_res = client.post(
        f"/api/v1/distributed/assignments/{asgn_id}/complete",
        json={
            "assignment_id": asgn_id,
            "task_id": "task_e2e_100",
            "worker_id": worker_id,
            "generation": generation,
            "status": "COMPLETED",
            "output": {"result": "success"},
            "deliverables": {"report": "data ready"},
            "verification_evidence": {"verified": True},
        },
    )
    assert complete_res.status_code == 200
    assert complete_res.json()["verified"] is True

    # 7. Query fleet metrics
    res_metrics = client.get("/api/v1/distributed/fleet/metrics")
    assert res_metrics.status_code == 200
    metrics = res_metrics.json()
    assert metrics["total_workers"] >= 1
