"""CodingTeamSupervisor orchestrating specialist engineering agents with conflict-aware parallel scheduling."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas_core.contracts.agent import AgentCapability
from atlas_core.contracts.coding import UnifiedDiff
from atlas_core.contracts.graph import (
    DependencyType,
    NodeStatus,
    TaskGraph,
    TaskNode,
)
from atlas_policy.firewall import ActionFirewall

from atlas_orchestration.coding_team.code_reviewer import (
    IndependentCodeReviewer,
)
from atlas_orchestration.coding_team.conflict_detector import ConflictManager
from atlas_orchestration.coding_team.shared_context import (
    CodingSharedContext,
    TrustLevel,
)
from atlas_orchestration.coding_team.specialists import (
    create_specialist_roster,
)
from atlas_orchestration.coding_team.workspace_isolation import (
    WorkspaceIsolationManager,
)
from atlas_orchestration.graph_engine import TaskGraphEngine
from atlas_orchestration.memory import SharedMemoryEngine
from atlas_orchestration.messaging import AgentMessageRouter
from atlas_orchestration.registry import AgentRegistry, AgentUnavailableError
from atlas_orchestration.reviewer import ReviewVerdict
from atlas_orchestration.supervisor import (
    AgentSupervisor,
    OrchestrationError,
    ReviewRejectionError,
)

logger = logging.getLogger("atlas.orchestration.coding_team")


class CodingTeamSupervisor(AgentSupervisor):
    """Authoritative supervisor coordinating specialist engineering agents, conflict resolution, and QA review."""

    def __init__(
        self,
        repo_root: str | Path | None = None,
        firewall: ActionFirewall | None = None,
        registry: AgentRegistry | None = None,
        memory: SharedMemoryEngine | None = None,
        router: AgentMessageRouter | None = None,
        reviewer: IndependentCodeReviewer | None = None,
        isolation_manager: WorkspaceIsolationManager | None = None,
        conflict_manager: ConflictManager | None = None,
        shared_context: CodingSharedContext | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd()
        mem = memory or SharedMemoryEngine()
        reg = registry or AgentRegistry()
        rout = router or AgentMessageRouter(reg)
        rev = reviewer or IndependentCodeReviewer(mem)

        super().__init__(
            registry=reg,
            memory=mem,
            router=rout,
            reviewer=rev,
        )

        self.code_reviewer = rev
        self.firewall = firewall or ActionFirewall()
        self.isolation_manager = isolation_manager or WorkspaceIsolationManager(self.repo_root)
        self.conflict_manager = conflict_manager or ConflictManager()
        self.shared_context = shared_context or CodingSharedContext(mem)
        self._delegation_log: list[dict[str, Any]] = []

        # Auto-register standard 11 specialist roster
        roster = create_specialist_roster(
            memory=self.memory,
            firewall=self.firewall,
            repo_root=str(self.repo_root),
        )
        for specialist in roster.values():
            self.register_specialist(specialist)

    def decompose_engineering_objective(
        self,
        task_id: str,
        objective: str,
        target_files: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> TaskGraph:
        """Decompose a software engineering objective into a dependency-aware multi-agent DAG."""
        params = parameters or {}
        now = datetime.now(UTC)
        graph_id = f"graph_eng_{uuid.uuid4().hex[:8]}"
        files = target_files or ["src/module.py"]

        nodes: dict[str, TaskNode] = {}

        # 1. Architecture Stage (Software Architect)
        n_arch = TaskNode(
            node_id=f"node_arch_{task_id}",
            task_id=task_id,
            name=f"Design architecture for {objective}",
            required_capability=AgentCapability.ARCHITECT,
            parameters={"objective": objective, "constraints": params.get("constraints", [])},
            status=NodeStatus.PENDING,
            dependency_type=DependencyType.HARD,
        )
        nodes[n_arch.node_id] = n_arch

        # 2. Exploration Stage (Repository Explorer)
        n_exp = TaskNode(
            node_id=f"node_exp_{task_id}",
            task_id=task_id,
            name="Explore repository topology and dependencies",
            required_capability=AgentCapability.EXPLORER,
            parameters={"query": objective, "max_files": 30},
            dependencies=[n_arch.node_id],
            status=NodeStatus.PENDING,
            dependency_type=DependencyType.HARD,
        )
        nodes[n_exp.node_id] = n_exp

        # 3. Implementation Stage (Backend / Frontend / Database based on targets)
        impl_nodes: list[TaskNode] = []
        for idx, fpath in enumerate(files):
            cap = AgentCapability.BACKEND
            if fpath.endswith((".tsx", ".jsx", ".html", ".css", ".ts")):
                cap = AgentCapability.FRONTEND
            elif fpath.endswith(".sql") or "migration" in fpath:
                cap = AgentCapability.DATABASE

            nid = f"node_impl_{task_id}_{idx}"
            node = TaskNode(
                node_id=nid,
                task_id=task_id,
                name=f"Implement changes for {fpath}",
                required_capability=cap,
                parameters={
                    "file_path": fpath,
                    "code": f"# Implementation for {objective}\n# File: {fpath}\n",
                },
                dependencies=[n_exp.node_id],
                status=NodeStatus.PENDING,
                dependency_type=DependencyType.HARD,
            )
            nodes[nid] = node
            impl_nodes.append(node)

        # 4. Testing Stage (Testing Engineer)
        test_file = params.get("test_file", "tests/test_deliverable.py")
        n_test = TaskNode(
            node_id=f"node_test_{task_id}",
            task_id=task_id,
            name=f"Implement and verify test suite {test_file}",
            required_capability=AgentCapability.TESTING,
            parameters={
                "test_file": test_file,
                "test_code": "def test_deliverable(): assert True\n",
                "run_suite": params.get("run_suite", False),
            },
            dependencies=[node.node_id for node in impl_nodes],
            status=NodeStatus.PENDING,
            dependency_type=DependencyType.HARD,
        )
        nodes[n_test.node_id] = n_test

        # 5. Security Audit Stage (Security Auditor)
        n_sec = TaskNode(
            node_id=f"node_sec_{task_id}",
            task_id=task_id,
            name="Audit security and Action Firewall policies",
            required_capability=AgentCapability.SECURITY_AUDITOR,
            parameters={"target_files": files + [test_file]},
            dependencies=[n_test.node_id],
            status=NodeStatus.PENDING,
            dependency_type=DependencyType.HARD,
        )
        nodes[n_sec.node_id] = n_sec

        graph = TaskGraph(
            graph_id=graph_id,
            task_id=task_id,
            version=1,
            nodes=nodes,
            created_at=now,
            updated_at=now,
        )

        # Invariant: Detect file write conflicts and serialize overlapping nodes
        self.conflict_manager.serialize_conflicting_nodes(graph)

        return graph

    async def execute_coding_team(
        self,
        graph: TaskGraph,
        max_parallel: int = 4,
        enforce_review: bool = True,
        disallowed_imports: list[str] | None = None,
    ) -> tuple[TaskGraph, Any]:
        """Execute task graph with concurrency control, workspace isolation, and independent review."""
        engine = TaskGraphEngine(graph)
        self._active_graphs[graph.task_id] = engine
        collected_diffs: list[UnifiedDiff] = []

        while not graph.is_complete():
            ready_nodes = engine.get_ready_nodes()

            if not ready_nodes:
                running = [n for n in graph.nodes.values() if n.status == NodeStatus.RUNNING]
                if running:
                    await asyncio.sleep(0.05)
                    continue

                if graph.has_failures():
                    break
                else:
                    raise OrchestrationError(
                        f"Task graph '{graph.graph_id}' reached deadlock with no ready or running nodes."
                    )

            batch = ready_nodes[:max_parallel]

            async def _run_coding_node(node: TaskNode) -> None:
                agent_desc = self.registry.find_available_agent([node.required_capability])
                if not agent_desc:
                    raise AgentUnavailableError(
                        f"No available agent with capability '{node.required_capability.value}' for node '{node.node_id}'."
                    )

                lease = self.registry.acquire_agent_lease(
                    agent_id=agent_desc.agent_id,
                    task_id=node.task_id,
                    node_id=node.node_id,
                    ttl_seconds=60.0,
                )
                self.router.register_agent_task(agent_desc.agent_id, node.task_id)
                engine.mark_running(node.node_id, agent_id=agent_desc.agent_id)

                # Record delegation
                delegation_entry = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "task_id": node.task_id,
                    "node_id": node.node_id,
                    "node_name": node.name,
                    "assigned_agent": agent_desc.agent_id,
                    "capability": node.required_capability.value,
                    "status": "RUNNING",
                }
                self._delegation_log.append(delegation_entry)

                try:
                    specialist = self._specialists.get(agent_desc.agent_id)
                    if not specialist:
                        raise OrchestrationError(
                            f"Specialist instance '{agent_desc.agent_id}' is not loaded."
                        )

                    # Execute subtask
                    output = await specialist.execute_subtask(node)
                    engine.mark_completed(node.node_id, output=output)
                    delegation_entry["status"] = "COMPLETED"

                    # Publish output into shared context
                    self.shared_context.publish_context(
                        key=f"output_{node.node_id}",
                        content=output,
                        owner_agent_id=agent_desc.agent_id,
                        source=f"agent:{agent_desc.agent_id}",
                        provenance=node.name,
                        trust_level=TrustLevel.HEURISTIC,
                        task_id=node.task_id,
                    )

                except Exception as exc:
                    logger.error("Coding node '%s' execution failed: %s", node.node_id, exc)
                    engine.mark_failed(node.node_id, error=str(exc))
                    delegation_entry["status"] = "FAILED"
                    delegation_entry["error"] = str(exc)
                finally:
                    self.registry.release_agent_lease(lease.lease_id)
                    self.router.unregister_agent_task(agent_desc.agent_id)

            await asyncio.gather(*[_run_coding_node(n) for n in batch])

        # Independent Code Review Gate
        review_result = None
        if enforce_review and not graph.has_failures():
            review_result = self.code_reviewer.review_code_deliverables(
                graph=graph,
                diffs=collected_diffs,
                require_tests=True,
                disallowed_imports=disallowed_imports,
            )
            if review_result.verdict == ReviewVerdict.REJECTED:
                finding_msgs = [
                    f"[{f.severity}] {f.issue} -> {f.remediation}"
                    for f in review_result.actionable_findings
                ]
                raise ReviewRejectionError(
                    f"Independent code review REJECTED: {review_result.summary} | Findings: {'; '.join(finding_msgs)}"
                )

        return graph, review_result

    def get_delegation_history(self) -> list[dict[str, Any]]:
        """Return the auditable delegation history."""
        return list(self._delegation_log)
