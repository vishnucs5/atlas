"""WorkflowExecutor compiling marketplace packages to canonical TaskGraphs and dispatching to AgentSupervisor."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from atlas_core.contracts.graph import NodeStatus, TaskGraph, TaskNode
from atlas_core.contracts.memory import MemoryScope
from atlas_orchestration.supervisor import (
    AgentSupervisor,
    ReviewRejectionError,
)
from atlas_policy.firewall import ActionFirewall
from pydantic import BaseModel, ConfigDict, Field

from atlas_marketplace.models import (
    PermissionScope,
    WorkflowPackage,
)
from atlas_marketplace.registry import MarketplaceRegistry

logger = logging.getLogger("atlas.marketplace.executor")


class WorkflowExecutionError(Exception):
    """Base exception for workflow execution failures."""


class PermissionDeniedError(WorkflowExecutionError):
    """Raised when a package requests permissions forbidden by the security policy."""


class WorkflowExecutionResult(BaseModel):
    """Execution outcome produced by WorkflowExecutor."""

    model_config = ConfigDict(validate_assignment=True)

    task_id: str
    package_id: str
    version: str
    status: str
    deliverables: dict[str, Any] = Field(default_factory=dict)
    graph: TaskGraph
    started_at: datetime
    completed_at: datetime | None = None
    error: str | None = None


class WorkflowExecutor:
    """Executes marketplace workflow packages through the canonical ATLAS multi-agent runtime."""

    def __init__(
        self,
        registry: MarketplaceRegistry,
        supervisor: AgentSupervisor,
        firewall: ActionFirewall | None = None,
    ) -> None:
        self.registry = registry
        self.supervisor = supervisor
        self.firewall = firewall or ActionFirewall()

    def evaluate_package_permissions(self, package: WorkflowPackage) -> None:
        """Validate package declared permissions against ActionFirewall security policies."""
        manifest = package.manifest
        for perm in manifest.permissions:
            # 1. Network domain allowlist checks
            if perm.scope == PermissionScope.NETWORK and perm.domains:
                for domain in perm.domains:
                    if domain in self.firewall.blocked_domains:
                        raise PermissionDeniedError(
                            f"Package '{manifest.package_id}' requests blocked domain '{domain}'."
                        )

            # 2. Filesystem path containment checks
            if perm.scope == PermissionScope.FILESYSTEM and perm.path_pattern:
                # Reject root filesystem escape or absolute system directory patterns
                if perm.path_pattern.startswith("/") or perm.path_pattern.startswith("\\"):
                    raise PermissionDeniedError(
                        f"Package '{manifest.package_id}' requests forbidden absolute path '{perm.path_pattern}'."
                    )
                if ".." in perm.path_pattern:
                    raise PermissionDeniedError(
                        f"Package '{manifest.package_id}' contains directory traversal in path '{perm.path_pattern}'."
                    )

    def compile_workflow_to_task_graph(
        self,
        package: WorkflowPackage,
        task_id: str,
        input_parameters: dict[str, Any] | None = None,
    ) -> TaskGraph:
        """Translate package workflow DAG definition into a canonical ATLAS TaskGraph."""
        manifest = package.manifest
        workflow_def = package.workflow
        if not workflow_def or not workflow_def.nodes:
            raise WorkflowExecutionError(
                f"Package '{manifest.package_id}' does not contain an executable workflow definition."
            )

        now = datetime.now(UTC)
        inputs = input_parameters or {}
        nodes: dict[str, TaskNode] = {}

        for w_node in workflow_def.nodes:
            # Merge workflow parameters with runtime inputs
            combined_params = {**w_node.parameters, **inputs}
            task_node = TaskNode(
                node_id=f"{task_id}_{w_node.node_id}",
                task_id=task_id,
                name=w_node.name,
                required_capability=w_node.required_capability,
                parameters=combined_params,
                dependencies=[f"{task_id}_{dep}" for dep in w_node.dependencies],
                dependency_type=w_node.dependency_type,
                status=NodeStatus.PENDING,
            )
            nodes[task_node.node_id] = task_node

        graph = TaskGraph(
            graph_id=f"graph_{uuid.uuid4().hex[:10]}",
            task_id=task_id,
            version=1,
            nodes=nodes,
            created_at=now,
            updated_at=now,
        )
        return graph

    async def execute_workflow(
        self,
        package_id: str,
        version: str | None = None,
        tenant_id: str = "default",
        task_id: str | None = None,
        inputs: dict[str, Any] | None = None,
        max_parallel: int = 4,
        enforce_review: bool = True,
    ) -> WorkflowExecutionResult:
        """End-to-end execution of a marketplace workflow package."""
        now = datetime.now(UTC)
        effective_task_id = task_id or f"task_wf_{uuid.uuid4().hex[:8]}"

        # 1. Fetch package from registry
        record = self.registry.get_package(package_id, version=version, tenant_id=tenant_id)
        if not record:
            raise KeyError(
                f"Package '{package_id}' version '{version or 'latest'}' not found in registry."
            )

        # 2. Unpack and validate package
        pkg = self.registry._packages[package_id][record.version]
        from atlas_marketplace.package import unpack_and_validate_package

        validated_pkg = unpack_and_validate_package(
            archive_bytes=pkg.archive_bytes,
            revoked_publishers=self.registry._revoked_publishers,
        )

        # 3. Evaluate permissions
        self.evaluate_package_permissions(validated_pkg)

        # 4. Gated untrusted memory injection
        self.supervisor.memory.store(
            key=f"package_manifest_{package_id}",
            value=validated_pkg.manifest.model_dump(),
            scope=MemoryScope.TASK_SCOPED,
            contributor_id="workflow_executor",
            task_id=effective_task_id,
            is_untrusted=True,  # Third-party package definitions are untrusted
        )

        # 5. Compile to TaskGraph
        graph = self.compile_workflow_to_task_graph(
            package=validated_pkg,
            task_id=effective_task_id,
            input_parameters=inputs,
        )

        # 6. Execute DAG through AgentSupervisor
        error_msg: str | None = None
        status = "COMPLETED"
        deliverables: dict[str, Any] = {}

        try:
            completed_graph = await self.supervisor.execute_graph(
                graph=graph,
                max_parallel=max_parallel,
                enforce_review=enforce_review,
                required_outputs=validated_pkg.manifest.verification_criteria,
            )

            # Aggregate deliverables
            for node in completed_graph.nodes.values():
                if node.output:
                    deliverables.update(node.output)

        except ReviewRejectionError as rev_err:
            status = "FAILED"
            error_msg = f"Independent Reviewer rejected deliverables: {rev_err}"
            logger.error("Workflow review rejection: %s", error_msg)
            raise
        except Exception as exc:
            status = "FAILED"
            error_msg = str(exc)
            logger.error("Workflow execution failed: %s", error_msg)
            raise WorkflowExecutionError(f"Execution failed: {exc}") from exc

        return WorkflowExecutionResult(
            task_id=effective_task_id,
            package_id=package_id,
            version=record.version,
            status=status,
            deliverables=deliverables,
            graph=graph,
            started_at=now,
            completed_at=datetime.now(UTC),
            error=error_msg,
        )
