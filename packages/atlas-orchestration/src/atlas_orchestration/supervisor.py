"""AgentSupervisor providing hierarchical task decomposition, parallel dispatch, and lifecycle ownership."""

import asyncio
import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from atlas_core.contracts.agent import AgentCapability
from atlas_core.contracts.graph import (
    DependencyType,
    NodeStatus,
    TaskGraph,
    TaskNode,
)
from atlas_core.contracts.message import AgentMessage, AgentMessageType

from atlas_orchestration.graph_engine import TaskGraphEngine
from atlas_orchestration.memory import SharedMemoryEngine
from atlas_orchestration.messaging import AgentMessageRouter
from atlas_orchestration.recovery import MultiAgentRecoveryManager
from atlas_orchestration.registry import (
    AgentRegistry,
    AgentUnavailableError,
)
from atlas_orchestration.reviewer import IndependentReviewer, ReviewVerdict
from atlas_orchestration.specialist import SpecialistAgent

logger = logging.getLogger("atlas.orchestration.supervisor")


class OrchestrationError(Exception):
    """Raised when an error occurs during multi-agent task execution."""


class ReviewRejectionError(Exception):
    """Raised when the IndependentReviewer rejects the task deliverables."""


class AgentSupervisor:
    """Central orchestrator managing multi-agent task decomposition, parallel execution, and QA gates."""

    def __init__(
        self,
        registry: AgentRegistry,
        memory: SharedMemoryEngine,
        router: AgentMessageRouter,
        reviewer: IndependentReviewer | None = None,
        recovery_manager: MultiAgentRecoveryManager | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.registry = registry
        self.memory = memory
        self.router = router
        self.reviewer = reviewer or IndependentReviewer(memory)
        self.recovery_manager = recovery_manager or MultiAgentRecoveryManager(registry)
        self._specialists: dict[str, SpecialistAgent] = {}
        self._active_graphs: dict[str, TaskGraphEngine] = {}

    def register_specialist(self, specialist: SpecialistAgent) -> None:
        """Register a specialist agent instance for subtask execution."""
        with self._lock:
            self._specialists[specialist.descriptor.agent_id] = specialist
            self.registry.register_agent(specialist.descriptor)

    def decompose_task(
        self,
        task_id: str,
        objective: str,
        parameters: dict[str, Any] | None = None,
    ) -> TaskGraph:
        """Decompose a high-level task objective into a multi-stage execution DAG."""
        params = parameters or {}
        now = datetime.now(UTC)
        graph_id = f"graph_{uuid.uuid4().hex[:10]}"

        # Standard 3-stage hierarchical decomposition: Research -> Action/Code -> QA
        n1 = TaskNode(
            node_id=f"node_res_{task_id}",
            task_id=task_id,
            name=f"Research requirements for {objective}",
            required_capability=AgentCapability.RESEARCH,
            parameters={"query": objective, **params},
            status=NodeStatus.PENDING,
            dependency_type=DependencyType.HARD,
        )

        n2 = TaskNode(
            node_id=f"node_exec_{task_id}",
            task_id=task_id,
            name=f"Implement deliverables for {objective}",
            required_capability=AgentCapability.CODE,
            parameters={"objective": objective, **params},
            dependencies=[n1.node_id],
            status=NodeStatus.PENDING,
            dependency_type=DependencyType.HARD,
        )

        n3 = TaskNode(
            node_id=f"node_qa_{task_id}",
            task_id=task_id,
            name=f"Verify deliverables for {objective}",
            required_capability=AgentCapability.QUALITY_ASSURANCE,
            parameters={"target": objective, **params},
            dependencies=[n2.node_id],
            status=NodeStatus.PENDING,
            dependency_type=DependencyType.HARD,
        )

        graph = TaskGraph(
            graph_id=graph_id,
            task_id=task_id,
            version=1,
            nodes={n1.node_id: n1, n2.node_id: n2, n3.node_id: n3},
            created_at=now,
            updated_at=now,
        )
        return graph

    async def execute_graph(
        self,
        graph: TaskGraph,
        max_parallel: int = 4,
        enforce_review: bool = True,
        required_outputs: list[str] | None = None,
    ) -> TaskGraph:
        """Orchestrate DAG execution by dispatching ready nodes in parallel to leased specialists."""
        engine = TaskGraphEngine(graph)
        self._active_graphs[graph.task_id] = engine

        while not graph.is_complete():
            ready_nodes = engine.get_ready_nodes()

            if not ready_nodes:
                # Check if there are active running nodes
                running_nodes = [n for n in graph.nodes.values() if n.status == NodeStatus.RUNNING]
                if running_nodes:
                    await asyncio.sleep(0.05)
                    continue

                # Deadlock or hard failure
                if graph.has_failures():
                    break
                else:
                    raise OrchestrationError(
                        f"Task graph '{graph.graph_id}' is stuck with no ready or running nodes."
                    )

            # Limit concurrent execution by max_parallel
            batch = ready_nodes[:max_parallel]

            async def _run_node(node: TaskNode) -> None:
                # 1. Discover available specialist
                agent_desc = self.registry.find_available_agent(
                    required_capabilities=[node.required_capability]
                )
                if not agent_desc:
                    raise AgentUnavailableError(
                        f"No available agent with capability '{node.required_capability.value}' for node '{node.node_id}'."
                    )

                # 2. Acquire lease
                lease = self.registry.acquire_agent_lease(
                    agent_id=agent_desc.agent_id,
                    task_id=node.task_id,
                    node_id=node.node_id,
                    ttl_seconds=60.0,
                )
                self.router.register_agent_task(agent_desc.agent_id, node.task_id)
                engine.mark_running(node.node_id, agent_id=agent_desc.agent_id)

                try:
                    specialist = self._specialists.get(agent_desc.agent_id)
                    if not specialist:
                        raise OrchestrationError(
                            f"Specialist instance for agent '{agent_desc.agent_id}' is not loaded."
                        )

                    # Send task assignment message
                    self.router.route_message(
                        AgentMessage(
                            sender_id="supervisor",
                            recipient_id=agent_desc.agent_id,
                            task_id=node.task_id,
                            correlation_id=node.node_id,
                            message_type=AgentMessageType.TASK_ASSIGNMENT,
                            payload={"node_id": node.node_id, "parameters": node.parameters},
                        )
                    )

                    # Execute subtask
                    output = await specialist.execute_subtask(node)
                    engine.mark_completed(node.node_id, output=output)

                    # Send task result message
                    self.router.route_message(
                        AgentMessage(
                            sender_id=agent_desc.agent_id,
                            recipient_id="supervisor",
                            task_id=node.task_id,
                            correlation_id=node.node_id,
                            message_type=AgentMessageType.TASK_RESULT,
                            payload={"node_id": node.node_id, "output": output},
                        )
                    )
                except Exception as exc:
                    logger.error("Node '%s' execution failed: %s", node.node_id, exc)
                    engine.mark_failed(node.node_id, error=str(exc))
                finally:
                    self.registry.release_agent_lease(lease.lease_id)
                    self.router.unregister_agent_task(agent_desc.agent_id)

            # Dispatch batch concurrently
            await asyncio.gather(*[_run_node(n) for n in batch])

        # 3. Independent QA Review Gate
        if enforce_review and not graph.has_failures():
            review = self.reviewer.evaluate_task_graph(graph, required_outputs=required_outputs)
            if review.verdict == ReviewVerdict.REJECTED:
                raise ReviewRejectionError(review.feedback)

        return graph

    def get_task_graph(self, task_id: str) -> TaskGraph | None:
        """Retrieve active or completed task graph by task ID."""
        with self._lock:
            engine = self._active_graphs.get(task_id)
            return engine.graph if engine else None

    def cancel_task(self, task_id: str, reason: str = "Cancelled by supervisor") -> None:
        """Propagate cancellation across all active agents and subtask nodes."""
        with self._lock:
            engine = self._active_graphs.get(task_id)
            if engine:
                for node in engine.graph.nodes.values():
                    if not node.is_terminal():
                        node.status = NodeStatus.CANCELLED
                        node.error = reason
                        node.completed_at = datetime.now(UTC)

            # Broadcast cancellation notices to all registered agents
            for agent in self.registry.list_agents():
                try:
                    self.router.route_message(
                        AgentMessage(
                            sender_id="supervisor",
                            recipient_id=agent.agent_id,
                            task_id=task_id,
                            correlation_id="cancel_broadcast",
                            message_type=AgentMessageType.CANCEL_NOTICE,
                            payload={"reason": reason},
                        )
                    )
                except Exception:
                    pass
