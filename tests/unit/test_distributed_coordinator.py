"""Unit tests for DistributedTaskCoordinator (Milestone 4)."""

import pytest
from atlas_core.contracts.action import ActionResult, ComputerAction
from atlas_core.contracts.agent import AgentCapability
from atlas_core.contracts.graph import DependencyType, NodeStatus, TaskGraph, TaskNode
from atlas_core.runtime.driver import ComputerDriver, DriverHealth
from atlas_distributed.coordinator import DistributedTaskCoordinator
from atlas_distributed.enrollment import WorkerEnrollmentAuthority
from atlas_distributed.models import (
    EnrollmentRequest,
    SessionType,
    WorkerCapabilities,
    WorkerHardware,
    WorkerPlatform,
)
from atlas_distributed.scheduler import DistributedScheduler
from atlas_distributed.worker import (
    InMemoryControlPlaneTransport,
    WorkerAgent,
    WorkerAgentConfig,
)


class MockDriver(ComputerDriver):
    """Mock ComputerDriver for coordinator tests."""

    def __init__(self, name: str, should_fail: bool = False):
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
                action_id="act_err",
                success=False,
                duration_ms=10,
                error="Simulated failure in driver",
            )
        return ActionResult(
            action_id="act_ok",
            success=True,
            duration_ms=20,
            output={"result": f"Executed on {self.name}", "action": action.action_type},
            evidence={"executed": True},
        )

    async def health_check(self) -> DriverHealth:
        return DriverHealth(driver_type=self.name, connected=True)

    async def disconnect(self) -> None:
        pass


@pytest.fixture
def authority() -> WorkerEnrollmentAuthority:
    return WorkerEnrollmentAuthority()


def enroll_worker(
    authority: WorkerEnrollmentAuthority,
    tenant_id: str = "default",
    platform: WorkerPlatform = WorkerPlatform.LINUX,
    session_type: SessionType = SessionType.HEADLESS,
    drivers: list[str] | None = None,
):
    token, _ = authority.create_enrollment_token(tenant_id=tenant_id)
    caps = WorkerCapabilities(
        platform=platform,
        session_type=session_type,
        drivers=drivers or ["bash", "playwright"],
        hardware=WorkerHardware(cpu_cores=4, memory_bytes=8 * 1024 * 1024 * 1024),
        max_concurrent_tasks=4,
    )
    req = EnrollmentRequest(
        provisioning_token=token,
        hostname=f"node-{platform.value}",
        capabilities=caps,
        tenant_id=tenant_id,
    )
    return authority.enroll_worker(req)


@pytest.mark.asyncio
async def test_multi_worker_dag_parallel_and_synchronization_barrier(authority):
    """Verify execution of a 3-stage DAG with parallel branches and synchronization barriers."""
    # Worker 1: Linux data node
    enroll_worker(
        authority,
        platform=WorkerPlatform.LINUX,
        drivers=["bash", "python_eval"],
    )
    # Worker 2: Windows desktop node
    enroll_worker(
        authority,
        platform=WorkerPlatform.WINDOWS,
        session_type=SessionType.INTERACTIVE_USER,
        drivers=["cmd", "desktop"],
    )

    scheduler = DistributedScheduler(enrollment_authority=authority)
    coordinator = DistributedTaskCoordinator(scheduler=scheduler)

    # Build 3-stage DAG
    # Node 1: Fetch data (Linux)
    # Node 2a: Process data (Linux) [parallel with 2b]
    # Node 2b: Setup desktop display (Windows) [parallel with 2a]
    # Node 3: Aggregate (barrier on 2a and 2b)
    n1 = TaskNode(
        node_id="node_fetch",
        task_id="task_pipeline_01",
        name="Fetch dataset",
        required_capability=AgentCapability.RESEARCH,
        parameters={"required_platform": WorkerPlatform.LINUX, "required_drivers": ["bash"]},
        dependencies=[],
    )
    n2a = TaskNode(
        node_id="node_process",
        task_id="task_pipeline_01",
        name="Process dataset",
        required_capability=AgentCapability.CODE,
        parameters={"required_platform": WorkerPlatform.LINUX, "required_drivers": ["bash"]},
        dependencies=["node_fetch"],
    )
    n2b = TaskNode(
        node_id="node_gui",
        task_id="task_pipeline_01",
        name="Open GUI Dashboard",
        required_capability=AgentCapability.DESKTOP,
        parameters={
            "required_platform": WorkerPlatform.WINDOWS,
            "requires_interactive_desktop": True,
            "required_drivers": ["desktop"],
        },
        dependencies=["node_fetch"],
    )
    n3 = TaskNode(
        node_id="node_aggregate",
        task_id="task_pipeline_01",
        name="Aggregate results",
        required_capability=AgentCapability.GENERAL,
        parameters={},
        dependencies=["node_process", "node_gui"],
    )

    graph = TaskGraph(
        graph_id="graph_001",
        task_id="task_pipeline_01",
        nodes={
            "node_fetch": n1,
            "node_process": n2a,
            "node_gui": n2b,
            "node_aggregate": n3,
        },
    )

    summary = await coordinator.execute_task_graph(graph)

    assert summary.status == "COMPLETED"
    assert summary.error is None
    assert len(summary.node_results) == 4
    assert n1.status == NodeStatus.COMPLETED
    assert n2a.status == NodeStatus.COMPLETED
    assert n2b.status == NodeStatus.COMPLETED
    assert n3.status == NodeStatus.COMPLETED
    assert "node_fetch" in summary.deliverables
    assert "node_process" in summary.deliverables
    assert "node_gui" in summary.deliverables
    assert "node_aggregate" in summary.deliverables


@pytest.mark.asyncio
async def test_dependency_failure_blocks_downstream_hard_nodes(authority):
    """Verify failing upstream hard dependency blocks downstream nodes and marks DAG failed."""
    resp = enroll_worker(authority, platform=WorkerPlatform.LINUX, drivers=["failing_driver"])
    scheduler = DistributedScheduler(enrollment_authority=authority)
    coordinator = DistributedTaskCoordinator(scheduler=scheduler)

    # Attach worker agent with a failing driver
    transport = InMemoryControlPlaneTransport()
    config = WorkerAgentConfig(worker_id=resp.worker_id)
    agent = WorkerAgent(config=config, transport=transport)
    agent.register_driver("failing_driver", MockDriver("failing_driver", should_fail=True))
    coordinator.register_worker_agent(agent)

    n1 = TaskNode(
        node_id="node_root",
        task_id="task_fail_01",
        name="Root failure node",
        parameters={"required_drivers": ["failing_driver"]},
        dependencies=[],
        dependency_type=DependencyType.HARD,
    )
    n2 = TaskNode(
        node_id="node_child",
        task_id="task_fail_01",
        name="Child dependent node",
        dependencies=["node_root"],
        dependency_type=DependencyType.HARD,
    )

    graph = TaskGraph(
        graph_id="graph_fail_01",
        task_id="task_fail_01",
        nodes={"node_root": n1, "node_child": n2},
    )

    summary = await coordinator.execute_task_graph(graph)

    assert summary.status == "FAILED"
    assert "node_root" in summary.error or "node_child" in summary.error
    assert n1.status == NodeStatus.FAILED
    assert n2.status == NodeStatus.FAILED
    assert "Upstream hard dependency" in (n2.error or "")


@pytest.mark.asyncio
async def test_coordinator_with_live_worker_agent_execution(authority):
    """Verify end-to-end integration between coordinator, scheduler, and real WorkerAgent."""
    resp = enroll_worker(authority, platform=WorkerPlatform.LINUX, drivers=["custom_tool"])
    scheduler = DistributedScheduler(enrollment_authority=authority)
    coordinator = DistributedTaskCoordinator(scheduler=scheduler)

    transport = InMemoryControlPlaneTransport()
    agent = WorkerAgent(config=WorkerAgentConfig(worker_id=resp.worker_id), transport=transport)
    mock_driver = MockDriver("custom_tool")
    agent.register_driver("custom_tool", mock_driver)
    coordinator.register_worker_agent(agent)

    node = TaskNode(
        node_id="node_live",
        task_id="task_live_01",
        name="Execute custom tool",
        parameters={"required_drivers": ["custom_tool"], "action_type": "custom_operation"},
    )

    result = await coordinator.execute_node(node)
    assert result.status == "COMPLETED"
    assert len(mock_driver.executed_actions) == 1
    assert mock_driver.executed_actions[0].action_type == "custom_operation"
