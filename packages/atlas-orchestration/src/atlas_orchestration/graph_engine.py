"""TaskGraphEngine providing DAG validation, cycle detection, parallel dispatch, and failure cascading."""

import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

from atlas_core.contracts.graph import (
    DependencyType,
    NodeStatus,
    TaskGraph,
    TaskNode,
)


class CyclicDependencyError(Exception):
    """Raised when task graph contains a cycle or circular dependency."""


class NodeNotFoundError(Exception):
    """Raised when an operation references a non-existent task node."""


class InvalidNodeStateError(Exception):
    """Raised when an invalid state transition is requested on a task node."""


class TaskGraphEngine:
    """Manages DAG lifecycle, dependency resolution, topological sorting, and failure propagation."""

    def __init__(self, graph: TaskGraph) -> None:
        self._lock = threading.RLock()
        self.graph = graph
        self.validate_graph()

    def validate_graph(self) -> None:
        """Validate DAG integrity: verify all dependency references exist and detect cycles."""
        with self._lock:
            # 1. Verify referenced dependencies exist
            for node in self.graph.nodes.values():
                for dep_id in node.dependencies:
                    if dep_id not in self.graph.nodes:
                        raise NodeNotFoundError(
                            f"Node '{node.node_id}' references non-existent dependency '{dep_id}'."
                        )

            # 2. Cycle detection via Kahn's algorithm
            in_degree: dict[str, int] = dict.fromkeys(self.graph.nodes, 0)
            adj: dict[str, list[str]] = {nid: [] for nid in self.graph.nodes}

            for node in self.graph.nodes.values():
                for dep_id in node.dependencies:
                    adj[dep_id].append(node.node_id)
                    in_degree[node.node_id] += 1

            queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
            visited_count = 0

            while queue:
                curr = queue.popleft()
                visited_count += 1
                for neighbor in adj[curr]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

            if visited_count < len(self.graph.nodes):
                raise CyclicDependencyError(
                    f"Cyclic dependency detected in task graph '{self.graph.graph_id}'."
                )

    def get_execution_batches(self) -> list[list[str]]:
        """Return topological execution batches where all nodes in a batch can run in parallel."""
        with self._lock:
            in_degree: dict[str, int] = {
                nid: len(n.dependencies) for nid, n in self.graph.nodes.items()
            }
            adj: dict[str, list[str]] = {nid: [] for nid in self.graph.nodes}

            for node in self.graph.nodes.values():
                for dep_id in node.dependencies:
                    adj[dep_id].append(node.node_id)

            batches: list[list[str]] = []
            current_batch = [nid for nid, deg in in_degree.items() if deg == 0]

            while current_batch:
                batches.append(sorted(current_batch))
                next_batch: list[str] = []
                for curr in current_batch:
                    for neighbor in adj[curr]:
                        in_degree[neighbor] -= 1
                        if in_degree[neighbor] == 0:
                            next_batch.append(neighbor)
                current_batch = next_batch

            return batches

    def is_node_ready(self, node_id: str) -> bool:
        """Determine whether a node's dependencies are satisfied and it is ready to execute."""
        with self._lock:
            node = self.graph.nodes.get(node_id)
            if not node or node.status != NodeStatus.PENDING:
                return False

            for dep_id in node.dependencies:
                parent = self.graph.nodes.get(dep_id)
                if not parent:
                    return False

                if node.dependency_type == DependencyType.HARD:
                    if parent.status != NodeStatus.COMPLETED:
                        return False
                elif node.dependency_type == DependencyType.CONDITIONAL:
                    if parent.status != NodeStatus.COMPLETED:
                        return False
                    # Check condition predicate against parent output
                    if node.condition_expr and parent.output:
                        try:
                            # Evaluate condition safely with parent output context
                            res = bool(
                                eval(
                                    node.condition_expr,
                                    {"__builtins__": {}},
                                    {"output": parent.output},
                                )
                            )
                            if not res:
                                return False
                        except Exception:
                            return False
                elif node.dependency_type == DependencyType.OPTIONAL:
                    if not parent.is_terminal():
                        return False

            return True

    def get_ready_nodes(self) -> list[TaskNode]:
        """Return all nodes eligible to be assigned and executed immediately."""
        with self._lock:
            ready: list[TaskNode] = []
            for node in self.graph.nodes.values():
                if self.is_node_ready(node.node_id):
                    node.status = NodeStatus.READY
                    ready.append(node)
                elif node.status == NodeStatus.READY:
                    ready.append(node)
            return ready

    def mark_running(self, node_id: str, agent_id: str) -> TaskNode:
        """Mark a node as actively executing under an agent."""
        with self._lock:
            node = self.graph.nodes.get(node_id)
            if not node:
                raise NodeNotFoundError(f"Node '{node_id}' not found.")
            if node.status not in (NodeStatus.READY, NodeStatus.PENDING):
                raise InvalidNodeStateError(
                    f"Cannot transition node '{node_id}' to RUNNING from state '{node.status.value}'."
                )
            node.status = NodeStatus.RUNNING
            node.assigned_agent_id = agent_id
            node.started_at = datetime.now(UTC)
            self.graph.updated_at = datetime.now(UTC)
            return node

    def mark_completed(self, node_id: str, output: dict[str, Any] | None = None) -> TaskNode:
        """Mark a node as successfully completed with output artifacts."""
        with self._lock:
            node = self.graph.nodes.get(node_id)
            if not node:
                raise NodeNotFoundError(f"Node '{node_id}' not found.")
            node.status = NodeStatus.COMPLETED
            node.output = output or {}
            node.completed_at = datetime.now(UTC)
            self.graph.updated_at = datetime.now(UTC)
            return node

    def mark_failed(self, node_id: str, error: str) -> TaskNode:
        """Record node failure, handling retry policies and cascading cancellations."""
        with self._lock:
            node = self.graph.nodes.get(node_id)
            if not node:
                raise NodeNotFoundError(f"Node '{node_id}' not found.")
            node.error = error
            node.retry_count += 1

            if node.retry_count <= node.retry_limit:
                # Re-queue for retry
                node.status = NodeStatus.READY
                node.assigned_agent_id = None
            else:
                # Terminal failure
                node.status = NodeStatus.FAILED
                node.completed_at = datetime.now(UTC)
                # Cascade cancellation to downstream hard-dependent nodes
                if node.dependency_type == DependencyType.HARD:
                    self._cascade_cancellation(node_id)

            self.graph.updated_at = datetime.now(UTC)
            return node

    def _cascade_cancellation(self, failed_node_id: str) -> None:
        """Recursively cancel downstream nodes depending on a failed hard dependency."""
        downstream: list[str] = []
        for n in self.graph.nodes.values():
            if failed_node_id in n.dependencies and n.dependency_type == DependencyType.HARD:
                if not n.is_terminal():
                    n.status = NodeStatus.CANCELLED
                    n.error = f"Upstream hard dependency '{failed_node_id}' failed."
                    n.completed_at = datetime.now(UTC)
                    downstream.append(n.node_id)

        for child_id in downstream:
            self._cascade_cancellation(child_id)

    def mark_skipped(self, node_id: str, reason: str = "Condition not met") -> TaskNode:
        """Mark a node as skipped."""
        with self._lock:
            node = self.graph.nodes.get(node_id)
            if not node:
                raise NodeNotFoundError(f"Node '{node_id}' not found.")
            node.status = NodeStatus.SKIPPED
            node.error = reason
            node.completed_at = datetime.now(UTC)
            self.graph.updated_at = datetime.now(UTC)
            return node

    def replan(self, new_nodes: list[TaskNode]) -> TaskGraph:
        """Dynamically add or update graph nodes and increment DAG version."""
        with self._lock:
            for node in new_nodes:
                self.graph.nodes[node.node_id] = node
            self.validate_graph()
            self.graph.version += 1
            self.graph.updated_at = datetime.now(UTC)
            return self.graph

    def get_progress(self) -> dict[str, Any]:
        """Compute execution statistics across graph nodes."""
        with self._lock:
            total = len(self.graph.nodes)
            completed = sum(
                1 for n in self.graph.nodes.values() if n.status == NodeStatus.COMPLETED
            )
            failed = sum(1 for n in self.graph.nodes.values() if n.status == NodeStatus.FAILED)
            running = sum(1 for n in self.graph.nodes.values() if n.status == NodeStatus.RUNNING)
            ready = sum(1 for n in self.graph.nodes.values() if n.status == NodeStatus.READY)
            skipped = sum(1 for n in self.graph.nodes.values() if n.status == NodeStatus.SKIPPED)
            cancelled = sum(
                1 for n in self.graph.nodes.values() if n.status == NodeStatus.CANCELLED
            )
            pending = sum(1 for n in self.graph.nodes.values() if n.status == NodeStatus.PENDING)

            pct = (completed / total * 100.0) if total > 0 else 0.0
            return {
                "total_nodes": total,
                "completed": completed,
                "failed": failed,
                "running": running,
                "ready": ready,
                "skipped": skipped,
                "cancelled": cancelled,
                "pending": pending,
                "completion_percentage": round(pct, 2),
                "is_complete": self.graph.is_complete(),
                "has_failures": self.graph.has_failures(),
            }
