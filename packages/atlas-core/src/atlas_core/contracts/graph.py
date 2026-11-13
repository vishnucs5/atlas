"""Task DAG, node dependencies, execution states, and graph contracts."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atlas_core.contracts.agent import AgentCapability


class NodeStatus(StrEnum):
    """Lifecycle execution status of an individual task graph node."""

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class DependencyType(StrEnum):
    """Semantic requirement of a node's dependency on its parent."""

    HARD = "HARD"  # Parent must reach COMPLETED
    OPTIONAL = "OPTIONAL"  # Parent may fail or be skipped without blocking this node
    CONDITIONAL = "CONDITIONAL"  # Evaluated dynamically against parent output


class TaskNode(BaseModel):
    """An individual unit of execution within an orchestrated task DAG."""

    model_config = ConfigDict(validate_assignment=True)

    node_id: str
    task_id: str
    name: str
    description: str = ""
    required_capability: AgentCapability = AgentCapability.GENERAL
    parameters: dict[str, Any] = Field(default_factory=dict)
    status: NodeStatus = NodeStatus.PENDING
    assigned_agent_id: str | None = None
    dependencies: list[str] = Field(default_factory=list)  # Parent node_ids
    dependency_type: DependencyType = DependencyType.HARD
    condition_expr: str | None = None  # e.g. "output.get('status') == 'approved'"
    retry_limit: int = 2
    retry_count: int = 0
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def is_terminal(self) -> bool:
        """Evaluate if the node has finished execution."""
        return self.status in (
            NodeStatus.COMPLETED,
            NodeStatus.FAILED,
            NodeStatus.SKIPPED,
            NodeStatus.CANCELLED,
        )


class TaskGraph(BaseModel):
    """Versioned Directed Acyclic Graph representing an orchestrated multi-agent task."""

    model_config = ConfigDict(validate_assignment=True)

    graph_id: str
    task_id: str
    version: int = 1
    nodes: dict[str, TaskNode] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"

    def is_complete(self) -> bool:
        """Check if all nodes in the DAG have reached a terminal state."""
        if not self.nodes:
            return False
        return all(node.is_terminal() for node in self.nodes.values())

    def has_failures(self) -> bool:
        """Check if any hard node failed."""
        return any(
            node.status == NodeStatus.FAILED and node.dependency_type == DependencyType.HARD
            for node in self.nodes.values()
        )
