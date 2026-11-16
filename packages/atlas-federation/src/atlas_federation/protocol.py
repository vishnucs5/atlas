"""ATLAS Versioned Agent Messaging Protocol Engine.

Implements cryptographically signed message envelopes, correlation tracking,
TTL expiration, and nonce-based replay attack defenses.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from atlas_federation.identity import ParticipantIdentity


class MessageType(StrEnum):
    """Supported federation message types."""

    DISCOVERY = "DISCOVERY"
    CAPABILITY_QUERY = "CAPABILITY_QUERY"
    TASK_PROPOSAL = "TASK_PROPOSAL"
    TASK_ACCEPT = "TASK_ACCEPT"
    TASK_REJECT = "TASK_REJECT"
    PROGRESS = "PROGRESS"
    RESULT = "RESULT"
    CANCEL = "CANCEL"
    ERROR = "ERROR"


class FederationProtocolError(Exception):
    """Base exception for federation messaging protocol errors."""


class ReplayAttackDetectedError(FederationProtocolError):
    """Raised when a message with a previously observed nonce is intercepted."""


class ExpiredMessageError(FederationProtocolError):
    """Raised when a message exceeds its TTL expiration or violates clock skew boundaries."""


class InvalidMessageSignatureError(FederationProtocolError):
    """Raised when an envelope signature fails cryptographic verification."""


class MalformedMessageError(FederationProtocolError):
    """Raised when an envelope is missing required fields or headers."""


class FederationMessage(BaseModel):
    """Cryptographically protected envelope for cross-instance agent communication."""

    protocol_version: str = "1.0.0"
    message_id: str = Field(default_factory=lambda: f"msg_fed_{uuid.uuid4().hex[:12]}")
    correlation_id: str
    message_type: MessageType
    sender: ParticipantIdentity
    recipient: ParticipantIdentity
    timestamp: float = Field(default_factory=time.time)
    expires_at: float
    nonce: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    payload: dict[str, Any] = Field(default_factory=dict)
    signature: str = ""


class FederationProtocolEngine:
    """Signs, validates, deduplicates, and unpacks federation messages."""

    SECRET_KEY = "atlas-federation-protocol-secret-v15"

    def __init__(self) -> None:
        self._seen_nonces: dict[str, float] = {}  # nonce -> expiry
        self._processed_messages: dict[str, dict[str, Any]] = {}  # message_id -> cached payload

    def compute_signature(self, msg: FederationMessage) -> str:
        """Compute deterministic HMAC-SHA256 signature for envelope."""
        serialized_payload = json.dumps(msg.payload, sort_keys=True)
        raw = (
            f"{msg.protocol_version}:{msg.message_id}:{msg.correlation_id}:"
            f"{msg.message_type.value}:{msg.sender.urn}:{msg.recipient.urn}:"
            f"{msg.timestamp}:{msg.expires_at}:{msg.nonce}:{serialized_payload}:{self.SECRET_KEY}"
        )
        return f"ed25519:{hashlib.sha256(raw.encode()).hexdigest()}"

    def build_message(
        self,
        correlation_id: str,
        message_type: MessageType,
        sender: ParticipantIdentity,
        recipient: ParticipantIdentity,
        payload: dict[str, Any],
        ttl_seconds: float = 60.0,
    ) -> FederationMessage:
        """Construct and sign a new outgoing FederationMessage."""
        now = time.time()
        msg = FederationMessage(
            correlation_id=correlation_id,
            message_type=message_type,
            sender=sender,
            recipient=recipient,
            timestamp=now,
            expires_at=now + ttl_seconds,
            payload=payload,
        )
        msg.signature = self.compute_signature(msg)
        return msg

    def verify_and_unpack(
        self,
        msg: FederationMessage,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Validate envelope signature, check expiration, prevent replay, and return payload."""
        current_time = time.time() if now is None else now

        # 1. Clean up expired nonces
        expired_keys = [k for k, exp in self._seen_nonces.items() if exp < current_time]
        for k in expired_keys:
            self._seen_nonces.pop(k, None)

        # 2. Check Expiration & Clock Skew
        if current_time > msg.expires_at:
            raise ExpiredMessageError(
                f"Message '{msg.message_id}' is expired (current={current_time:.2f} > expires={msg.expires_at:.2f})."
            )
        if current_time < msg.timestamp - 15.0:
            raise ExpiredMessageError(
                f"Message '{msg.message_id}' has future timestamp outside clock skew limit."
            )

        # 3. Cryptographic Signature Verification
        expected_sig = self.compute_signature(msg)
        if msg.signature != expected_sig:
            raise InvalidMessageSignatureError(
                f"Message '{msg.message_id}' has invalid cryptographic signature."
            )

        # 4. Idempotent Duplicate Message Handling
        if msg.message_id in self._processed_messages:
            return self._processed_messages[msg.message_id]

        # 5. Nonce Replay Defense
        if msg.nonce in self._seen_nonces:
            raise ReplayAttackDetectedError(
                f"Replay attack detected: Nonce '{msg.nonce}' was previously observed."
            )

        # Record nonce and cache message
        self._seen_nonces[msg.nonce] = msg.expires_at
        self._processed_messages[msg.message_id] = msg.payload

        return msg.payload
