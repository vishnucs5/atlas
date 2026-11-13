"""Unit tests verifying WorkflowExecutor, TaskGraph compilation, ActionFirewall gating, and QA review."""

import pytest
from atlas_core.contracts.agent import (
    AgentCapability,
    AgentDescriptor,
)
from atlas_marketplace.executor import (
    PermissionDeniedError,
    WorkflowExecutor,
)
from atlas_marketplace.models import (
    PackageManifest,
    PackageType,
    PermissionDeclaration,
    PermissionScope,
    PublisherIdentity,
    WorkflowGraphDefinition,
    WorkflowNodeDefinition,
)
from atlas_marketplace.package import build_package_archive
from atlas_marketplace.registry import MarketplaceRegistry
from atlas_orchestration.memory import SharedMemoryEngine
from atlas_orchestration.messaging import AgentMessageRouter
from atlas_orchestration.specialist import (
    CodingSpecialist,
    ResearchSpecialist,
)
from atlas_orchestration.supervisor import (
    AgentSupervisor,
    ReviewRejectionError,
)
from atlas_policy.firewall import ActionFirewall


@pytest.fixture
def execution_env():
    """Build connected supervisor, registry, and executor environment."""
    registry = MarketplaceRegistry()
    memory = SharedMemoryEngine()
    router = AgentMessageRouter()
    from atlas_orchestration.registry import AgentRegistry

    agent_reg = AgentRegistry()
    supervisor = AgentSupervisor(
        registry=agent_reg,
        memory=memory,
        router=router,
    )

    # Register specialists
    supervisor.register_specialist(
        ResearchSpecialist(
            AgentDescriptor(
                agent_id="agent_res",
                name="Researcher",
                role="R",
                capabilities=[AgentCapability.RESEARCH],
            ),
            memory=memory,
        )
    )
    supervisor.register_specialist(
        CodingSpecialist(
            AgentDescriptor(
                agent_id="agent_code",
                name="Coder",
                role="C",
                capabilities=[AgentCapability.CODE],
            ),
            memory=memory,
        )
    )

    firewall = ActionFirewall(blocked_domains=["forbidden.com", "malicious.org"])
    executor = WorkflowExecutor(registry=registry, supervisor=supervisor, firewall=firewall)
    return {
        "registry": registry,
        "supervisor": supervisor,
        "executor": executor,
        "firewall": firewall,
    }


@pytest.mark.asyncio
async def test_workflow_permission_denial_on_blocked_domain(execution_env):
    """Verify package requesting forbidden domain is blocked with PermissionDeniedError."""
    registry: MarketplaceRegistry = execution_env["registry"]
    executor: WorkflowExecutor = execution_env["executor"]

    manifest = PackageManifest(
        package_id="com.atlas.wf.evil",
        package_type=PackageType.WORKFLOW,
        name="Evil Workflow",
        description="Forbidden network",
        version="1.0.0",
        publisher=PublisherIdentity(
            publisher_id="pub_1",
            name="P",
            email="p@atlas.org",
            public_key="k1",
        ),
        permissions=[
            PermissionDeclaration(
                scope=PermissionScope.NETWORK,
                access="domain_allowlist",
                domains=["forbidden.com"],  # Blocked in firewall!
            )
        ],
    )
    wf = WorkflowGraphDefinition(
        graph_id="wf_e",
        nodes=[
            WorkflowNodeDefinition(
                node_id="n1",
                name="Step",
                required_capability=AgentCapability.RESEARCH,
            )
        ],
    )
    arch = build_package_archive(manifest=manifest, workflow=wf, signing_key="k1")
    registry.publish_package(arch)

    with pytest.raises(PermissionDeniedError, match="blocked domain"):
        await executor.execute_workflow("com.atlas.wf.evil")


@pytest.mark.asyncio
async def test_workflow_permission_denial_on_path_traversal(execution_env):
    """Verify package requesting path traversal is blocked with PermissionDeniedError."""
    registry: MarketplaceRegistry = execution_env["registry"]
    executor: WorkflowExecutor = execution_env["executor"]

    manifest = PackageManifest(
        package_id="com.atlas.wf.traversal",
        package_type=PackageType.WORKFLOW,
        name="Traversal Workflow",
        description="Path traversal",
        version="1.0.0",
        publisher=PublisherIdentity(
            publisher_id="pub_2",
            name="P",
            email="p@atlas.org",
            public_key="k2",
        ),
        permissions=[
            PermissionDeclaration(
                scope=PermissionScope.FILESYSTEM,
                access="read_write",
                path_pattern="../../etc/shadow",  # Directory traversal!
            )
        ],
    )
    wf = WorkflowGraphDefinition(
        graph_id="wf_t",
        nodes=[
            WorkflowNodeDefinition(
                node_id="n1",
                name="Step",
                required_capability=AgentCapability.RESEARCH,
            )
        ],
    )
    arch = build_package_archive(manifest=manifest, workflow=wf, signing_key="k2")
    registry.publish_package(arch)

    with pytest.raises(PermissionDeniedError, match="directory traversal"):
        await executor.execute_workflow("com.atlas.wf.traversal")


@pytest.mark.asyncio
async def test_workflow_executor_end_to_end_success(execution_env):
    """Verify end-to-end execution of a published workflow through AgentSupervisor."""
    registry: MarketplaceRegistry = execution_env["registry"]
    executor: WorkflowExecutor = execution_env["executor"]

    manifest = PackageManifest(
        package_id="com.atlas.wf.consensus.verify",
        package_type=PackageType.WORKFLOW,
        name="Consensus Verify",
        description="Valid workflow",
        version="1.0.0",
        publisher=PublisherIdentity(
            publisher_id="pub_core",
            name="Core",
            email="core@atlas.org",
            public_key="core_key",
        ),
        required_capabilities=[AgentCapability.RESEARCH, AgentCapability.CODE],
        verification_criteria=["summary"],
    )
    wf = WorkflowGraphDefinition(
        graph_id="wf_good",
        nodes=[
            WorkflowNodeDefinition(
                node_id="step_res",
                name="Research Step",
                required_capability=AgentCapability.RESEARCH,
                parameters={"query": "Raft protocol"},
            ),
            WorkflowNodeDefinition(
                node_id="step_code",
                name="Coding Step",
                required_capability=AgentCapability.CODE,
                parameters={"filepath": "raft.py", "content": "# raft"},
                dependencies=["step_res"],
            ),
        ],
    )
    arch = build_package_archive(manifest=manifest, workflow=wf, signing_key="core_key")
    registry.publish_package(arch)

    result = await executor.execute_workflow("com.atlas.wf.consensus.verify")
    assert result.status == "COMPLETED"
    assert result.error is None
    assert result.graph.is_complete()
    assert "summary" in result.deliverables


@pytest.mark.asyncio
async def test_workflow_executor_rejection_on_missing_criteria(execution_env):
    """Verify IndependentReviewer rejects workflow if declared verification criteria are not met."""
    registry: MarketplaceRegistry = execution_env["registry"]
    executor: WorkflowExecutor = execution_env["executor"]

    manifest = PackageManifest(
        package_id="com.atlas.wf.unmet",
        package_type=PackageType.WORKFLOW,
        name="Unmet Criteria",
        description="Missing criteria",
        version="1.0.0",
        publisher=PublisherIdentity(
            publisher_id="pub_c",
            name="C",
            email="c@atlas.org",
            public_key="ckey",
        ),
        required_capabilities=[AgentCapability.RESEARCH],
        verification_criteria=["non_existent_deliverable_key"],  # Will never be produced!
    )
    wf = WorkflowGraphDefinition(
        graph_id="wf_unmet",
        nodes=[
            WorkflowNodeDefinition(
                node_id="n1",
                name="Step",
                required_capability=AgentCapability.RESEARCH,
                parameters={"query": "test"},
            )
        ],
    )
    arch = build_package_archive(manifest=manifest, workflow=wf, signing_key="ckey")
    registry.publish_package(arch)

    with pytest.raises(ReviewRejectionError):
        await executor.execute_workflow("com.atlas.wf.unmet", enforce_review=True)
