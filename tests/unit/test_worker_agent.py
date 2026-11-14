"""Unit tests for Lightweight Installable Worker Agent Daemon (Milestone 2)."""

from datetime import UTC, datetime, timedelta

import pytest
from atlas_core.contracts.action import ActionResult, ComputerAction
from atlas_core.contracts.worker import WorkerStatus
from atlas_core.runtime.driver import ComputerDriver, DriverHealth
from atlas_distributed.enrollment import (
    SessionZeroInteractiveError,
    WorkerEnrollmentAuthority,
)
from atlas_distributed.models import (
    AssignmentPayload,
    AssignmentStatus,
    SessionType,
    WorkerCapabilities,
    WorkerPlatform,
)
from atlas_distributed.worker import (
    EventRingBuffer,
    InMemoryControlPlaneTransport,
    WorkerAgent,
    WorkerAgentConfig,
    detect_capabilities,
    detect_hardware,
    detect_platform,
    detect_session_type,
)


class MockTestDriver(ComputerDriver):
    """Mock implementation of ComputerDriver protocol for unit testing."""

    def __init__(self, name: str = "test_driver", fail_execution: bool = False):
        self.name = name
        self.fail_execution = fail_execution
        self.executed_actions: list[ComputerAction] = []

    async def connect(self, config: dict | None = None) -> None:
        pass

    async def observe(self) -> None:
        pass

    async def execute(self, action: ComputerAction) -> ActionResult:
        self.executed_actions.append(action)
        if self.fail_execution:
            return ActionResult(
                action_id="act_err",
                success=False,
                duration_ms=15,
                error="Simulated driver execution error",
            )
        return ActionResult(
            action_id="act_001",
            success=True,
            duration_ms=25,
            output={"result": f"Executed action on {self.name}"},
            evidence={"state_changed": True},
        )

    async def health_check(self) -> DriverHealth:
        return DriverHealth(driver_type=self.name, connected=True)

    async def disconnect(self) -> None:
        pass


def test_platform_and_session_detection():
    """Verify platform, hardware, and session type detection routines."""
    plat = detect_platform()
    assert plat in [
        WorkerPlatform.WINDOWS,
        WorkerPlatform.LINUX,
        WorkerPlatform.DARWIN,
        WorkerPlatform.CONTAINER,
    ]

    session = detect_session_type(plat)
    assert session in [SessionType.INTERACTIVE_USER, SessionType.HEADLESS, SessionType.SESSION_0]

    hw = detect_hardware()
    assert hw.cpu_cores >= 1
    assert hw.memory_bytes > 0

    caps = detect_capabilities()
    assert caps.platform == plat
    assert caps.session_type == session
    assert len(caps.drivers) >= 1


@pytest.mark.asyncio
async def test_worker_agent_enrollment():
    """Verify WorkerAgent enrollment flow via control plane transport."""
    authority = WorkerEnrollmentAuthority()
    prov_token, _ = authority.create_enrollment_token(tenant_id="tenant-prod")

    transport = InMemoryControlPlaneTransport(enrollment_authority=authority)
    config = WorkerAgentConfig(
        hostname="node-worker-01",
        tenant_id="tenant-prod",
        provisioning_token=prov_token,
    )
    agent = WorkerAgent(config=config, transport=transport)

    assert agent.worker_id is None
    assert agent.auth_token is None

    response = await agent.enroll()
    assert response.worker_id.startswith("worker_")
    assert agent.worker_id == response.worker_id
    assert agent.auth_token == response.auth_token
    assert agent.status == WorkerStatus.IDLE


@pytest.mark.asyncio
async def test_worker_heartbeat_emission():
    """Verify periodic heartbeat telemetry emission."""
    transport = InMemoryControlPlaneTransport()
    config = WorkerAgentConfig(
        worker_id="wrk_test_123",
        tenant_id="tenant-alpha",
    )
    agent = WorkerAgent(config=config, transport=transport)

    success = await agent.send_heartbeat()
    assert success is True
    assert len(transport.heartbeats) == 1

    hb = transport.heartbeats[0]
    assert hb.worker_id == "wrk_test_123"
    assert hb.tenant_id == "tenant-alpha"
    assert hb.status == WorkerStatus.IDLE
    assert hb.sequence_number == 1
    assert hb.cpu_percent >= 0.0


@pytest.mark.asyncio
async def test_driver_execution_success():
    """Verify successful task execution via registered local ComputerDriver."""
    transport = InMemoryControlPlaneTransport()
    config = WorkerAgentConfig(
        worker_id="wrk_exec_01",
        tenant_id="default",
    )
    agent = WorkerAgent(config=config, transport=transport)

    mock_driver = MockTestDriver(name="custom_browser")
    agent.register_driver("custom_browser", mock_driver)

    assignment = AssignmentPayload(
        assignment_id="asgn_001",
        task_id="task_100",
        worker_id="wrk_exec_01",
        lease_id="lease_001",
        generation=1,
        objective="Navigate to dashboard and click export",
        required_capabilities=["custom_browser"],
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        parameters={"driver": "custom_browser", "target": "http://atlas.local/dashboard"},
    )

    result = await agent.execute_assignment(assignment)

    assert result.status == AssignmentStatus.COMPLETED
    assert result.error is None
    assert result.deliverables["action_result"]["result"] == "Executed action on custom_browser"
    assert result.verification_evidence["verified"] is True
    assert len(mock_driver.executed_actions) == 1
    assert agent.status == WorkerStatus.IDLE
    assert len(transport.completed_assignments) == 1


@pytest.mark.asyncio
async def test_driver_execution_failure():
    """Verify driver failure handling returning failed status and structured error."""
    transport = InMemoryControlPlaneTransport()
    config = WorkerAgentConfig(worker_id="wrk_fail_01")
    agent = WorkerAgent(config=config, transport=transport)

    failing_driver = MockTestDriver(name="faulty_driver", fail_execution=True)
    agent.register_driver("faulty_driver", failing_driver)

    assignment = AssignmentPayload(
        assignment_id="asgn_err_01",
        task_id="task_err_100",
        worker_id="wrk_fail_01",
        lease_id="lease_err_001",
        generation=1,
        objective="Execute risky operation",
        required_capabilities=["faulty_driver"],
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        parameters={"driver": "faulty_driver"},
    )

    result = await agent.execute_assignment(assignment)
    assert result.status == AssignmentStatus.FAILED
    assert "Simulated driver execution error" in (result.error or "")
    assert result.verification_evidence["verified"] is False


@pytest.mark.asyncio
async def test_session_zero_interactive_rejection():
    """Verify Windows Session 0 worker strictly rejects interactive desktop tasks."""
    transport = InMemoryControlPlaneTransport()
    caps = WorkerCapabilities(
        platform=WorkerPlatform.WINDOWS,
        session_type=SessionType.SESSION_0,
        drivers=["cmd"],
    )
    config = WorkerAgentConfig(
        worker_id="wrk_srv_0",
        capabilities=caps,
    )
    agent = WorkerAgent(config=config, transport=transport)

    interactive_assignment = AssignmentPayload(
        assignment_id="asgn_gui_01",
        task_id="task_gui_100",
        worker_id="wrk_srv_0",
        lease_id="lease_gui_01",
        generation=1,
        objective="Click login button on desktop",
        action_type="desktop_automation",
        required_capabilities=["desktop"],
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    with pytest.raises(SessionZeroInteractiveError) as exc_info:
        await agent.execute_assignment(interactive_assignment)

    assert "Session 0 Invariant Violation" in str(exc_info.value)
    assert agent.status == WorkerStatus.IDLE


@pytest.mark.asyncio
async def test_assignment_cancellation():
    """Verify cancellation directive cancels active assignment cleanly."""
    transport = InMemoryControlPlaneTransport()
    config = WorkerAgentConfig(worker_id="wrk_cancel_01")
    agent = WorkerAgent(config=config, transport=transport)

    assignment = AssignmentPayload(
        assignment_id="asgn_cancel_01",
        task_id="task_cancel_100",
        worker_id="wrk_cancel_01",
        lease_id="lease_cancel_01",
        generation=1,
        objective="Long running data processing",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    # Cancel prior to execution trigger
    agent.cancel_assignment("asgn_cancel_01", reason="User requested abort")
    result = await agent.execute_assignment(assignment)

    assert result.status == AssignmentStatus.CANCELLED
    assert "cancelled" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_disconnect_ring_buffer_and_replay():
    """Verify ring buffer stores unacknowledged events during partition and flushes on reconnect."""
    transport = InMemoryControlPlaneTransport()
    config = WorkerAgentConfig(
        worker_id="wrk_buff_01",
        buffer_capacity=50,
    )
    agent = WorkerAgent(config=config, transport=transport)

    # Simulate network partition
    transport.should_fail_network = True

    assignment = AssignmentPayload(
        assignment_id="asgn_net_01",
        task_id="task_net_100",
        worker_id="wrk_buff_01",
        lease_id="lease_net_01",
        generation=1,
        objective="Perform batch operations under network partition",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    result = await agent.execute_assignment(assignment)
    assert result.status == AssignmentStatus.COMPLETED
    assert agent.connected is False

    # Check that events were buffered
    unacked = agent.buffer.get_unacknowledged()
    assert len(unacked) >= 1  # Contains at least the completion result

    # Network heals
    transport.should_fail_network = False

    # Reconnect triggered via heartbeat
    heartbeat_ok = await agent.send_heartbeat()
    assert heartbeat_ok is True
    assert agent.connected is True

    # Buffered completion must now be delivered to transport
    assert len(transport.completed_assignments) == 1
    assert transport.completed_assignments[0].assignment_id == "asgn_net_01"
    assert len(agent.buffer.get_unacknowledged()) == 0


def test_event_ring_buffer_capacity():
    """Verify ring buffer bounds and maxlen eviction."""
    buffer = EventRingBuffer(capacity=5)
    for i in range(10):
        buffer.append(
            "test",
            AssignmentPayload(
                assignment_id=f"asgn_{i}",
                task_id="t1",
                worker_id="w1",
                lease_id="l1",
                objective="test",
                expires_at=datetime.now(UTC),
            ),
        )

    assert len(buffer) == 5
    unacked = buffer.get_unacknowledged()
    assert len(unacked) == 5
    assert unacked[0]["payload"].assignment_id == "asgn_5"
