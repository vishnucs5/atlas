"""ATLAS Remote Execution Protocol (ATLAS-REP/1.0) framing, signing, and verification."""

import hashlib
import hmac
import json
import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from atlas_distributed.models import (
    ProtocolEnvelope,
    ProtocolMessageType,
)

logger = logging.getLogger("atlas.distributed.protocol")

CURRENT_PROTOCOL_VERSION = "ATLAS-REP/1.0"
SUPPORTED_PROTOCOL_VERSIONS = {CURRENT_PROTOCOL_VERSION}


class ProtocolError(Exception):
    """Base exception for Remote Execution Protocol errors."""


class ProtocolVersionMismatchError(ProtocolError):
    """Raised when wire protocol version is unsupported."""


class InvalidSignatureError(ProtocolError):
    """Raised when message signature verification fails."""


class ReplayAttackError(ProtocolError):
    """Raised when a duplicated message ID or out-of-order sequence is detected."""


class MessageExpiredError(ProtocolError):
    """Raised when message timestamp exceeds allowable TTL clock drift."""


def canonical_json(data: Any) -> str:
    """Serialize dictionary/object to deterministic, canonical JSON."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_signature(
    secret_key: str,
    payload: dict[str, Any],
    message_id: str,
    timestamp_iso: str,
    sequence_number: int,
) -> str:
    """Compute HMAC-SHA256 signature over canonical message content."""
    canonical_body = canonical_json(payload)
    message_digest_content = f"{canonical_body}:{message_id}:{timestamp_iso}:{sequence_number}"
    signature = hmac.new(
        secret_key.encode("utf-8"),
        message_digest_content.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature


def create_envelope(
    message_type: ProtocolMessageType,
    sender_id: str,
    recipient_id: str,
    payload: dict[str, Any],
    secret_key: str,
    tenant_id: str = "default",
    sequence_number: int = 1,
    message_id: str | None = None,
    protocol_version: str = CURRENT_PROTOCOL_VERSION,
) -> ProtocolEnvelope:
    """Construct and cryptographically sign a standard ATLAS-REP/1.0 envelope."""
    msg_id = message_id or f"msg_{uuid.uuid4().hex}"
    now = datetime.now(UTC)
    timestamp_iso = now.isoformat()

    sig = compute_signature(
        secret_key=secret_key,
        payload=payload,
        message_id=msg_id,
        timestamp_iso=timestamp_iso,
        sequence_number=sequence_number,
    )

    return ProtocolEnvelope(
        protocol_version=protocol_version,
        message_id=msg_id,
        message_type=message_type,
        sender_id=sender_id,
        recipient_id=recipient_id,
        tenant_id=tenant_id,
        timestamp=now,
        sequence_number=sequence_number,
        payload=payload,
        signature=sig,
    )


def verify_envelope(
    envelope: ProtocolEnvelope,
    secret_key: str,
    max_drift_seconds: float = 300.0,
) -> bool:
    """Verify envelope protocol version, clock drift, and HMAC-SHA256 signature."""
    # 1. Version check
    if envelope.protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ProtocolVersionMismatchError(
            f"Unsupported protocol version '{envelope.protocol_version}'. "
            f"Supported versions: {list(SUPPORTED_PROTOCOL_VERSIONS)}"
        )

    # 2. Timestamp clock drift check
    now = datetime.now(UTC)
    age = abs((now - envelope.timestamp).total_seconds())
    if age > max_drift_seconds:
        raise MessageExpiredError(
            f"Message {envelope.message_id} timestamp exceeds allowable drift "
            f"({age:.1f}s > {max_drift_seconds:.1f}s)"
        )

    # 3. Signature verification
    expected_sig = compute_signature(
        secret_key=secret_key,
        payload=envelope.payload,
        message_id=envelope.message_id,
        timestamp_iso=envelope.timestamp.isoformat(),
        sequence_number=envelope.sequence_number,
    )

    if not hmac.compare_digest(envelope.signature, expected_sig):
        raise InvalidSignatureError(f"Signature mismatch on message {envelope.message_id}")

    return True


class MessageDeduplicator:
    """Thread-safe nonce and sequence deduplicator guarding against replay attacks."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self.ttl = timedelta(seconds=ttl_seconds)
        self._seen_messages: dict[str, datetime] = {}
        self._sender_sequences: dict[str, int] = {}
        self._lock = threading.Lock()

    def process_envelope(self, envelope: ProtocolEnvelope) -> None:
        """Validate that message has not been seen and sequence numbers are ordered."""
        now = datetime.now(UTC)
        with self._lock:
            # Purge expired seen messages
            expired_keys = [k for k, v in self._seen_messages.items() if now - v > self.ttl]
            for k in expired_keys:
                del self._seen_messages[k]

            # Replay check by message_id
            if envelope.message_id in self._seen_messages:
                raise ReplayAttackError(
                    f"Duplicate message detected: {envelope.message_id} has already been processed"
                )

            # Sequence check per sender
            last_seq = self._sender_sequences.get(envelope.sender_id, 0)
            if envelope.sequence_number <= last_seq:
                raise ReplayAttackError(
                    f"Out of order sequence number from {envelope.sender_id}: "
                    f"received {envelope.sequence_number}, expected > {last_seq}"
                )

            self._seen_messages[envelope.message_id] = now
            self._sender_sequences[envelope.sender_id] = envelope.sequence_number


def encode_envelope(envelope: ProtocolEnvelope) -> str:
    """Serialize ProtocolEnvelope to wire JSON string."""
    return envelope.model_dump_json()


def decode_envelope(data: str | bytes) -> ProtocolEnvelope:
    """Deserialize JSON wire data into validated ProtocolEnvelope."""
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return ProtocolEnvelope.model_validate_json(data)
