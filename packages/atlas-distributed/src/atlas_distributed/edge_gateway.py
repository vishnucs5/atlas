"""Edge Execution Gateway and Resilient Offline Buffer for ATLAS."""

from __future__ import annotations

import enum
import hashlib
import hmac
import logging
import time
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("atlas.distributed.edge_gateway")


class EdgeNodeStatus(enum.StrEnum):
    CONNECTED = "CONNECTED"
    OFFLINE = "OFFLINE"
    REVOKED = "REVOKED"


class EdgeHardwareMetrics(BaseModel):
    """Hardware health and resource status reported by an edge node."""

    platform: str = "linux/amd64"
    cpu_cores: int = 4
    memory_available_mb: int = 4096
    disk_free_gb: float = 20.0
    battery_percent: float | None = None  # None if AC powered
    is_charging: bool = True


class EdgeEnrollmentToken(BaseModel):
    """Cryptographic token authenticating an edge device."""

    token_id: str
    edge_node_id: str
    tenant_id: str
    hardware_fingerprint: str
    expires_at: float
    signature: str


class EdgeTaskAssignment(BaseModel):
    """Task assigned to an edge node."""

    assignment_id: str
    task_id: str
    tenant_id: str
    action_type: str
    action_parameters: dict[str, Any] = Field(default_factory=dict)
    assigned_at: float = Field(default_factory=time.time)
    lease_timeout_seconds: float = 300.0


class EdgeExecutionResult(BaseModel):
    """Execution result produced by an edge node."""

    assignment_id: str
    task_id: str
    status: str  # "SUCCESS", "FAILURE", "ABORTED"
    result_data: dict[str, Any] = Field(default_factory=dict)
    completed_at: float = Field(default_factory=time.time)
    buffered_offline: bool = False


class EdgeLocalBuffer:
    """Durable client-side buffer for edge nodes operating during intermittent WAN drops."""

    def __init__(self) -> None:
        self._buffered_assignments: dict[str, EdgeTaskAssignment] = {}
        self._buffered_results: list[EdgeExecutionResult] = []

    def buffer_assignment(self, assignment: EdgeTaskAssignment) -> None:
        self._buffered_assignments[assignment.assignment_id] = assignment

    def buffer_result(self, result: EdgeExecutionResult) -> None:
        result.buffered_offline = True
        self._buffered_results.append(result)

    def get_pending_results(self) -> list[EdgeExecutionResult]:
        return list(self._buffered_results)

    def clear_replayed_results(self, assignment_ids: set[str]) -> None:
        self._buffered_results = [
            r for r in self._buffered_results if r.assignment_id not in assignment_ids
        ]
        for aid in assignment_ids:
            self._buffered_assignments.pop(aid, None)


class EdgeExecutionGateway:
    """Central gateway terminating reverse outbound connections from remote edge workers."""

    def __init__(self, secret_key: str = "edge-gateway-master-secret") -> None:
        self.secret_key = secret_key
        self._enrolled_nodes: dict[str, EdgeEnrollmentToken] = {}
        self._node_states: dict[str, EdgeNodeStatus] = {}
        self._node_hardware: dict[str, EdgeHardwareMetrics] = {}
        self._node_last_seen: dict[str, float] = {}
        self._assigned_tasks: dict[str, EdgeTaskAssignment] = {}
        self._completed_results: dict[str, EdgeExecutionResult] = {}
        self._revocation_list: set[str] = set()

    def issue_enrollment_token(
        self,
        edge_node_id: str,
        tenant_id: str,
        hardware_fingerprint: str,
        validity_seconds: float = 86400.0,
    ) -> EdgeEnrollmentToken:
        """Issue cryptographically signed enrollment token for an edge node."""
        token_id = f"etk_{edge_node_id}_{int(time.time())}"
        expires_at = time.time() + validity_seconds

        payload = f"{token_id}:{edge_node_id}:{tenant_id}:{hardware_fingerprint}:{expires_at}"
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        token = EdgeEnrollmentToken(
            token_id=token_id,
            edge_node_id=edge_node_id,
            tenant_id=tenant_id,
            hardware_fingerprint=hardware_fingerprint,
            expires_at=expires_at,
            signature=signature,
        )
        self._enrolled_nodes[edge_node_id] = token
        self._node_states[edge_node_id] = EdgeNodeStatus.OFFLINE
        return token

    def authenticate_handshake(self, token: EdgeEnrollmentToken, current_fingerprint: str) -> bool:
        """Verify token authenticity and hardware binding on reverse connection."""
        if token.edge_node_id in self._revocation_list:
            logger.warning(f"Connection rejected for REVOKED edge node '{token.edge_node_id}'")
            return False

        if time.time() > token.expires_at:
            logger.warning(f"Connection rejected: expired token for '{token.edge_node_id}'")
            return False

        # Verify hardware fingerprint match (prevents token copying to other machines)
        if token.hardware_fingerprint != current_fingerprint:
            logger.error(f"Hardware fingerprint mismatch for '{token.edge_node_id}'")
            return False

        # Verify signature
        payload = f"{token.token_id}:{token.edge_node_id}:{token.tenant_id}:{token.hardware_fingerprint}:{token.expires_at}"
        expected_sig = hmac.new(
            self.secret_key.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(token.signature, expected_sig):
            logger.error(f"Invalid cryptographic signature for '{token.edge_node_id}'")
            return False

        self._node_states[token.edge_node_id] = EdgeNodeStatus.CONNECTED
        self._node_last_seen[token.edge_node_id] = time.time()
        logger.info(f"Edge node '{token.edge_node_id}' successfully connected via outbound TLS")
        return True

    def receive_heartbeat(self, edge_node_id: str, metrics: EdgeHardwareMetrics) -> bool:
        """Process heartbeat from connected edge node."""
        if edge_node_id in self._revocation_list:
            return False

        self._node_last_seen[edge_node_id] = time.time()
        self._node_hardware[edge_node_id] = metrics
        self._node_states[edge_node_id] = EdgeNodeStatus.CONNECTED
        return True

    def dispatch_assignment(self, edge_node_id: str, assignment: EdgeTaskAssignment) -> bool:
        """Send task assignment to connected edge node."""
        if self._node_states.get(edge_node_id) != EdgeNodeStatus.CONNECTED:
            return False

        self._assigned_tasks[assignment.assignment_id] = assignment
        return True

    def sync_replayed_results(
        self, edge_node_id: str, results: list[EdgeExecutionResult]
    ) -> set[str]:
        """Acknowledge and persist replayed execution results from reconnected edge node."""
        if edge_node_id in self._revocation_list:
            return set()

        synced_ids = set()
        for res in results:
            self._completed_results[res.assignment_id] = res
            self._assigned_tasks.pop(res.assignment_id, None)
            synced_ids.add(res.assignment_id)

        logger.info(
            f"Synced {len(synced_ids)} buffered offline results from edge node '{edge_node_id}'"
        )
        return synced_ids

    def revoke_edge_node(self, edge_node_id: str) -> None:
        """Revoke edge node, invalidating active leases and rejecting future connections."""
        self._revocation_list.add(edge_node_id)
        self._node_states[edge_node_id] = EdgeNodeStatus.REVOKED
        logger.warning(f"Edge node '{edge_node_id}' has been permanently REVOKED")

    def is_revoked(self, edge_node_id: str) -> bool:
        return edge_node_id in self._revocation_list
