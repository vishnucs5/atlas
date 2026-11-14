"""Unit tests for Centralized Enterprise Agent Governance and Policy Inheritance (Milestone 3)."""

import pytest
from atlas_enterprise import (
    AgentCapabilityViolationError,
    AgentLifecycleStatus,
    AgentSelfElevationError,
    AgentSuspendedError,
    CrossTenantAccessViolationError,
    EnterpriseAgentGovernanceManager,
    EnterpriseIAMEngine,
    EnterpriseOrganizationManager,
    GovernanceScopeType,
)


@pytest.fixture
def org_manager() -> EnterpriseOrganizationManager:
    return EnterpriseOrganizationManager()


@pytest.fixture
def iam_engine(org_manager: EnterpriseOrganizationManager) -> EnterpriseIAMEngine:
    return EnterpriseIAMEngine(org_manager=org_manager)


@pytest.fixture
def gov_manager(
    org_manager: EnterpriseOrganizationManager,
    iam_engine: EnterpriseIAMEngine,
) -> EnterpriseAgentGovernanceManager:
    return EnterpriseAgentGovernanceManager(org_manager=org_manager, iam_engine=iam_engine)


def test_agent_registration_and_tenant_scoping(
    org_manager: EnterpriseOrganizationManager,
    gov_manager: EnterpriseAgentGovernanceManager,
) -> None:
    """Verify centralized agent registration, ownership attribution, and tenant boundary enforcement."""
    org_a, owner_a, _ = org_manager.create_organization(
        name="Org A", slug="orga", owner_email="a@orga.com", owner_name="Owner A"
    )
    org_b, owner_b, _ = org_manager.create_organization(
        name="Org B", slug="orgb", owner_email="b@orgb.com", owner_name="Owner B"
    )

    # Register agent in Org A
    agent = gov_manager.register_agent(
        caller_user_id=owner_a.user_id,
        org_id=org_a.org_id,
        name="DataProcessorAgent",
        owner_user_id=owner_a.user_id,
        allowed_tools=["filesystem", "read_file", "write_file"],
        allowed_skills=["data_cleaning"],
        model_constraints={"allowed_models": ["gemini-1.5-pro", "claude-3-5-sonnet"]},
    )

    assert agent.agent_id.startswith("ag_")
    assert agent.org_id == org_a.org_id
    assert agent.status == AgentLifecycleStatus.ACTIVE
    assert "filesystem" in agent.allowed_tools

    # Cross-tenant read is blocked
    with pytest.raises(CrossTenantAccessViolationError):
        gov_manager.get_agent(agent.agent_id, caller_org_id=org_b.org_id)


def test_tool_and_skill_allowlisting(
    org_manager: EnterpriseOrganizationManager,
    gov_manager: EnterpriseAgentGovernanceManager,
) -> None:
    """Verify that unallowlisted tools and skills are rejected server-side."""
    org, owner, _ = org_manager.create_organization(
        name="Alpha", slug="alpha", owner_email="owner@alpha.com", owner_name="Owner"
    )

    agent = gov_manager.register_agent(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="SafeAgent",
        owner_user_id=owner.user_id,
        allowed_tools=["browser", "http_get"],
        allowed_skills=["web_scraper"],
    )

    # Allowlisted tool succeeds
    allowed, reason, _ = gov_manager.validate_agent_execution(agent.agent_id, tool_name="browser")
    assert allowed is True
    assert reason is None

    # Unallowlisted tool rejected
    allowed, reason, _ = gov_manager.validate_agent_execution(
        agent.agent_id, tool_name="bash_command"
    )
    assert allowed is False
    assert "not in agent" in reason

    # Unallowlisted skill rejected
    allowed, reason, _ = gov_manager.validate_agent_execution(
        agent.agent_id, skill_name="arbitrary_eval"
    )
    assert allowed is False
    assert "not in agent" in reason


def test_hierarchical_policy_inheritance_and_bans(
    org_manager: EnterpriseOrganizationManager,
    gov_manager: EnterpriseAgentGovernanceManager,
) -> None:
    """Verify multi-tier policy inheritance: Org rules strictly bound Department and Team rules."""
    org, owner, _ = org_manager.create_organization(
        name="Regulated Bank", slug="bank", owner_email="admin@bank.com", owner_name="Bank Admin"
    )
    dept = org_manager.create_department(org_id=org.org_id, name="Trading", slug="trading")

    # 1. Organization policy bans raw shell execution and unapproved LLMs
    gov_manager.set_policy(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        scope_type=GovernanceScopeType.ORGANIZATION,
        scope_id=org.org_id,
        disallowed_tools=["raw_bash", "powershell_exec"],
        disallowed_models=["unvetted-open-model"],
        max_cost_per_task_usd=50.0,
    )

    # 2. Attempting to register an agent with a banned tool fails
    with pytest.raises(AgentCapabilityViolationError) as exc_info:
        gov_manager.register_agent(
            caller_user_id=owner.user_id,
            org_id=org.org_id,
            department_id=dept.department_id,
            name="RogueAgent",
            owner_user_id=owner.user_id,
            allowed_tools=["filesystem", "raw_bash"],
        )
    assert "banned tool 'raw_bash'" in str(exc_info.value)

    # 3. Department policy adds additional bans (e.g. external http)
    gov_manager.set_policy(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        scope_type=GovernanceScopeType.DEPARTMENT,
        scope_id=dept.department_id,
        disallowed_tools=["external_http"],
        max_cost_per_task_usd=25.0,
    )

    # Effective policy incorporates both Org and Dept bans
    effective = gov_manager.get_effective_policy(org.org_id, department_id=dept.department_id)
    assert "raw_bash" in effective.disallowed_tools
    assert "powershell_exec" in effective.disallowed_tools
    assert "external_http" in effective.disallowed_tools
    assert effective.max_cost_per_task_usd == 25.0  # Lowest limit wins


def test_agent_lifecycle_status(
    org_manager: EnterpriseOrganizationManager,
    gov_manager: EnterpriseAgentGovernanceManager,
) -> None:
    """Verify suspending or revoking an agent halts execution immediately."""
    org, owner, _ = org_manager.create_organization(
        name="Corp", slug="corp", owner_email="lead@corp.com", owner_name="Lead"
    )

    agent = gov_manager.register_agent(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="WorkerBot",
        owner_user_id=owner.user_id,
        allowed_tools=["calculator"],
    )

    # Active executes fine
    allowed, _, _ = gov_manager.validate_agent_execution(agent.agent_id, tool_name="calculator")
    assert allowed is True

    # Suspend agent
    gov_manager.update_agent_status(
        caller_user_id=owner.user_id,
        agent_id=agent.agent_id,
        new_status=AgentLifecycleStatus.SUSPENDED,
        reason="Security audit in progress",
    )

    with pytest.raises(AgentSuspendedError):
        gov_manager.validate_agent_execution(agent.agent_id, tool_name="calculator")


def test_agent_self_elevation_prevention(
    gov_manager: EnterpriseAgentGovernanceManager,
) -> None:
    """Verify agents cannot invoke IAM, role assignment, or policy modification routines."""
    agent_id = "ag_autonomous_worker_123"

    # Permitted non-administrative action
    gov_manager.check_agent_self_elevation(agent_id, "data:process")

    # Prohibited self-elevation actions
    with pytest.raises(AgentSelfElevationError):
        gov_manager.check_agent_self_elevation(agent_id, "iam:manage_roles")

    with pytest.raises(AgentSelfElevationError):
        gov_manager.check_agent_self_elevation(agent_id, "policy:update")

    with pytest.raises(AgentSelfElevationError):
        gov_manager.check_agent_self_elevation(agent_id, "agent:elevate")


def test_spending_limits_and_dual_custody_triggers(
    org_manager: EnterpriseOrganizationManager,
    gov_manager: EnterpriseAgentGovernanceManager,
) -> None:
    """Verify budget limits and tools requiring dual-custody approval."""
    org, owner, _ = org_manager.create_organization(
        name="FinCorp", slug="fincorp", owner_email="cfo@fincorp.com", owner_name="CFO"
    )

    gov_manager.set_policy(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        scope_type=GovernanceScopeType.ORGANIZATION,
        scope_id=org.org_id,
        require_approval_for_tools=["wire_transfer", "production_db_write"],
        max_cost_per_task_usd=100.0,
    )

    agent = gov_manager.register_agent(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        name="FinanceBot",
        owner_user_id=owner.user_id,
        allowed_tools=["wire_transfer", "balance_check"],
    )

    # 1. Normal tool execution without dual custody
    allowed, _, requires_dc = gov_manager.validate_agent_execution(
        agent.agent_id, tool_name="balance_check", estimated_cost_usd=5.0
    )
    assert allowed is True
    assert requires_dc is False

    # 2. Critical tool triggers dual custody
    allowed, _, requires_dc = gov_manager.validate_agent_execution(
        agent.agent_id, tool_name="wire_transfer", estimated_cost_usd=10.0
    )
    assert allowed is True
    assert requires_dc is True

    # 3. Cost exceeding budget limit is denied
    allowed, reason, _ = gov_manager.validate_agent_execution(
        agent.agent_id, tool_name="balance_check", estimated_cost_usd=150.0
    )
    assert allowed is False
    assert "exceeds task limit" in reason
