"""Unit tests verifying AgentDescriptor contracts, budgets, and AgentRegistry lifecycle management."""

from datetime import UTC, datetime, timedelta

import pytest
from atlas_core.contracts.agent import (
    AgentBudget,
    AgentCapability,
    AgentDescriptor,
    AgentStatus,
)
from atlas_orchestration.registry import (
    AgentBudgetExhaustedError,
    AgentRegistry,
    AgentUnavailableError,
)


def test_agent_budget_exhaustion():
    """Verify AgentBudget tracks metrics and correctly reports exhaustion thresholds."""
    budget = AgentBudget(max_tokens=1000, max_cost_usd=5.0, max_steps=10)
    assert budget.is_exhausted() is False

    budget.record_usage(tokens=500, cost_usd=1.0, steps=2)
    assert budget.tokens_used == 500
    assert budget.cost_usd_used == 1.0
    assert budget.steps_used == 2
    assert budget.is_exhausted() is False

    # Exceed tokens
    budget.record_usage(tokens=600)
    assert budget.is_exhausted() is True


def test_agent_descriptor_capabilities():
    """Verify AgentDescriptor capability lookup and general wildcard match."""
    specialist = AgentDescriptor(
        agent_id="agent_res_1",
        name="Research Specialist",
        role="Researcher",
        capabilities=[AgentCapability.RESEARCH, AgentCapability.DATA_ANALYSIS],
    )
    assert specialist.has_capability(AgentCapability.RESEARCH) is True
    assert specialist.has_capability(AgentCapability.DATA_ANALYSIS) is True
    assert specialist.has_capability(AgentCapability.CODE) is False

    generalist = AgentDescriptor(
        agent_id="agent_gen_1",
        name="General Agent",
        role="Generalist",
        capabilities=[AgentCapability.GENERAL],
    )
    assert generalist.has_capability(AgentCapability.CODE) is True
    assert generalist.has_capability(AgentCapability.BROWSER) is True


def test_agent_registry_crud_and_filters():
    """Verify registering, retrieving, filtering, and unregistering agents."""
    reg = AgentRegistry()

    a1 = AgentDescriptor(
        agent_id="agent_browser_1",
        name="Browser Specialist",
        role="Web Navigator",
        capabilities=[AgentCapability.BROWSER],
        model_family="openai",
        model_name="gpt-4o",
    )
    a2 = AgentDescriptor(
        agent_id="agent_code_1",
        name="Coding Specialist",
        role="Code Engineer",
        capabilities=[AgentCapability.CODE],
        model_family="anthropic",
        model_name="claude-3-5-sonnet-20241022",
    )

    reg.register_agent(a1)
    reg.register_agent(a2)

    # Retrieval
    assert reg.get_agent("agent_browser_1") is not None
    assert reg.get_agent("agent_unknown") is None

    # Filtering by capability
    browser_agents = reg.list_agents(capability=AgentCapability.BROWSER)
    assert len(browser_agents) == 1
    assert browser_agents[0].agent_id == "agent_browser_1"

    code_agents = reg.list_agents(capability=AgentCapability.CODE)
    assert len(code_agents) == 1
    assert code_agents[0].agent_id == "agent_code_1"

    # Unregister
    assert reg.unregister_agent("agent_browser_1") is True
    assert reg.get_agent("agent_browser_1") is None
    assert len(reg.list_agents()) == 1


def test_agent_heartbeat_and_health_monitoring():
    """Verify stale heartbeats transition agents to UNHEALTHY status."""
    reg = AgentRegistry()
    now = datetime.now(UTC)

    stale_agent = AgentDescriptor(
        agent_id="stale_agent_1",
        name="Stale Specialist",
        role="Researcher",
        capabilities=[AgentCapability.RESEARCH],
        last_heartbeat_at=now - timedelta(seconds=60),
    )
    fresh_agent = AgentDescriptor(
        agent_id="fresh_agent_1",
        name="Fresh Specialist",
        role="Researcher",
        capabilities=[AgentCapability.RESEARCH],
        last_heartbeat_at=now,
    )

    reg.register_agent(stale_agent)
    reg.register_agent(fresh_agent)
    # Manually backdate stale agent heartbeat for deterministic test
    reg._agents["stale_agent_1"].last_heartbeat_at = now - timedelta(seconds=60)

    unhealthy = reg.check_health(timeout_seconds=30.0)
    assert unhealthy == ["stale_agent_1"]
    assert reg.get_agent("stale_agent_1").status == AgentStatus.UNHEALTHY
    assert reg.get_agent("fresh_agent_1").status == AgentStatus.IDLE

    # Heartbeat recovers unhealthy agent
    reg.heartbeat("stale_agent_1")
    assert reg.get_agent("stale_agent_1").status == AgentStatus.IDLE


def test_find_available_agent_matching():
    """Verify capability-based discovery and least-utilization ordering."""
    reg = AgentRegistry()

    busy_agent = AgentDescriptor(
        agent_id="busy_1",
        name="Busy Agent",
        role="Coder",
        capabilities=[AgentCapability.CODE],
        max_concurrency=1,
        current_task_count=1,
        status=AgentStatus.BUSY,
    )
    available_agent = AgentDescriptor(
        agent_id="avail_1",
        name="Available Agent",
        role="Coder",
        capabilities=[AgentCapability.CODE],
        max_concurrency=2,
        current_task_count=0,
        status=AgentStatus.IDLE,
    )

    reg.register_agent(busy_agent)
    reg.register_agent(available_agent)

    # Should select available_agent since busy_agent has reached concurrency limit
    chosen = reg.find_available_agent(required_capabilities=[AgentCapability.CODE])
    assert chosen is not None
    assert chosen.agent_id == "avail_1"

    # Searching for non-existent capability returns None
    assert reg.find_available_agent(required_capabilities=[AgentCapability.DESKTOP]) is None


def test_agent_lease_lifecycle_and_fencing():
    """Verify exclusive lease acquisition, renewal with fencing tokens, and clean release."""
    reg = AgentRegistry()

    agent = AgentDescriptor(
        agent_id="worker_agent_1",
        name="Leased Worker",
        role="Worker",
        capabilities=[AgentCapability.RESEARCH],
        max_concurrency=1,
    )
    reg.register_agent(agent)

    # 1. Acquire lease
    lease = reg.acquire_agent_lease(
        agent_id="worker_agent_1",
        task_id="parent_task_1",
        node_id="subtask_node_1",
        ttl_seconds=30.0,
    )
    assert lease.agent_id == "worker_agent_1"
    assert lease.fencing_token == 1
    assert lease.is_expired() is False
    assert reg.get_agent("worker_agent_1").status == AgentStatus.BUSY

    # 2. Concurrency limit prevents second concurrent lease
    with pytest.raises(AgentUnavailableError) as exc:
        reg.acquire_agent_lease(
            agent_id="worker_agent_1",
            task_id="parent_task_1",
            node_id="subtask_node_2",
        )
    assert "concurrency limit" in str(exc.value).lower()

    # 3. Renew lease increments fencing token
    renewed = reg.renew_agent_lease(lease.lease_id, ttl_seconds=60.0)
    assert renewed.fencing_token == 2

    # 4. Release lease returns agent to IDLE
    assert reg.release_agent_lease(lease.lease_id) is True
    assert reg.get_agent("worker_agent_1").status == AgentStatus.IDLE
    assert reg.get_agent("worker_agent_1").current_task_count == 0


def test_agent_budget_exhaustion_blocks_lease():
    """Verify exhausted budget prohibits lease acquisition."""
    reg = AgentRegistry()

    exhausted_budget = AgentBudget(max_tokens=100, tokens_used=100)
    agent = AgentDescriptor(
        agent_id="budget_exhausted_1",
        name="Broke Agent",
        role="Researcher",
        capabilities=[AgentCapability.RESEARCH],
        budget=exhausted_budget,
    )
    reg.register_agent(agent)

    with pytest.raises(AgentBudgetExhaustedError):
        reg.acquire_agent_lease(
            agent_id="budget_exhausted_1",
            task_id="task_1",
            node_id="node_1",
        )
