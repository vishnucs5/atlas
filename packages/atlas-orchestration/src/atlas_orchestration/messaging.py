"""AgentMessageRouter providing typed message delivery, circular delegation prevention, and cross-task barriers."""

import threading
from collections import defaultdict
from datetime import UTC, datetime

from atlas_core.contracts.message import AgentMessage, AgentMessageType


class DuplicateMessageError(Exception):
    """Raised when an identical message ID is submitted more than once."""


class ExpiredMessageError(Exception):
    """Raised when an inter-agent message has exceeded its TTL deadline."""


class CircularDelegationError(Exception):
    """Raised when a delegation request would form a loop or exceeds max delegation depth."""


class UnauthorizedCrossTaskCommunicationError(Exception):
    """Raised when an agent attempts to communicate across isolated task boundaries."""


class AgentMessageRouter:
    """Thread-safe router enforcing security, provenance, anti-looping, and delivery for inter-agent messages."""

    def __init__(self, max_delegation_depth: int = 3) -> None:
        self._lock = threading.RLock()
        self.max_delegation_depth = max_delegation_depth
        self._inboxes: dict[str, list[AgentMessage]] = defaultdict(list)
        self._task_messages: dict[str, list[AgentMessage]] = defaultdict(list)
        self._seen_message_ids: set[str] = set()
        self._agent_active_tasks: dict[str, str] = {}  # agent_id -> task_id

    def register_agent_task(self, agent_id: str, task_id: str) -> None:
        """Bind an agent to a specific active task context for cross-task boundary enforcement."""
        with self._lock:
            self._agent_active_tasks[agent_id] = task_id

    def unregister_agent_task(self, agent_id: str) -> None:
        """Clear the task binding for an agent."""
        with self._lock:
            self._agent_active_tasks.pop(agent_id, None)

    def route_message(self, msg: AgentMessage) -> None:
        """Validate and route an inter-agent message to the recipient's inbox."""
        with self._lock:
            # 1. Replay prevention
            if msg.message_id in self._seen_message_ids:
                raise DuplicateMessageError(
                    f"Message '{msg.message_id}' has already been processed and cannot be replayed."
                )

            # 2. TTL Expiration check
            if msg.is_expired():
                raise ExpiredMessageError(
                    f"Message '{msg.message_id}' expired at {msg.expires_at}."
                )

            # 3. Cross-task boundary isolation
            recipient_active_task = self._agent_active_tasks.get(msg.recipient_id)
            if recipient_active_task and recipient_active_task != msg.task_id:
                raise UnauthorizedCrossTaskCommunicationError(
                    f"Unauthorized cross-task communication: agent '{msg.recipient_id}' is assigned to task "
                    f"'{recipient_active_task}', but message was sent for task '{msg.task_id}'."
                )

            # 4. Circular delegation prevention
            if msg.message_type == AgentMessageType.DELEGATION_REQUEST:
                if msg.recipient_id in msg.delegation_path:
                    raise CircularDelegationError(
                        f"Circular delegation loop detected: recipient '{msg.recipient_id}' already exists in delegation path "
                        f"{msg.delegation_path}."
                    )
                if len(msg.delegation_path) >= self.max_delegation_depth:
                    raise CircularDelegationError(
                        f"Delegation depth exceeded maximum permissible limit of {self.max_delegation_depth}. "
                        f"Path: {msg.delegation_path}"
                    )
                # Append sender to delegation path for downstream forwarding
                msg.delegation_path.append(msg.sender_id)

            # Deliver to recipient inbox and task audit log
            self._seen_message_ids.add(msg.message_id)
            self._inboxes[msg.recipient_id].append(msg)
            self._task_messages[msg.task_id].append(msg)

    def get_inbox(self, agent_id: str) -> list[AgentMessage]:
        """Retrieve and drain all pending messages for an agent."""
        with self._lock:
            messages = self._inboxes.pop(agent_id, [])
            # Filter out expired messages at retrieval time
            now = datetime.now(UTC)
            return [m for m in messages if not m.is_expired(now)]

    def peek_inbox(self, agent_id: str) -> list[AgentMessage]:
        """View pending messages for an agent without draining."""
        with self._lock:
            now = datetime.now(UTC)
            return [m for m in self._inboxes.get(agent_id, []) if not m.is_expired(now)]

    def get_task_message_history(self, task_id: str) -> list[AgentMessage]:
        """Return immutable chronological record of all messages routed within a task."""
        with self._lock:
            return list(self._task_messages.get(task_id, []))
