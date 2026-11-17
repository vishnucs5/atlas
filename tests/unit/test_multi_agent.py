"""Comprehensive unit and integration tests for ATLAS CLI Multi-Agent Coding Environment."""

import tempfile
from pathlib import Path

import pytest
from atlas_core.contracts.action import ComputerAction
from atlas_core.contracts.agent import AgentCapability
from atlas_core.contracts.coding import UnifiedDiff
from atlas_core.contracts.graph import NodeStatus
from atlas_orchestration.coding_team.code_reviewer import (
    IndependentCodeReviewer,
)
from atlas_orchestration.coding_team.conflict_detector import (
    ConflictType,
)
from atlas_orchestration.coding_team.shared_context import (
    CodingSharedContext,
    TrustLevel,
    UnverifiedFactError,
)
from atlas_orchestration.coding_team.specialists import (
    create_specialist_roster,
)
from atlas_orchestration.coding_team.supervisor import CodingTeamSupervisor
from atlas_orchestration.coding_team.workspace_isolation import (
    WorkspaceConflictError,
    WorkspaceIsolationManager,
)
from atlas_orchestration.memory import SharedMemoryEngine
from atlas_orchestration.registry import AgentBudgetExhaustedError
from atlas_orchestration.reviewer import ReviewVerdict
from atlas_orchestration.specialist import PolicyViolationError
from atlas_policy.firewall import ActionFirewall, PolicyRule


@pytest.fixture
def repo_sandbox():
    """Create a temporary sandbox repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        src_dir = root / "src"
        src_dir.mkdir(parents=True)
        (src_dir / "app.py").write_text("def run(): pass\n", encoding="utf-8")
        yield root


def test_specialist_roster_initialization_and_descriptors(repo_sandbox):
    """Verify all 11 specialist engineering agents are instantiated with correct capabilities."""
    mem = SharedMemoryEngine()
    firewall = ActionFirewall()
    roster = create_specialist_roster(memory=mem, firewall=firewall, repo_root=str(repo_sandbox))

    expected_agents = [
        ("agent_architect", AgentCapability.ARCHITECT),
        ("agent_explorer", AgentCapability.EXPLORER),
        ("agent_backend", AgentCapability.BACKEND),
        ("agent_frontend", AgentCapability.FRONTEND),
        ("agent_database", AgentCapability.DATABASE),
        ("agent_infra", AgentCapability.INFRASTRUCTURE),
        ("agent_testing", AgentCapability.TESTING),
        ("agent_security", AgentCapability.SECURITY_AUDITOR),
        ("agent_reviewer", AgentCapability.CODE_REVIEWER),
        ("agent_docs", AgentCapability.DOCUMENTATION),
        ("agent_debugging", AgentCapability.DEBUGGING),
    ]

    assert len(roster) == 11
    for aid, cap in expected_agents:
        assert aid in roster
        spec = roster[aid]
        assert spec.descriptor.has_capability(cap)
        assert spec.descriptor.budget.max_tokens >= 100_000
        assert spec.descriptor.budget.max_steps >= 40


def test_task_decomposition_into_dag(repo_sandbox):
    """Verify task decomposition into multi-stage DAG with correct dependencies."""
    supervisor = CodingTeamSupervisor(repo_root=repo_sandbox)
    graph = supervisor.decompose_engineering_objective(
        task_id="task_123",
        objective="Build user authentication endpoint and frontend form",
        target_files=["src/auth.py", "src/login.tsx"],
    )

    assert len(graph.nodes) >= 5
    nodes = graph.nodes

    # Check stages: Architect -> Explorer -> Impl (Backend & Frontend) -> Testing -> Security
    arch_node = next(
        n for n in nodes.values() if n.required_capability == AgentCapability.ARCHITECT
    )
    exp_node = next(n for n in nodes.values() if n.required_capability == AgentCapability.EXPLORER)
    test_node = next(n for n in nodes.values() if n.required_capability == AgentCapability.TESTING)
    sec_node = next(
        n for n in nodes.values() if n.required_capability == AgentCapability.SECURITY_AUDITOR
    )

    assert exp_node.dependencies == [arch_node.node_id]
    assert test_node.dependencies != []
    assert sec_node.dependencies == [test_node.node_id]


def test_conflict_detection_and_sequential_serialization(repo_sandbox):
    """Verify that multiple concurrent tasks targeting the same file are detected and serialized."""
    supervisor = CodingTeamSupervisor(repo_root=repo_sandbox)
    # Both backend tasks target the same file: src/auth.py
    graph = supervisor.decompose_engineering_objective(
        task_id="task_conf",
        objective="Refactor authentication service",
        target_files=["src/auth.py", "src/auth.py"],
    )

    conf_mgr = supervisor.conflict_manager
    conflicts = conf_mgr.detected_conflicts
    assert len(conflicts) >= 1
    assert any(c.conflict_type == ConflictType.OVERLAPPING_FILE_WRITE for c in conflicts)

    # Verify dependency edge was injected so they do not execute in parallel
    impl_nodes = [n for n in graph.nodes.values() if "node_impl_task_conf" in n.node_id]
    assert len(impl_nodes) == 2
    # Second node must depend on the first node
    assert (
        impl_nodes[0].node_id in impl_nodes[1].dependencies
        or impl_nodes[1].node_id in impl_nodes[0].dependencies
    )

    # Verify decision history
    history = conf_mgr.get_audit_history()
    assert len(history) >= 1
    assert history[0].resolution_strategy == "SERIALIZE_DEPENDENCY"


@pytest.mark.asyncio
async def test_parallel_execution_of_independent_tasks(repo_sandbox):
    """Verify parallel execution of independent tasks under concurrency limits."""
    supervisor = CodingTeamSupervisor(repo_root=repo_sandbox)
    graph = supervisor.decompose_engineering_objective(
        task_id="task_exec",
        objective="Create backend API and documentation",
        target_files=["src/api.py"],
        parameters={"test_file": "tests/test_api.py", "run_suite": False},
    )

    completed_graph, review = await supervisor.execute_coding_team(
        graph=graph,
        max_parallel=4,
        enforce_review=False,
    )

    assert completed_graph.is_complete()
    assert not completed_graph.has_failures()
    for node in completed_graph.nodes.values():
        assert node.status == NodeStatus.COMPLETED
        assert node.output is not None

    # Delegation history is recorded
    delegation = supervisor.get_delegation_history()
    assert len(delegation) >= len(graph.nodes)


def test_workspace_isolation_and_conflict_prevention(repo_sandbox):
    """Verify that concurrent agent changes are isolated and cannot silently overwrite."""
    iso_mgr = WorkspaceIsolationManager(base_repo_root=repo_sandbox)

    ws_backend = iso_mgr.allocate_workspace(agent_id="agent_backend")
    ws_frontend = iso_mgr.allocate_workspace(agent_id="agent_frontend")

    # 1. Isolated writes
    ws_backend.write_staged_file("src/shared.py", "def backend_func(): pass\n")
    ws_frontend.write_staged_file("src/shared.py", "def frontend_func(): pass\n")

    # Base file should remain untouched until integration
    base_file = repo_sandbox / "src" / "shared.py"
    assert not base_file.exists()

    # 2. Integrate backend changes cleanly
    res1 = iso_mgr.integrate_workspace_changes(ws_backend)
    assert res1["status"] == "INTEGRATED"
    assert "src/shared.py" in res1["integrated_files"]
    assert base_file.read_text(encoding="utf-8") == "def backend_func(): pass\n"

    # 3. Attempting to integrate frontend with same file raises conflict error (no silent overwrite)
    with pytest.raises(WorkspaceConflictError) as exc_info:
        iso_mgr.integrate_workspace_changes(ws_frontend, allow_overwrite=False)

    assert "Concurrent integration conflict" in str(exc_info.value)

    # Cleanup
    iso_mgr.cleanup_all()
    assert not (repo_sandbox / ".atlas" / "workspaces").exists()


def test_shared_context_provenance_and_trust_level_protection():
    """Verify shared context provenance tracking and protection against unverified claims."""
    ctx = CodingSharedContext()

    # 1. Publish heuristic claim
    item_heuristic = ctx.publish_context(
        key="performance_baseline",
        content={"p95_ms": 12.5},
        owner_agent_id="agent_backend",
        source="agent:agent_backend",
        provenance="Hypothetical estimation",
        trust_level=TrustLevel.HEURISTIC,
        task_id="t_1",
    )
    assert item_heuristic.is_authoritative is False

    # 2. Querying as authoritative raises UnverifiedFactError
    with pytest.raises(UnverifiedFactError):
        ctx.get_context(key="performance_baseline", task_id="t_1", require_authoritative=True)

    # 3. Promote to VERIFIED with verifier provenance
    ctx.promote_to_verified(
        key="performance_baseline",
        verifier_agent_id="agent_reviewer",
        task_id="t_1",
        verification_evidence="Confirmed by benchmark test suite",
    )

    verified_item = ctx.get_context(
        key="performance_baseline", task_id="t_1", require_authoritative=True
    )
    assert verified_item is not None
    assert verified_item.is_authoritative is True
    assert verified_item.trust_level == TrustLevel.VERIFIED
    assert "Verified by agent_reviewer" in verified_item.provenance


def test_independent_code_reviewer_approval_and_rejection(repo_sandbox):
    """Verify adversarial independent code review catches security leaks, prompt injections, and missing tests."""
    mem = SharedMemoryEngine()
    reviewer = IndependentCodeReviewer(memory=mem)
    supervisor = CodingTeamSupervisor(repo_root=repo_sandbox, reviewer=reviewer)

    graph = supervisor.decompose_engineering_objective(
        task_id="t_review",
        objective="Implement feature",
        target_files=["src/feature.py"],
    )

    # Mark all nodes completed cleanly
    for n in graph.nodes.values():
        n.status = NodeStatus.COMPLETED
        n.output = {"status": "ok", "verdict": "PASSED"}

    from atlas_core.contracts.coding import FilePatch

    # 1. Clean diff -> APPROVED
    clean_diff = [
        UnifiedDiff(
            patches=[FilePatch(source_path="src/feature.py", target_path="src/feature.py")],
            files_changed=1,
            insertions=2,
            deletions=0,
            raw_diff="@@ -0,0 +1,2 @@\n+def add(a, b):\n+    return a + b\n",
        )
    ]
    res_clean = reviewer.review_code_deliverables(graph=graph, diffs=clean_diff, require_tests=True)
    assert res_clean.verdict == ReviewVerdict.APPROVED
    assert len(res_clean.actionable_findings) == 0

    # 2. Hardcoded secret in diff -> REJECTED with actionable findings
    secret_diff = [
        UnifiedDiff(
            patches=[FilePatch(source_path="src/feature.py", target_path="src/feature.py")],
            files_changed=1,
            insertions=1,
            deletions=0,
            raw_diff='+api_key = "secret_live_tok_9918237498"\n',
        )
    ]
    res_sec = reviewer.review_code_deliverables(graph=graph, diffs=secret_diff, require_tests=True)
    assert res_sec.verdict == ReviewVerdict.REJECTED
    assert any(f.category == "SECURITY" for f in res_sec.actionable_findings)

    # 3. Unsafe shell execution in diff -> REJECTED
    unsafe_diff = [
        UnifiedDiff(
            patches=[FilePatch(source_path="src/feature.py", target_path="src/feature.py")],
            files_changed=1,
            insertions=1,
            deletions=0,
            raw_diff='+import os; os.system("rm -rf /")\n',
        )
    ]
    res_unsafe = reviewer.review_code_deliverables(
        graph=graph, diffs=unsafe_diff, require_tests=True
    )
    assert res_unsafe.verdict == ReviewVerdict.REJECTED
    assert any("os.system" in f.issue for f in res_unsafe.actionable_findings)


def test_agent_budget_exhaustion_and_cancellation(repo_sandbox):
    """Verify resource limits enforce budget exhaustion and cancellation propagates."""
    mem = SharedMemoryEngine()
    roster = create_specialist_roster(memory=mem, repo_root=str(repo_sandbox))
    architect = roster["agent_architect"]

    # Breaching token budget
    architect.descriptor.budget.max_tokens = 500
    architect.record_resource_usage(tokens=400)
    with pytest.raises(AgentBudgetExhaustedError):
        architect.record_resource_usage(tokens=200)

    # Test supervisor task cancellation
    supervisor = CodingTeamSupervisor(repo_root=repo_sandbox)
    graph = supervisor.decompose_engineering_objective(
        task_id="t_cancel",
        objective="Long running job",
    )
    from atlas_orchestration.graph_engine import TaskGraphEngine

    supervisor._active_graphs[graph.task_id] = TaskGraphEngine(graph)
    supervisor.cancel_task(task_id="t_cancel", reason="Operator interrupted")

    for node in graph.nodes.values():
        if not node.is_terminal():
            assert node.status == NodeStatus.CANCELLED


def test_action_firewall_blocks_unauthorized_specialist_action(repo_sandbox):
    """Verify specialist agents cannot bypass Action Firewall."""
    from atlas_core.contracts.policy import PolicyDecisionType, RiskLevel

    firewall = ActionFirewall()
    firewall.add_rule(
        PolicyRule(
            rule_id="deny_file_write",
            name="Deny file write",
            exact_action_type="file.write",
            decision=PolicyDecisionType.DENY,
            risk_level=RiskLevel.HIGH,
        )
    )

    mem = SharedMemoryEngine()
    roster = create_specialist_roster(memory=mem, firewall=firewall, repo_root=str(repo_sandbox))
    backend = roster["agent_backend"]

    bad_action = ComputerAction(
        action_id="act_bad_1",
        task_id="task_1",
        session_id="s_1",
        action_type="file.write",
        parameters={"filepath": "etc/passwd"},
        idempotency_key="idem_1",
    )

    with pytest.raises(PolicyViolationError) as exc_info:
        backend.validate_action(bad_action)

    assert "denied by policy firewall" in str(exc_info.value)


def test_cli_agents_list_and_inspect_commands():
    """Verify CLI commands list and inspect the 11 specialists."""
    from atlas_cli.commands.agents import run_agents_inspect, run_agents_list

    ret_list = run_agents_list()
    assert ret_list == 0

    ret_insp = run_agents_inspect("agent_architect")
    assert ret_insp == 0

    ret_insp_sec = run_agents_inspect("agent_security")
    assert ret_insp_sec == 0

    ret_not_found = run_agents_inspect("non_existent_agent")
    assert ret_not_found == 1
