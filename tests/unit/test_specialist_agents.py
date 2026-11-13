"""Unit tests verifying SpecialistAgent implementations, ActionFirewall gating, memory integration, and budget caps."""

import pytest
from atlas_core.contracts.agent import (
    AgentBudget,
    AgentCapability,
    AgentDescriptor,
)
from atlas_core.contracts.graph import TaskNode
from atlas_core.contracts.memory import MemoryScope
from atlas_orchestration.memory import SharedMemoryEngine
from atlas_orchestration.registry import AgentBudgetExhaustedError
from atlas_orchestration.specialist import (
    BrowserSpecialist,
    CodingSpecialist,
    DataAnalysisSpecialist,
    DesktopSpecialist,
    PolicyViolationError,
    QASpecialist,
    ResearchSpecialist,
)
from atlas_policy.firewall import ActionFirewall


@pytest.mark.asyncio
async def test_research_specialist_execution():
    """Verify ResearchSpecialist synthesizes findings and populates task memory."""
    mem = SharedMemoryEngine()
    desc = AgentDescriptor(
        agent_id="spec_res_1",
        name="Research Specialist",
        role="Researcher",
        capabilities=[AgentCapability.RESEARCH],
    )
    specialist = ResearchSpecialist(desc, memory=mem)

    node = TaskNode(
        node_id="node_res_1",
        task_id="task_p7_1",
        name="Analyze Distributed Consensus",
        parameters={"query": "Raft vs Paxos comparison"},
    )

    result = await specialist.execute_subtask(node)
    assert result["status"] == "completed"
    assert "Raft vs Paxos" in result["summary"]

    # Verify task memory
    stored = mem.retrieve(
        "research_node_res_1",
        scope=MemoryScope.TASK_SCOPED,
        requester_id="any",
        task_id="task_p7_1",
    )
    assert stored is not None
    assert stored.is_untrusted is False
    assert desc.budget.tokens_used > 0


@pytest.mark.asyncio
async def test_browser_specialist_firewall_enforcement():
    """Verify BrowserSpecialist enforces ActionFirewall and flags web content as untrusted."""
    mem = SharedMemoryEngine()
    # Firewall blocks evil.com explicitly
    firewall = ActionFirewall(blocked_domains=["evil.com"])

    desc = AgentDescriptor(
        agent_id="spec_browser_1",
        name="Browser Specialist",
        role="Web Agent",
        capabilities=[AgentCapability.BROWSER],
    )
    specialist = BrowserSpecialist(desc, memory=mem, firewall=firewall)

    # 1. Denied domain raises PolicyViolationError
    blocked_node = TaskNode(
        node_id="node_nav_bad",
        task_id="task_p7_1",
        name="Visit Malicious Site",
        parameters={"url": "https://evil.com/phish"},
    )
    with pytest.raises(PolicyViolationError) as exc:
        await specialist.execute_subtask(blocked_node)
    assert "denied by policy firewall" in str(exc.value).lower()

    # 2. Allowed domain executes and stores as untrusted
    allowed_node = TaskNode(
        node_id="node_nav_ok",
        task_id="task_p7_1",
        name="Visit Documentation",
        parameters={"url": "https://docs.python.org"},
    )
    result = await specialist.execute_subtask(allowed_node)
    assert result["status"] == "navigated"

    stored = mem.retrieve(
        "dom_extract_node_nav_ok",
        scope=MemoryScope.TASK_SCOPED,
        requester_id="any",
        task_id="task_p7_1",
    )
    assert stored is not None
    assert stored.is_untrusted is True  # External web data must be flagged untrusted


@pytest.mark.asyncio
async def test_desktop_specialist_execution():
    """Verify DesktopSpecialist runs native actions under firewall policy."""
    mem = SharedMemoryEngine()
    desc = AgentDescriptor(
        agent_id="spec_desktop_1",
        name="Desktop Specialist",
        role="Desktop Agent",
        capabilities=[AgentCapability.DESKTOP],
    )
    specialist = DesktopSpecialist(desc, memory=mem)

    node = TaskNode(
        node_id="node_desk_1",
        task_id="task_p7_1",
        name="Inspect Window",
        parameters={"action": "desktop.inspect", "target_app": "notepad.exe"},
    )
    result = await specialist.execute_subtask(node)
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_coding_specialist_execution():
    """Verify CodingSpecialist writes code artifact to task memory."""
    mem = SharedMemoryEngine()
    desc = AgentDescriptor(
        agent_id="spec_code_1",
        name="Coding Specialist",
        role="Software Engineer",
        capabilities=[AgentCapability.CODE],
    )
    specialist = CodingSpecialist(desc, memory=mem)

    node = TaskNode(
        node_id="node_code_1",
        task_id="task_p7_1",
        name="Implement Algorithm",
        parameters={"filepath": "src/consensus.py", "content": "def raft(): pass\n"},
    )
    result = await specialist.execute_subtask(node)
    assert result["status"] == "created"
    assert result["lines_written"] == 1


@pytest.mark.asyncio
async def test_data_analysis_specialist_computation():
    """Verify DataAnalysisSpecialist computes statistics correctly."""
    mem = SharedMemoryEngine()
    desc = AgentDescriptor(
        agent_id="spec_data_1",
        name="Data Specialist",
        role="Data Analyst",
        capabilities=[AgentCapability.DATA_ANALYSIS],
    )
    specialist = DataAnalysisSpecialist(desc, memory=mem)

    node = TaskNode(
        node_id="node_data_1",
        task_id="task_p7_1",
        name="Analyze Latencies",
        parameters={"dataset": [10.0, 20.0, 30.0, 40.0]},
    )
    result = await specialist.execute_subtask(node)
    assert result["sample_count"] == 4
    assert result["sum"] == 100.0
    assert result["mean"] == 25.0


@pytest.mark.asyncio
async def test_qa_specialist_execution():
    """Verify QASpecialist generates structured test verification report."""
    mem = SharedMemoryEngine()
    desc = AgentDescriptor(
        agent_id="spec_qa_1",
        name="QA Specialist",
        role="Quality Engineer",
        capabilities=[AgentCapability.QUALITY_ASSURANCE],
    )
    specialist = QASpecialist(desc, memory=mem)

    node = TaskNode(
        node_id="node_qa_1",
        task_id="task_p7_1",
        name="Verify Consensus Module",
        parameters={"component": "consensus_engine"},
    )
    result = await specialist.execute_subtask(node)
    assert result["verdict"] == "PASSED"
    assert result["checks_passed"] == 5


@pytest.mark.asyncio
async def test_specialist_budget_exhaustion_halts_execution():
    """Verify specialist raises AgentBudgetExhaustedError when budget caps are reached."""
    mem = SharedMemoryEngine()
    # Tiny token budget
    desc = AgentDescriptor(
        agent_id="spec_tight_budget",
        name="Budget Constrained Agent",
        role="Researcher",
        capabilities=[AgentCapability.RESEARCH],
        budget=AgentBudget(max_tokens=100, max_steps=1),
    )
    specialist = ResearchSpecialist(desc, memory=mem)

    node = TaskNode(
        node_id="node_res_budget",
        task_id="task_p7_1",
        name="Exceed Budget",
        parameters={"query": "Heavy analysis"},
    )

    with pytest.raises(AgentBudgetExhaustedError) as exc:
        await specialist.execute_subtask(node)
    assert "budget exhausted" in str(exc.value).lower()
