"""AgentRegistry managing agent lifecycle, capabilities, availability, leases, and budgets."""

import threading
import uuid
from datetime import UTC, datetime, timedelta

from atlas_core.contracts.agent import (
    AgentCapability,
    AgentDescriptor,
    AgentLease,
    AgentStatus,
)


class AgentNotFoundError(Exception):
    """Raised when an operation references an unregistered agent."""


class AgentUnavailableError(Exception):
    """Raised when an agent cannot accept a lease due to status, concurrency, or budget limits."""


class AgentBudgetExhaustedError(Exception):
    """Raised when an operation would exceed an agent's allocated resource budget."""


class AgentRegistry:
    """Thread-safe registry for agent lifecycle management and resource governance."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._agents: dict[str, AgentDescriptor] = {}
        self._leases: dict[str, AgentLease] = {}

    def register_agent(self, descriptor: AgentDescriptor) -> AgentDescriptor:
        """Register a new agent or update an existing registration."""
        with self._lock:
            now = datetime.now(UTC)
            descriptor.last_heartbeat_at = now
            self._agents[descriptor.agent_id] = descriptor
            return descriptor

    def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent and cancel any active leases."""
        with self._lock:
            if agent_id not in self._agents:
                return False
            agent = self._agents[agent_id]
            agent.status = AgentStatus.TERMINATED
            # Clean up active leases for this agent
            active_lease_ids = [
                lid for lid, lease in self._leases.items() if lease.agent_id == agent_id
            ]
            for lid in active_lease_ids:
                del self._leases[lid]
            del self._agents[agent_id]
            return True

    def get_agent(self, agent_id: str) -> AgentDescriptor | None:
        """Fetch agent descriptor by ID."""
        with self._lock:
            return self._agents.get(agent_id)

    def list_agents(
        self,
        capability: AgentCapability | None = None,
        status: AgentStatus | None = None,
    ) -> list[AgentDescriptor]:
        """List agents, optionally filtering by capability and lifecycle status."""
        with self._lock:
            results: list[AgentDescriptor] = []
            for agent in self._agents.values():
                if status and agent.status != status:
                    continue
                if capability and not agent.has_capability(capability):
                    continue
                results.append(agent)
            return results

    def heartbeat(self, agent_id: str) -> None:
        """Record a heartbeat timestamp for an active agent."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                raise AgentNotFoundError(f"Agent '{agent_id}' is not registered.")
            now = datetime.now(UTC)
            agent.last_heartbeat_at = now
            if agent.status == AgentStatus.UNHEALTHY:
                agent.status = (
                    AgentStatus.IDLE if agent.current_task_count == 0 else AgentStatus.BUSY
                )

    def check_health(self, timeout_seconds: float = 30.0) -> list[str]:
        """Check all registered agents for overdue heartbeats and mark them UNHEALTHY."""
        with self._lock:
            now = datetime.now(UTC)
            unhealthy_agents: list[str] = []
            for agent in self._agents.values():
                if agent.status in (AgentStatus.TERMINATED, AgentStatus.INITIALIZING):
                    continue
                age = (now - agent.last_heartbeat_at).total_seconds()
                if age > timeout_seconds:
                    agent.status = AgentStatus.UNHEALTHY
                    unhealthy_agents.append(agent.agent_id)
            return unhealthy_agents

    def find_available_agent(
        self,
        required_capabilities: list[AgentCapability] | None = None,
        min_tokens_remaining: int = 1000,
    ) -> AgentDescriptor | None:
        """Find an idle or available agent that matches all capabilities and has budget."""
        with self._lock:
            candidates: list[AgentDescriptor] = []
            for agent in self._agents.values():
                if agent.status not in (AgentStatus.IDLE, AgentStatus.BUSY):
                    continue
                if agent.current_task_count >= agent.max_concurrency:
                    continue
                if agent.budget.is_exhausted():
                    continue
                remaining_tokens = agent.budget.max_tokens - agent.budget.tokens_used
                if remaining_tokens < min_tokens_remaining:
                    continue

                # Check all required capabilities
                if required_capabilities:
                    if not all(agent.has_capability(cap) for cap in required_capabilities):
                        continue
                candidates.append(agent)

            if not candidates:
                return None

            # Sort by least utilization
            candidates.sort(key=lambda a: (a.current_task_count, a.budget.tokens_used))
            return candidates[0]

    def acquire_agent_lease(
        self,
        agent_id: str,
        task_id: str,
        node_id: str,
        ttl_seconds: float = 60.0,
    ) -> AgentLease:
        """Acquire an exclusive execution lease for a specific task node."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                raise AgentNotFoundError(f"Agent '{agent_id}' is not registered.")
            if agent.status in (AgentStatus.UNHEALTHY, AgentStatus.TERMINATED):
                raise AgentUnavailableError(
                    f"Agent '{agent_id}' is in non-executable state '{agent.status.value}'."
                )
            if agent.current_task_count >= agent.max_concurrency:
                raise AgentUnavailableError(
                    f"Agent '{agent_id}' has reached concurrency limit ({agent.max_concurrency})."
                )
            if agent.budget.is_exhausted():
                raise AgentBudgetExhaustedError(
                    f"Agent '{agent_id}' resource budget has been exhausted."
                )

            now = datetime.now(UTC)
            lease_id = f"lease_{uuid.uuid4().hex[:12]}"
            lease = AgentLease(
                lease_id=lease_id,
                agent_id=agent_id,
                task_id=task_id,
                node_id=node_id,
                acquired_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
                fencing_token=1,
            )
            self._leases[lease_id] = lease
            agent.current_task_count += 1
            agent.status = AgentStatus.BUSY
            return lease

    def renew_agent_lease(self, lease_id: str, ttl_seconds: float = 60.0) -> AgentLease:
        """Renew an active agent lease."""
        with self._lock:
            lease = self._leases.get(lease_id)
            if not lease:
                raise KeyError(f"Agent lease '{lease_id}' not found.")
            lease.renew(ttl_seconds)
            return lease

    def release_agent_lease(self, lease_id: str) -> bool:
        """Release an agent lease and decrement concurrent task load."""
        with self._lock:
            lease = self._leases.pop(lease_id, None)
            if not lease:
                return False
            agent = self._agents.get(lease.agent_id)
            if agent:
                agent.current_task_count = max(0, agent.current_task_count - 1)
                if agent.current_task_count == 0 and agent.status == AgentStatus.BUSY:
                    agent.status = AgentStatus.IDLE
            return True

    def get_lease(self, lease_id: str) -> AgentLease | None:
        """Retrieve lease by ID."""
        with self._lock:
            return self._leases.get(lease_id)

    def record_agent_usage(
        self,
        agent_id: str,
        tokens: int = 0,
        cost_usd: float = 0.0,
        steps: int = 1,
    ) -> None:
        """Record resource usage against an agent's allocated budget."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                raise AgentNotFoundError(f"Agent '{agent_id}' is not registered.")
            agent.budget.record_usage(tokens=tokens, cost_usd=cost_usd, steps=steps)
            if agent.budget.is_exhausted() and agent.status == AgentStatus.IDLE:
                agent.status = AgentStatus.UNHEALTHY
