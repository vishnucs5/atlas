"""Collaborative Workspace Hub with Server-Authoritative Semantic Turn-Locking."""

from __future__ import annotations

import time
import uuid
from typing import Any

from atlas_collaboration.models import (
    CollaborativeSession,
    Collaborator,
    TurnLease,
    WorkspaceRole,
)


class TurnLeaseConflictError(RuntimeError):
    """Raised when an actor attempts to acquire an active turn lease held by another actor."""


class FencingTokenInvalidError(RuntimeError):
    """Raised when a mutation is attempted with an expired or preempted fencing token."""


class CollaborativeWorkspaceHub:
    """Manages collaborative paired-coding sessions with human preemptive turn-locking."""

    def __init__(self) -> None:
        self._sessions: dict[str, CollaborativeSession] = {}
        self._fencing_counters: dict[str, int] = {}

    def create_session(
        self,
        tenant_id: str,
        workspace_name: str,
        owner_identity: str,
        session_id: str | None = None,
    ) -> CollaborativeSession:
        sid = session_id or f"ws_sess_{uuid.uuid4().hex[:8]}"
        session = CollaborativeSession(
            session_id=sid,
            tenant_id=tenant_id,
            workspace_name=workspace_name,
        )
        owner = Collaborator(identity=owner_identity, role=WorkspaceRole.OWNER, is_human=True)
        session.collaborators[owner_identity] = owner
        self._sessions[sid] = session
        self._fencing_counters[sid] = 0
        return session

    def get_session(self, session_id: str) -> CollaborativeSession | None:
        return self._sessions.get(session_id)

    def join_session(
        self,
        session_id: str,
        identity: str,
        role: WorkspaceRole = WorkspaceRole.EDITOR,
        is_human: bool = True,
    ) -> Collaborator:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Collaborative session '{session_id}' not found.")

        collaborator = Collaborator(identity=identity, role=role, is_human=is_human)
        session.collaborators[identity] = collaborator
        session.updated_at = time.time()
        return collaborator

    def acquire_turn_lease(
        self,
        session_id: str,
        identity: str,
        duration_seconds: float = 30.0,
    ) -> TurnLease:
        """Acquire turn lease with human preemptive priority over autonomous agents."""
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Collaborative session '{session_id}' not found.")

        collab = session.collaborators.get(identity)
        if not collab:
            raise PermissionError(f"Actor '{identity}' is not enrolled in session '{session_id}'.")

        now = time.time()
        active_lease = session.active_turn_lease

        # Check if an active lease currently exists
        if active_lease and active_lease.expires_at > now and not active_lease.preempted:
            if active_lease.holder_identity == identity:
                # Extend existing lease
                active_lease.expires_at = now + duration_seconds
                return active_lease

            # Human Preemptive Override: A human operator preempts an autonomous worker immediately!
            if collab.is_human and not active_lease.is_human:
                active_lease.preempted = True
            else:
                raise TurnLeaseConflictError(
                    f"Turn lease is actively held by '{active_lease.holder_identity}' until {active_lease.expires_at}."
                )

        # Increment monotonic fencing token
        self._fencing_counters[session_id] = self._fencing_counters.get(session_id, 0) + 1
        fencing_token = self._fencing_counters[session_id]

        new_lease = TurnLease(
            lease_id=f"lease_{uuid.uuid4().hex[:8]}",
            holder_identity=identity,
            acquired_at=now,
            expires_at=now + duration_seconds,
            fencing_token=fencing_token,
            is_human=collab.is_human,
        )
        session.active_turn_lease = new_lease
        session.updated_at = now
        return new_lease

    def release_turn_lease(self, session_id: str, identity: str, fencing_token: int) -> bool:
        session = self._sessions.get(session_id)
        if not session or not session.active_turn_lease:
            return False

        lease = session.active_turn_lease
        if lease.holder_identity == identity and lease.fencing_token == fencing_token:
            session.active_turn_lease = None
            session.updated_at = time.time()
            return True
        return False

    def mutate_artifact(
        self,
        session_id: str,
        identity: str,
        fencing_token: int,
        artifact_key: str,
        content: Any,
    ) -> int:
        """Mutate workspace artifact guarded by active turn lease and fencing token."""
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Collaborative session '{session_id}' not found.")

        now = time.time()
        lease = session.active_turn_lease
        if not lease or lease.expires_at <= now or lease.preempted:
            raise FencingTokenInvalidError("No active turn lease is currently valid.")

        if lease.holder_identity != identity or lease.fencing_token != fencing_token:
            raise FencingTokenInvalidError(
                f"Fencing token {fencing_token} held by '{identity}' is invalid or has been superseded by '{lease.holder_identity}' (token {lease.fencing_token})."
            )

        session.artifacts[artifact_key] = content
        session.sequence_id += 1
        session.updated_at = now
        return session.sequence_id

    def get_snapshot(self, session_id: str) -> dict[str, Any]:
        """Return full state snapshot for client reconnection and differential catch-up."""
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Collaborative session '{session_id}' not found.")

        return {
            "session_id": session.session_id,
            "tenant_id": session.tenant_id,
            "workspace_name": session.workspace_name,
            "status": session.status,
            "sequence_id": session.sequence_id,
            "active_holder": session.active_turn_lease.holder_identity
            if session.active_turn_lease
            else None,
            "artifacts": dict(session.artifacts),
            "collaborator_count": len(session.collaborators),
            "updated_at": session.updated_at,
        }
