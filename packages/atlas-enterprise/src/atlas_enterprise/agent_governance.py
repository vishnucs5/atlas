"""Enterprise Agent Governance, Centralized Registry, and Hierarchical Policy Inheritance."""

import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atlas_enterprise.iam import (
    AgentSelfElevationError as _IAMAgentSelfElevationError,
)
from atlas_enterprise.iam import (
    EnterpriseIAMEngine,
)
from atlas_enterprise.models import (
    AgentLifecycleStatus,
    EnterpriseAgentRecord,
    EnterprisePolicyEnvelope,
    GovernanceScopeType,
    PermissionAction,
)
from atlas_enterprise.organization import (
    CrossTenantAccessViolationError,
    EnterpriseOrganizationManager,
)

logger = logging.getLogger("atlas.enterprise.agent_governance")


class EnterpriseAgentGovernanceError(Exception):
    """Base exception for agent governance failures."""


class AgentNotFoundError(EnterpriseAgentGovernanceError):
    """Raised when an enterprise agent cannot be located."""


class AgentSuspendedError(EnterpriseAgentGovernanceError):
    """Raised when an agent is suspended or revoked from execution."""


class AgentCapabilityViolationError(EnterpriseAgentGovernanceError):
    """Raised when an agent attempts to execute an unallowlisted or forbidden tool/skill."""


class AgentSelfElevationError(_IAMAgentSelfElevationError, EnterpriseAgentGovernanceError):
    """Raised when an autonomous agent attempts to elevate privileges or modify security policy."""


class PolicyConflictResolutionError(EnterpriseAgentGovernanceError):
    """Raised when an inherited policy conflict cannot be resolved deterministically."""


class EffectivePolicy(BaseModel):
    """Resolved hierarchical policy combining Organization -> Department -> Team constraints."""

    model_config = ConfigDict(validate_assignment=True)

    org_id: str
    department_id: str | None = None
    team_id: str | None = None
    disallowed_tools: set[str] = Field(default_factory=set)
    disallowed_skills: set[str] = Field(default_factory=set)
    disallowed_models: set[str] = Field(default_factory=set)
    require_approval_for_tools: set[str] = Field(default_factory=set)
    require_dual_custody: bool = False
    max_cost_per_task_usd: float = 100.0
    rules: list[dict[str, Any]] = Field(default_factory=list)


# Actions that autonomous agents are strictly forbidden from executing (Self-Elevation Guard)
RESTRICTED_AGENT_ACTIONS: set[str] = {
    "iam:manage_roles",
    "iam:manage_policy",
    "iam:manage_credentials",
    "org:delete",
    "org:update",
    "policy:update",
    "permission:grant",
    "role:assign",
    "token:mint",
    "agent:elevate",
}


class EnterpriseAgentGovernanceManager:
    """Centralized governance for enterprise AI agents, allowlists, and policy inheritance."""

    def __init__(
        self,
        org_manager: EnterpriseOrganizationManager,
        iam_engine: EnterpriseIAMEngine,
        storage: Any = None,
    ) -> None:
        self.org_manager = org_manager
        self.iam_engine = iam_engine
        self.storage = storage or getattr(org_manager, "storage", None)
        self._lock = threading.RLock()
        self._agents: dict[str, EnterpriseAgentRecord] = {}
        self._policies: dict[str, EnterprisePolicyEnvelope] = {}  # scope_id -> Envelope

    # -------------------------------------------------------------------------
    # Centralized Agent Registration & Lifecycle
    # -------------------------------------------------------------------------

    def register_agent(
        self,
        caller_user_id: str,
        org_id: str,
        name: str,
        owner_user_id: str,
        allowed_tools: list[str],
        allowed_skills: list[str] | None = None,
        allowed_workflows: list[str] | None = None,
        model_constraints: dict[str, Any] | None = None,
        resource_limits: dict[str, Any] | None = None,
        department_id: str | None = None,
        team_id: str | None = None,
        version: str = "1.0.0",
        description: str = "",
    ) -> EnterpriseAgentRecord:
        """Register a new enterprise agent with explicit ownership, toolchains, and model boundaries."""
        with self._lock:
            # 1. Verify caller permission
            self.iam_engine.assert_permission(
                user_id=caller_user_id,
                org_id=org_id,
                action=PermissionAction.AGENT_REGISTER,
            )

            # 2. Verify effective policy does not ban any requested tools/skills
            effective = self.get_effective_policy(org_id, department_id, team_id)
            for tool in allowed_tools:
                if tool in effective.disallowed_tools:
                    raise AgentCapabilityViolationError(
                        f"Cannot register agent with banned tool '{tool}' under organization policy"
                    )

            if allowed_skills:
                for skill in allowed_skills:
                    if skill in effective.disallowed_skills:
                        raise AgentCapabilityViolationError(
                            f"Cannot register agent with banned skill '{skill}' under organization policy"
                        )

            agent_id = f"ag_{uuid.uuid4().hex[:12]}"
            agent = EnterpriseAgentRecord(
                agent_id=agent_id,
                org_id=org_id,
                department_id=department_id,
                team_id=team_id,
                name=name,
                description=description,
                version=version,
                owner_user_id=owner_user_id,
                status=AgentLifecycleStatus.ACTIVE,
                model_constraints=model_constraints or {},
                allowed_tools=list(set(allowed_tools)),
                allowed_skills=list(set(allowed_skills or [])),
                allowed_workflows=list(set(allowed_workflows or [])),
                resource_limits=resource_limits or {},
            )

            self._agents[agent_id] = agent
            self.org_manager.register_agent_tenancy(agent_id, org_id)
            if self.storage:
                self.storage.save_agent(agent)
            logger.info("Registered enterprise agent %s (%s) in org %s", name, agent_id, org_id)
            return agent

    def get_agent(self, agent_id: str, caller_org_id: str | None = None) -> EnterpriseAgentRecord:
        """Retrieve agent metadata, asserting tenant boundary."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if not agent and self.storage:
                agent = self.storage.get_agent(agent_id)
                if agent:
                    self._agents[agent.agent_id] = agent
                    self.org_manager.register_agent_tenancy(agent.agent_id, agent.org_id)
            if not agent:
                raise AgentNotFoundError(f"Agent '{agent_id}' not found")

            if caller_org_id and caller_org_id != agent.org_id:
                raise CrossTenantAccessViolationError(
                    f"Cross-tenant access violation: caller {caller_org_id} != agent org {agent.org_id}"
                )

            return agent

    def update_agent_status(
        self,
        caller_user_id: str,
        agent_id: str,
        new_status: AgentLifecycleStatus,
        reason: str = "",
    ) -> EnterpriseAgentRecord:
        """Update agent status (e.g. SUSPEND or REVOKE)."""
        with self._lock:
            agent = self.get_agent(agent_id)
            self.iam_engine.assert_permission(
                user_id=caller_user_id,
                org_id=agent.org_id,
                action=PermissionAction.AGENT_UPDATE,
            )

            agent.status = new_status
            agent.updated_at = datetime.now(UTC)
            logger.warning(
                "Updated agent %s status to %s by %s. Reason: %s",
                agent_id,
                new_status,
                caller_user_id,
                reason,
            )
            return agent

    # -------------------------------------------------------------------------
    # Hierarchical Policy Management & Inheritance
    # -------------------------------------------------------------------------

    def set_policy(
        self,
        caller_user_id: str,
        org_id: str,
        scope_type: GovernanceScopeType,
        scope_id: str,
        disallowed_tools: list[str] | None = None,
        disallowed_skills: list[str] | None = None,
        disallowed_models: list[str] | None = None,
        require_approval_for_tools: list[str] | None = None,
        require_dual_custody: bool = False,
        max_cost_per_task_usd: float = 100.0,
        rules: list[dict[str, Any]] | None = None,
    ) -> EnterprisePolicyEnvelope:
        """Set a governance policy envelope at Organization, Department, or Team scope."""
        with self._lock:
            # Self-Elevation Guard: Non-human identities (agents, workers, service identities) cannot modify policies
            self.check_agent_self_elevation(caller_user_id, "policy:update")

            self.iam_engine.assert_permission(
                user_id=caller_user_id,
                org_id=org_id,
                action=PermissionAction.IAM_MANAGE_POLICY,
            )

            # Enforce hierarchy bounds: department or team policy cannot relax organization rules
            if scope_type in (GovernanceScopeType.DEPARTMENT, GovernanceScopeType.TEAM):
                org_policy = self.get_policy(org_id)
                if org_policy:
                    # Check spending cap: cannot exceed organization ceiling
                    if max_cost_per_task_usd > org_policy.max_cost_per_task_usd:
                        raise PolicyConflictResolutionError(
                            f"Child scope budget ({max_cost_per_task_usd}) cannot exceed Organization limit ({org_policy.max_cost_per_task_usd})"
                        )

            policy_id = f"pol_{uuid.uuid4().hex[:12]}"
            envelope = EnterprisePolicyEnvelope(
                policy_id=policy_id,
                org_id=org_id,
                scope_type=scope_type,
                scope_id=scope_id,
                disallowed_tools=disallowed_tools or [],
                disallowed_skills=disallowed_skills or [],
                disallowed_models=disallowed_models or [],
                require_approval_for_tools=require_approval_for_tools or [],
                require_dual_custody=require_dual_custody,
                max_cost_per_task_usd=max_cost_per_task_usd,
                rules=rules or [],
                is_active=True,
            )

            self._policies[scope_id] = envelope
            if self.storage:
                self.storage.save_policy(envelope)
            logger.info("Configured policy %s for %s (%s)", policy_id, scope_type, scope_id)
            return envelope

    def get_policy(self, scope_id: str) -> EnterprisePolicyEnvelope | None:
        """Retrieve policy envelope by scope ID."""
        with self._lock:
            pol = self._policies.get(scope_id)
            if not pol and self.storage:
                pol = self.storage.get_policy(scope_id)
                if pol:
                    self._policies[pol.scope_id] = pol
            return pol

    def get_effective_policy(
        self,
        org_id: str,
        department_id: str | None = None,
        team_id: str | None = None,
    ) -> EffectivePolicy:
        """Compute the deterministic effective policy by inheriting down Org -> Dept -> Team."""
        with self._lock:
            effective = EffectivePolicy(
                org_id=org_id,
                department_id=department_id,
                team_id=team_id,
            )

            # 1. Organization level (authoritative baseline)
            org_pol = self.get_policy(org_id)
            if org_pol and org_pol.is_active:
                effective.disallowed_tools.update(org_pol.disallowed_tools)
                effective.disallowed_skills.update(org_pol.disallowed_skills)
                effective.disallowed_models.update(org_pol.disallowed_models)
                effective.require_approval_for_tools.update(org_pol.require_approval_for_tools)
                effective.require_dual_custody = (
                    effective.require_dual_custody or org_pol.require_dual_custody
                )
                effective.max_cost_per_task_usd = min(
                    effective.max_cost_per_task_usd, org_pol.max_cost_per_task_usd
                )
                effective.rules.extend(org_pol.rules)

            # 2. Department level (can add restrictions, cannot relax org constraints)
            if department_id:
                dept_pol = self.get_policy(department_id)
                if dept_pol and dept_pol.is_active:
                    effective.disallowed_tools.update(dept_pol.disallowed_tools)
                    effective.disallowed_skills.update(dept_pol.disallowed_skills)
                    effective.disallowed_models.update(dept_pol.disallowed_models)
                    effective.require_approval_for_tools.update(dept_pol.require_approval_for_tools)
                    effective.require_dual_custody = (
                        effective.require_dual_custody or dept_pol.require_dual_custody
                    )
                    effective.max_cost_per_task_usd = min(
                        effective.max_cost_per_task_usd, dept_pol.max_cost_per_task_usd
                    )
                    effective.rules.extend(dept_pol.rules)

            # 3. Team level (can further restrict, cannot relax parent constraints)
            if team_id:
                team_pol = self.get_policy(team_id)
                if team_pol and team_pol.is_active:
                    effective.disallowed_tools.update(team_pol.disallowed_tools)
                    effective.disallowed_skills.update(team_pol.disallowed_skills)
                    effective.disallowed_models.update(team_pol.disallowed_models)
                    effective.require_approval_for_tools.update(team_pol.require_approval_for_tools)
                    effective.require_dual_custody = (
                        effective.require_dual_custody or team_pol.require_dual_custody
                    )
                    effective.max_cost_per_task_usd = min(
                        effective.max_cost_per_task_usd, team_pol.max_cost_per_task_usd
                    )
                    effective.rules.extend(team_pol.rules)

            return effective

    # -------------------------------------------------------------------------
    # Server-Side Agent Execution Validation & ActionFirewall Bridging
    # -------------------------------------------------------------------------

    def validate_agent_execution(
        self,
        agent_id: str,
        tool_name: str | None = None,
        skill_name: str | None = None,
        model_name: str | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> tuple[bool, str | None, bool]:
        """Validate agent execution against status, allowlists, and hierarchical policies.

        Returns (is_allowed, denial_reason, requires_dual_custody).
        """
        with self._lock:
            agent = self.get_agent(agent_id)

            # 1. Lifecycle check
            if agent.status != AgentLifecycleStatus.ACTIVE:
                raise AgentSuspendedError(
                    f"Agent '{agent_id}' is {agent.status} and cannot execute actions"
                )

            # 2. Get effective policy
            effective = self.get_effective_policy(
                org_id=agent.org_id,
                department_id=agent.department_id,
                team_id=agent.team_id,
            )

            # 3. Tool allowlist and ban checks
            if tool_name:
                if tool_name not in agent.allowed_tools:
                    return (
                        False,
                        f"Tool '{tool_name}' is not in agent '{agent_id}' allowlisted tools",
                        False,
                    )
                if tool_name in effective.disallowed_tools:
                    return (
                        False,
                        f"Tool '{tool_name}' is forbidden by effective enterprise policy",
                        False,
                    )

            # 4. Skill allowlist and ban checks
            if skill_name:
                if skill_name not in agent.allowed_skills:
                    return (
                        False,
                        f"Skill '{skill_name}' is not in agent '{agent_id}' allowlisted skills",
                        False,
                    )
                if skill_name in effective.disallowed_skills:
                    return (
                        False,
                        f"Skill '{skill_name}' is forbidden by effective enterprise policy",
                        False,
                    )

            # 5. Model constraints check
            if model_name:
                allowed_models = agent.model_constraints.get("allowed_models", [])
                if allowed_models and model_name not in allowed_models:
                    return (
                        False,
                        f"Model '{model_name}' violates agent model constraints {allowed_models}",
                        False,
                    )
                if model_name in effective.disallowed_models:
                    return (
                        False,
                        f"Model '{model_name}' is forbidden by effective enterprise policy",
                        False,
                    )

            # 6. Cost limit check
            if estimated_cost_usd > effective.max_cost_per_task_usd:
                return (
                    False,
                    f"Estimated cost ${estimated_cost_usd:.2f} exceeds task limit ${effective.max_cost_per_task_usd:.2f}",
                    False,
                )

            # 7. Check if dual custody or approval is required
            requires_dual_custody = effective.require_dual_custody
            if tool_name and tool_name in effective.require_approval_for_tools:
                requires_dual_custody = True

            return True, None, requires_dual_custody

    # -------------------------------------------------------------------------
    # Agent Privilege Self-Elevation Guard
    # -------------------------------------------------------------------------

    def check_agent_self_elevation(self, caller_id: str, action: str) -> None:
        """Prevent autonomous agents or worker identities from granting permissions or modifying policies."""
        if (
            caller_id.startswith("ag_")
            or caller_id.startswith("worker_")
            or caller_id.startswith("svc_")
        ):
            if (
                action in RESTRICTED_AGENT_ACTIONS
                or action.startswith("iam:")
                or action.startswith("policy:")
            ):
                error_msg = (
                    f"Agent Self-Elevation Guard Triggered: Non-human identity '{caller_id}' "
                    f"attempted prohibited action '{action}'"
                )
                logger.critical(error_msg)
                raise AgentSelfElevationError(error_msg)
