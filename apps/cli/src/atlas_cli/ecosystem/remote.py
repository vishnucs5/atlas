"""ATLAS CLI Remote Runtime & Federation Adapter.

Connects ATLAS CLI to remote ATLAS runtimes and federation gateways.
Supports discovery of remote workers, session leasing, event streaming,
and automatic connection recovery while maintaining Action Firewall boundaries.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from atlas_federation.discovery import (
    CapabilityAdvertisement,
    FederatedCapabilityRegistry,
    VisibilityScope,
)
from atlas_federation.gateway import FederationGateway
from pydantic import BaseModel, Field

logger = logging.getLogger("atlas_cli.ecosystem.remote")


class RemoteNodeInfo(BaseModel):
    """Metadata describing a discoverable remote ATLAS execution node."""

    node_id: str
    organization_id: str = "org_default"
    installation_id: str = "inst_default"
    endpoint_url: str = "http://localhost:8000"
    status: str = "online"  # online, busy, offline, maintenance
    available_agents: list[str] = Field(default_factory=list)
    supported_task_categories: list[str] = Field(default_factory=list)
    available_skills: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0


class RemoteSessionLease(BaseModel):
    """Lease representing an active session delegated to a remote runtime."""

    lease_id: str = Field(default_factory=lambda: f"lease_{uuid.uuid4().hex[:12]}")
    session_id: str
    node_id: str
    auth_token_masked: str
    created_at: float = Field(default_factory=time.time)
    expires_at: float
    status: str = "active"  # active, expired, recovered, released


class RemoteStreamEvent(BaseModel):
    """Streamed event received from a remote runtime during task execution."""

    event_id: str = Field(default_factory=lambda: f"rev_{uuid.uuid4().hex[:10]}")
    session_id: str
    event_type: str  # task_started, tool_execution, output_chunk, completed, error
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class RemoteRuntimeConnectionError(Exception):
    """Raised when communication with a remote runtime fails."""


class RemoteRuntimeClient:
    """Manages secure communication with remote ATLAS execution nodes and gateways."""

    def __init__(
        self,
        gateway: FederationGateway | None = None,
        capability_registry: FederatedCapabilityRegistry | None = None,
    ) -> None:
        self.gateway = gateway
        self.capability_registry = capability_registry or FederatedCapabilityRegistry()
        self._connected: bool = False
        self._endpoint_url: str | None = None
        self._auth_token: str | None = None
        self._active_leases: dict[str, RemoteSessionLease] = {}
        self._event_buffer: dict[str, list[RemoteStreamEvent]] = {}
        self._known_nodes: dict[str, RemoteNodeInfo] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def endpoint_url(self) -> str | None:
        return self._endpoint_url

    def connect(self, endpoint_url: str, auth_token: str) -> bool:
        """Establish authenticated connection to a remote ATLAS endpoint."""
        if not endpoint_url or not auth_token:
            raise RemoteRuntimeConnectionError("Endpoint URL and auth token are required")

        # Redact token for logging
        masked_token = auth_token[:4] + "..." + auth_token[-4:] if len(auth_token) > 8 else "***"
        logger.info("Connecting to remote runtime at %s with token %s", endpoint_url, masked_token)

        self._endpoint_url = endpoint_url
        self._auth_token = auth_token
        self._connected = True
        return True

    def disconnect(self) -> None:
        """Disconnect and release all active remote session leases."""
        for lease_id in list(self._active_leases.keys()):
            self.release_session_lease(lease_id)
        self._connected = False
        self._endpoint_url = None
        self._auth_token = None
        logger.info("Disconnected from remote runtime")

    def register_node(self, node: RemoteNodeInfo) -> None:
        """Register a known remote node into local discovery."""
        self._known_nodes[node.node_id] = node
        # Also advertise to capability registry if present
        ad = CapabilityAdvertisement(
            organization_id=node.organization_id,
            installation_id=node.installation_id,
            agent_id=node.node_id,
            supported_task_categories=node.supported_task_categories,
            available_skills=node.available_skills,
            visibility=VisibilityScope.FEDERATION,
        )
        self.capability_registry.register_advertisement(ad)

    def discover_nodes(
        self,
        category: str | None = None,
        skill: str | None = None,
    ) -> list[RemoteNodeInfo]:
        """Discover active remote execution nodes matching criteria."""
        results: list[RemoteNodeInfo] = []
        for node in self._known_nodes.values():
            if node.status != "online":
                continue
            if category and category not in node.supported_task_categories:
                continue
            if skill and skill not in node.available_skills:
                continue
            results.append(node)
        return results

    def acquire_session_lease(
        self,
        session_id: str,
        preferred_node_id: str | None = None,
        duration_seconds: float = 3600.0,
    ) -> RemoteSessionLease:
        """Acquire a temporary execution lease for delegating work to a remote node."""
        if not self._connected:
            raise RemoteRuntimeConnectionError("Client is not connected to a remote runtime")

        # Select node
        if preferred_node_id:
            if preferred_node_id not in self._known_nodes:
                raise RemoteRuntimeConnectionError(f"Node {preferred_node_id} not found")
            node = self._known_nodes[preferred_node_id]
        else:
            candidates = self.discover_nodes()
            if not candidates:
                # Default fallback node
                node = RemoteNodeInfo(
                    node_id="remote-default-node-1",
                    organization_id="org_remote",
                    available_agents=["software_architect", "backend_engineer", "testing_engineer"],
                    supported_task_categories=["coding", "testing", "analysis"],
                )
                self.register_node(node)
            else:
                node = candidates[0]

        masked_token = (
            self._auth_token[:4] + "..." + self._auth_token[-4:]
            if self._auth_token and len(self._auth_token) > 8
            else "***"
        )
        lease = RemoteSessionLease(
            session_id=session_id,
            node_id=node.node_id,
            auth_token_masked=masked_token,
            expires_at=time.time() + duration_seconds,
            status="active",
        )
        self._active_leases[lease.lease_id] = lease
        self._event_buffer[lease.lease_id] = []
        logger.info(
            "Acquired remote session lease %s on node %s for session %s",
            lease.lease_id,
            node.node_id,
            session_id,
        )
        return lease

    def release_session_lease(self, lease_id: str) -> bool:
        """Release an active session lease."""
        lease = self._active_leases.get(lease_id)
        if not lease:
            return False
        lease.status = "released"
        logger.info("Released remote session lease %s", lease_id)
        return True

    def emit_remote_event(
        self, lease_id: str, event_type: str, payload: dict[str, Any]
    ) -> RemoteStreamEvent:
        """Record or simulate a streamed event from the remote node."""
        lease = self._active_leases.get(lease_id)
        if not lease or lease.status != "active":
            raise RemoteRuntimeConnectionError(
                f"Active lease required to emit events, lease {lease_id} is invalid"
            )

        event = RemoteStreamEvent(
            session_id=lease.session_id,
            event_type=event_type,
            payload=payload,
        )
        self._event_buffer.setdefault(lease_id, []).append(event)
        return event

    def poll_events(self, lease_id: str) -> list[RemoteStreamEvent]:
        """Retrieve and drain buffered streamed events for a session lease."""
        if lease_id not in self._event_buffer:
            return []
        events = list(self._event_buffer[lease_id])
        self._event_buffer[lease_id].clear()
        return events

    def reconnect_and_resume(self, lease_id: str) -> bool:
        """Recover a disconnected session by re-validating the active lease."""
        lease = self._active_leases.get(lease_id)
        if not lease:
            logger.warning("Cannot recover unknown lease %s", lease_id)
            return False

        if time.time() > lease.expires_at:
            lease.status = "expired"
            logger.warning("Session lease %s has expired and cannot be resumed", lease_id)
            return False

        lease.status = "recovered"
        self._connected = True
        logger.info("Successfully recovered and resumed remote session for lease %s", lease_id)
        return True
