"""Unit tests verifying AgentSupervisor, IndependentReviewer, and MultiAgentRecoveryManager."""

from datetime import UTC, datetime, timedelta

import pytest
from atlas_coordination.action_ledger import NonIdempotentActionUncertaintyError
from atlas_core.contracts.agent import (
    AgentCapability,
    AgentDescriptor,
    AgentLease,
    AgentStatus,
)
from atlas_core.contracts.graph import (
    NodeStatus,
    TaskGraph,
    TaskNode,
)
from atlas_core.contracts.message import AgentMessageType
from atlas_orchestration.graph_engine import TaskGraphEngine
from atlas_orchestration.memory import SharedMemoryEngine
from atlas_orchestration.messaging import AgentMessageRouter
from atlas_orchestration.recovery import MultiAgentRecoveryManager
from atlas_orchestration.registry import AgentRegistry
from atlas_orchestration.reviewer import (
    IndependentReviewer,
    ReviewVerdict,
)
from atlas_orchestration.specialist import (
    CodingSpecialist,
    DataAnalysisSpecialist,
    QASpecialist,
    ResearchSpecialist,
)
from atlas_orchestration.supervisor import (
    AgentSupervisor,
    ReviewRejectionError,
)


@pytest.fixture
def test_env():
    """Create a fully wired supervisor test environment."""
    registry = AgentRegistry()
    memory = SharedMemoryEngine()
    router = AgentMessageRouter()
    reviewer = IndependentReviewer(memory)
    recovery = MultiAgentRecoveryManager(registry)
    supervisor = AgentSupervisor(
        registry=registry,
        memory=memory,
        router=router,
        reviewer=reviewer,
        recovery_manager=recovery,
    )

    # Register specialists
    res_agent = ResearchSpecialist(
        AgentDescriptor(
            agent_id="agent_res_1",
            name="Research Agent",
            role="Researcher",
            capabilities=[AgentCapability.RESEARCH],
        ),
        memory=memory,
    )
    code_agent = CodingSpecialist(
        AgentDescriptor(
            agent_id="agent_code_1",
            name="Coding Agent",
            role="Coder",
            capabilities=[AgentCapability.CODE],
        ),
        memory=memory,
    )
    qa_agent = QASpecialist(
        AgentDescriptor(
            agent_id="agent_qa_1",
            name="QA Agent",
            role="Tester",
            capabilities=[AgentCapability.QUALITY_ASSURANCE],
        ),
        memory=memory,
    )
    data_agent = DataAnalysisSpecialist(
        AgentDescriptor(
            agent_id="agent_data_1",
            name="Data Agent",
            role="Analyst",
            capabilities=[AgentCapability.DATA_ANALYSIS],
        ),
        memory=memory,
    )

    for spec in [res_agent, code_agent, qa_agent, data_agent]:
        supervisor.register_specialist(spec)

    return {
        "supervisor": supervisor,
        "registry": registry,
        "memory": memory,
        "router": router,
        "reviewer": reviewer,
        "recovery": recovery,
    }


def test_supervisor_task_decomposition(test_env):
    """Verify AgentSupervisor decomposes task into 3-stage hierarchical DAG."""
    supervisor: AgentSupervisor = test_env["supervisor"]
    graph = supervisor.decompose_task("task_decomp_1", "Build Raft Engine")

    assert len(graph.nodes) == 3
    nodes = list(graph.nodes.values())

    n_res = nodes[0]
    n_code = nodes[1]
    n_qa = nodes[2]

    assert n_res.required_capability == AgentCapability.RESEARCH
    assert n_code.required_capability == AgentCapability.CODE
    assert n_qa.required_capability == AgentCapability.QUALITY_ASSURANCE

    assert n_res.node_id in n_code.dependencies
    assert n_code.node_id in n_qa.dependencies


@pytest.mark.asyncio
async def test_supervisor_end_to_end_graph_execution(test_env):
    """Verify supervisor executes multi-stage DAG with specialist dispatch and review approval."""
    supervisor: AgentSupervisor = test_env["supervisor"]
    router: AgentMessageRouter = test_env["router"]

    graph = supervisor.decompose_task("task_e2e_1", "Build Consensus Module")
    result_graph = await supervisor.execute_graph(graph, max_parallel=2, enforce_review=True)

    assert result_graph.is_complete()
    assert not result_graph.has_failures()
    for node in result_graph.nodes.values():
        assert node.status == NodeStatus.COMPLETED
        assert node.output is not None

    # Verify messages were delivered to supervisor inbox
    supervisor_msgs = router.get_inbox("supervisor")
    assert len(supervisor_msgs) == 3  # 3 subtask results
    for msg in supervisor_msgs:
        assert msg.message_type == AgentMessageType.TASK_RESULT


@pytest.mark.asyncio
async def test_supervisor_parallel_branch_execution(test_env):
    """Verify supervisor executes independent parallel branches concurrently."""
    supervisor: AgentSupervisor = test_env["supervisor"]
    now = datetime.now(UTC)

    # DAG: Root Research -> [Branch A: Data Analysis, Branch B: Coding] -> Join QA
    n_root = TaskNode(
        node_id="n_root",
        task_id="task_parallel_1",
        name="Root Research",
        required_capability=AgentCapability.RESEARCH,
        parameters={"query": "System telemetry"},
        status=NodeStatus.PENDING,
    )
    n_branch_a = TaskNode(
        node_id="n_branch_a",
        task_id="task_parallel_1",
        name="Branch A: Data",
        required_capability=AgentCapability.DATA_ANALYSIS,
        parameters={"dataset": [10.0, 20.0, 30.0]},
        dependencies=["n_root"],
        status=NodeStatus.PENDING,
    )
    n_branch_b = TaskNode(
        node_id="n_branch_b",
        task_id="task_parallel_1",
        name="Branch B: Code",
        required_capability=AgentCapability.CODE,
        parameters={"filepath": "out.py", "content": "# branch b"},
        dependencies=["n_root"],
        status=NodeStatus.PENDING,
    )
    n_join = TaskNode(
        node_id="n_join",
        task_id="task_parallel_1",
        name="Join QA",
        required_capability=AgentCapability.QUALITY_ASSURANCE,
        parameters={"component": "system"},
        dependencies=["n_branch_a", "n_branch_b"],
        status=NodeStatus.PENDING,
    )

    graph = TaskGraph(
        graph_id="graph_parallel_1",
        task_id="task_parallel_1",
        version=1,
        nodes={
            n_root.node_id: n_root,
            n_branch_a.node_id: n_branch_a,
            n_branch_b.node_id: n_branch_b,
            n_join.node_id: n_join,
        },
        created_at=now,
        updated_at=now,
    )

    completed_graph = await supervisor.execute_graph(graph, max_parallel=4, enforce_review=True)
    assert completed_graph.is_complete()
    assert not completed_graph.has_failures()
    assert completed_graph.nodes["n_branch_a"].status == NodeStatus.COMPLETED
    assert completed_graph.nodes["n_branch_b"].status == NodeStatus.COMPLETED
    assert completed_graph.nodes["n_join"].status == NodeStatus.COMPLETED


@pytest.mark.asyncio
async def test_independent_reviewer_rejection(test_env):
    """Verify IndependentReviewer and supervisor reject deliverables when criteria are missing."""
    supervisor: AgentSupervisor = test_env["supervisor"]
    reviewer: IndependentReviewer = test_env["reviewer"]
    now = datetime.now(UTC)

    n1 = TaskNode(
        node_id="n1",
        task_id="task_review_fail",
        name="Incomplete Node",
        required_capability=AgentCapability.RESEARCH,
        status=NodeStatus.COMPLETED,
        output=None,  # Missing output artifacts!
    )
    graph = TaskGraph(
        graph_id="g_fail",
        task_id="task_review_fail",
        version=1,
        nodes={n1.node_id: n1},
        created_at=now,
        updated_at=now,
    )

    # 1. Reviewer direct check
    review = reviewer.evaluate_task_graph(graph)
    assert review.verdict == ReviewVerdict.REJECTED
    assert "without producing output" in review.feedback

    # 2. Output key missing check
    n1.output = {"summary": "done"}
    review_missing_key = reviewer.evaluate_task_graph(
        graph, required_outputs=["final_deliverable_spec"]
    )
    assert review_missing_key.verdict == ReviewVerdict.REJECTED
    assert "final_deliverable_spec" in review_missing_key.feedback

    # 3. Supervisor execution gate check
    with pytest.raises(ReviewRejectionError):
        await supervisor.execute_graph(
            graph, enforce_review=True, required_outputs=["final_deliverable_spec"]
        )


def test_supervisor_cancellation_propagation(test_env):
    """Verify supervisor propagates cancellation across all subtask nodes and active agents."""
    supervisor: AgentSupervisor = test_env["supervisor"]
    router: AgentMessageRouter = test_env["router"]

    graph = supervisor.decompose_task("task_cancel_1", "Test Cancellation")
    engine = TaskGraphEngine(graph)
    supervisor._active_graphs[graph.task_id] = engine

    supervisor.cancel_task("task_cancel_1", reason="Operator aborted task")

    for node in graph.nodes.values():
        assert node.status == NodeStatus.CANCELLED
        assert "Operator aborted" in node.error

    # Verify cancel message routed to registered agents
    for agent_id in ["agent_res_1", "agent_code_1", "agent_qa_1"]:
        inbox = router.get_inbox(agent_id)
        assert any(
            m.message_type == AgentMessageType.CANCEL_NOTICE and m.task_id == "task_cancel_1"
            for m in inbox
        )


def test_recovery_manager_lease_eviction_and_reassignment(test_env):
    """Verify recovery manager detects expired leases and reassigns interrupted subtasks."""
    recovery: MultiAgentRecoveryManager = test_env["recovery"]
    registry: AgentRegistry = test_env["registry"]
    now = datetime.now(UTC)

    # 1. Register a spare research agent
    spare_desc = AgentDescriptor(
        agent_id="agent_res_spare",
        name="Spare Researcher",
        role="Researcher",
        capabilities=[AgentCapability.RESEARCH],
    )
    registry.register_agent(spare_desc)

    # 2. Create an expired lease for agent_res_1
    expired_lease = AgentLease(
        lease_id="lease_expired_1",
        agent_id="agent_res_1",
        task_id="task_recov_1",
        node_id="node_recov_1",
        fence_token=1,
        acquired_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=5),
    )
    registry._leases[expired_lease.lease_id] = expired_lease
    agent_res_1 = registry.get_agent("agent_res_1")
    agent_res_1.status = AgentStatus.BUSY

    # Evict expired leases
    evicted = recovery.check_and_evict_expired_leases()
    assert len(evicted) == 1
    assert evicted[0].lease_id == "lease_expired_1"
    assert agent_res_1.status == AgentStatus.UNHEALTHY
    assert "lease_expired_1" not in registry._leases

    # 3. Reassign interrupted node to available healthy agent (agent_res_spare)
    node = TaskNode(
        node_id="node_recov_1",
        task_id="task_recov_1",
        name="Interrupted Task",
        required_capability=AgentCapability.RESEARCH,
        status=NodeStatus.RUNNING,
    )
    graph = TaskGraph(
        graph_id="g_recov",
        task_id="task_recov_1",
        version=1,
        nodes={node.node_id: node},
        created_at=now,
        updated_at=now,
    )
    engine = TaskGraphEngine(graph)

    replacement, new_lease = recovery.reassign_subtask("node_recov_1", engine)
    assert replacement.agent_id == "agent_res_spare"
    assert new_lease.agent_id == "agent_res_spare"
    assert node.status == NodeStatus.READY
    assert node.assigned_agent_id == "agent_res_spare"


def test_recovery_non_idempotent_action_reconciliation(test_env):
    """Verify non-idempotent actions in unknown state cannot be retried without reconciliation."""
    recovery: MultiAgentRecoveryManager = test_env["recovery"]

    # 1. Non-idempotent action without operator confirmation raises uncertainty error
    with pytest.raises(NonIdempotentActionUncertaintyError):
        recovery.reconcile_action_outcome(
            task_id="task_pay_1",
            action_id="act_charge_1",
            idempotency_key="pay_tok_123",
            is_idempotent=False,
            operator_confirmed_executed=None,
        )

    # 2. Operator confirmed already executed -> do not re-execute (returns False)
    should_execute = recovery.reconcile_action_outcome(
        task_id="task_pay_1",
        action_id="act_charge_1",
        idempotency_key="pay_tok_123",
        is_idempotent=False,
        operator_confirmed_executed=True,
    )
    assert should_execute is False

    # 3. Operator confirmed not executed -> safe to execute (returns True)
    should_execute_not_done = recovery.reconcile_action_outcome(
        task_id="task_pay_1",
        action_id="act_charge_1",
        idempotency_key="pay_tok_123",
        is_idempotent=False,
        operator_confirmed_executed=False,
    )
    assert should_execute_not_done is True

    # 4. Idempotent action is always safe to execute
    assert (
        recovery.reconcile_action_outcome(
            task_id="task_read_1",
            action_id="act_read_1",
            idempotency_key="read_tok_123",
            is_idempotent=True,
            operator_confirmed_executed=None,
        )
        is True
    )
