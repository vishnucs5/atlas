"""Typed inter-agent messaging, provenance, delegation tracking, and envelope contracts."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentMessageType(StrEnum):
    """Semantic classification of an inter-agent message."""

    TASK_ASSIGNMENT = "TASK_ASSIGNMENT"
    TASK_RESULT = "TASK_RESULT"
    STATUS_UPDATE = "STATUS_UPDATE"
    DELEGATION_REQUEST = "DELEGATION_REQUEST"
    DELEGATION_RESPONSE = "DELEGATION_RESPONSE"
    MEMORY_QUERY = "MEMORY_QUERY"
    MEMORY_RESPONSE = "MEMORY_RESPONSE"
    REVIEW_REQUEST = "REVIEW_REQUEST"
    REVIEW_FEEDBACK = "REVIEW_FEEDBACK"
    CANCEL_NOTICE = "CANCEL_NOTICE"


class AgentMessage(BaseModel):
    """Typed, versioned envelope for asynchronous inter-agent communication."""

    model_config = ConfigDict(validate_assignment=True)

    message_id: str = Field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    sender_id: str
    recipient_id: str
    task_id: str
    correlation_id: str
    message_type: AgentMessageType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_schema_version: str = "1.0"
    delegation_path: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    schema_version: str = "1.0"

    def is_expired(self, now: datetime | None = None) -> bool:
        """Evaluate if the message has passed its time-to-live expiration."""
        if not self.expires_at:
            return False
        current_time = now or datetime.now(UTC)
        return current_time > self.expires_at
