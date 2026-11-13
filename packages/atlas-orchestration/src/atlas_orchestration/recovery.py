"""MultiAgentRecoveryManager providing agent crash detection, subtask reassignment, and side-effect reconciliation."""

import logging
import threading
from datetime import UTC, datetime

from atlas_coordination.action_ledger import NonIdempotentActionUncertaintyError
from atlas_core.contracts.graph import NodeStatus

from atlas_orchestration.graph_engine import TaskGraphEngine
from atlas_orchestration.registry import (
    AgentDescriptor,
    AgentLease,
    AgentRegistry,
    AgentStatus,
    AgentUnavailableError,
)

logger = logging.getLogger("atlas.orchestration.recovery")


class MultiAgentRecoveryManager:
    """Coordinates crash recovery, lease expiration eviction, safe reassignment, and side-effect gating."""

    def __init__(self, registry: AgentRegistry) -> None:
        self._lock = threading.RLock()
        self.registry = registry

    def check_and_evict_expired_leases(self) -> list[AgentLease]:
        """Scan active leases, evict expired ones, and mark responsible agents UNHEALTHY."""
        with self._lock:
            now = datetime.now(UTC)
            expired_leases: list[AgentLease] = []

            for lease_id, lease in list(self.registry._leases.items()):
                if lease.is_expired(now):
                    expired_leases.append(lease)
                    # Mark agent unhealthy due to missing heartbeat/lease expiry
                    agent = self.registry.get_agent(lease.agent_id)
                    if agent and agent.status == AgentStatus.BUSY:
                        agent.status = AgentStatus.UNHEALTHY
                    # Release the expired lease
                    self.registry.release_agent_lease(lease_id)

            return expired_leases

    def reassign_subtask(
        self,
        node_id: str,
        graph_engine: TaskGraphEngine,
    ) -> tuple[AgentDescriptor, AgentLease]:
        """Safely reassign an interrupted or crashed subtask to an available replacement specialist."""
        with self._lock:
            node = graph_engine.graph.nodes.get(node_id)
            if not node:
                raise KeyError(f"Node '{node_id}' not found in task graph.")

            # Find healthy replacement agent matching required capability
            replacement = self.registry.find_available_agent(
                required_capabilities=[node.required_capability]
            )
            if not replacement:
                raise AgentUnavailableError(
                    f"No available replacement agent with capability '{node.required_capability.value}' to reassign node '{node_id}'."
                )

            # Acquire new lease
            new_lease = self.registry.acquire_agent_lease(
                agent_id=replacement.agent_id,
                task_id=node.task_id,
                node_id=node_id,
                ttl_seconds=60.0,
            )

            # Re-queue node under new agent
            node.status = NodeStatus.READY
            node.assigned_agent_id = replacement.agent_id
            return replacement, new_lease

    def reconcile_action_outcome(
        self,
        task_id: str,
        action_id: str,
        idempotency_key: str,
        is_idempotent: bool,
        operator_confirmed_executed: bool | None = None,
    ) -> bool:
        """Enforce strict side-effect safety: non-idempotent actions in UNKNOWN state cannot be retried without reconciliation."""
        if not is_idempotent and operator_confirmed_executed is None:
            raise NonIdempotentActionUncertaintyError(
                f"Action '{action_id}' (key '{idempotency_key}') has non-idempotent side effects and unknown outcome. "
                "Automatic retry prohibited without deterministic operator reconciliation."
            )

        if operator_confirmed_executed is True:
            logger.info(
                "Operator reconciled action '%s' as already executed; skipping re-execution.",
                action_id,
            )
            return False  # Do not re-execute

        return True  # Safe to execute
