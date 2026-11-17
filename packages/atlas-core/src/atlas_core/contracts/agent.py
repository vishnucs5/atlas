"""Agent identity, capabilities, budgets, leases, and lifecycle contracts."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentCapability(StrEnum):
    """Declared capabilities supported by ATLAS specialist agents."""

    RESEARCH = "RESEARCH"
    BROWSER = "BROWSER"
    DESKTOP = "DESKTOP"
    CODE = "CODE"
    DATA_ANALYSIS = "DATA_ANALYSIS"
    QUALITY_ASSURANCE = "QUALITY_ASSURANCE"
    SUPERVISOR = "SUPERVISOR"
    GENERAL = "GENERAL"

    # Specialist Engineering Capabilities (Stage 5)
    ARCHITECT = "ARCHITECT"
    EXPLORER = "EXPLORER"
    BACKEND = "BACKEND"
    FRONTEND = "FRONTEND"
    DATABASE = "DATABASE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    TESTING = "TESTING"
    SECURITY_AUDITOR = "SECURITY_AUDITOR"
    CODE_REVIEWER = "CODE_REVIEWER"
    DOCUMENTATION = "DOCUMENTATION"
    DEBUGGING = "DEBUGGING"


class AgentStatus(StrEnum):
    """Lifecycle availability status for an agent instance."""

    INITIALIZING = "INITIALIZING"
    IDLE = "IDLE"
    BUSY = "BUSY"
    UNHEALTHY = "UNHEALTHY"
    TERMINATED = "TERMINATED"


class AgentBudget(BaseModel):
    """Resource consumption envelope and caps for an agent."""

    model_config = ConfigDict(validate_assignment=True)

    max_tokens: int = 100_000
    tokens_used: int = 0
    max_cost_usd: float = 10.0
    cost_usd_used: float = 0.0
    max_steps: int = 50
    steps_used: int = 0

    def is_exhausted(self) -> bool:
        """Evaluate if any consumption threshold has been breached."""
        if self.tokens_used >= self.max_tokens:
            return True
        if self.cost_usd_used >= self.max_cost_usd:
            return True
        if self.steps_used >= self.max_steps:
            return True
        return False

    def record_usage(self, tokens: int = 0, cost_usd: float = 0.0, steps: int = 1) -> None:
        """Increment resource consumption metrics."""
        self.tokens_used += max(0, tokens)
        self.cost_usd_used += max(0.0, cost_usd)
        self.steps_used += max(0, steps)


class AgentDescriptor(BaseModel):
    """Formal registration and capability record for an agent in ATLAS."""

    model_config = ConfigDict(validate_assignment=True)

    agent_id: str
    name: str
    role: str
    capabilities: list[AgentCapability] = Field(default_factory=list)
    model_family: str = "fallback"
    model_name: str = "hermetic-default"
    status: AgentStatus = AgentStatus.IDLE
    budget: AgentBudget = Field(default_factory=AgentBudget)
    max_concurrency: int = 1
    current_task_count: int = 0
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_heartbeat_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"

    def has_capability(self, capability: AgentCapability) -> bool:
        """Check if this agent provides the specified capability."""
        return capability in self.capabilities or AgentCapability.GENERAL in self.capabilities


class AgentLease(BaseModel):
    """Exclusive assignment lease granted to an agent for executing a specific task node."""

    model_config = ConfigDict(validate_assignment=True)

    lease_id: str
    agent_id: str
    task_id: str
    node_id: str
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    fencing_token: int = 1
    schema_version: str = "1.0"

    def is_expired(self, now: datetime | None = None) -> bool:
        """Check whether the lease has expired past the deadline."""
        current_time = now or datetime.now(UTC)
        return current_time > self.expires_at

    def renew(self, ttl_seconds: float = 60.0) -> "AgentLease":
        """Extend lease duration and increment fencing token."""
        now = datetime.now(UTC)
        self.expires_at = now + timedelta(seconds=ttl_seconds)
        self.fencing_token += 1
        return self
