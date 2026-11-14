"""Unit tests for ATLAS Remote Execution Protocol (ATLAS-REP/1.0)."""

from datetime import UTC, datetime, timedelta

import pytest
from atlas_distributed.models import ProtocolMessageType
from atlas_distributed.protocol import (
    CURRENT_PROTOCOL_VERSION,
    InvalidSignatureError,
    MessageDeduplicator,
    MessageExpiredError,
    ProtocolVersionMismatchError,
    ReplayAttackError,
    canonical_json,
    create_envelope,
    decode_envelope,
    encode_envelope,
    verify_envelope,
)


def test_canonical_json_determinism():
    """Verify JSON canonicalization ensures identical string output regardless of key order."""
    d1 = {"b": 2, "a": 1, "nested": {"z": 10, "y": 20}}
    d2 = {"nested": {"y": 20, "z": 10}, "a": 1, "b": 2}
    assert canonical_json(d1) == canonical_json(d2)
    assert canonical_json(d1) == '{"a":1,"b":2,"nested":{"y":20,"z":10}}'


def test_create_and_verify_envelope_success():
    """Verify valid ATLAS-REP/1.0 envelope creation and cryptographic verification."""
    secret = "shared_secret_key_123456"
    payload = {"task_id": "t_001", "action": "navigate", "url": "https://example.com"}

    envelope = create_envelope(
        message_type=ProtocolMessageType.ACTION_REQUEST,
        sender_id="worker_win11",
        recipient_id="control_plane",
        payload=payload,
        secret_key=secret,
        tenant_id="tenant_prod",
        sequence_number=1,
    )

    assert envelope.protocol_version == CURRENT_PROTOCOL_VERSION
    assert envelope.sender_id == "worker_win11"
    assert envelope.recipient_id == "control_plane"
    assert envelope.sequence_number == 1
    assert len(envelope.signature) == 64  # SHA-256 hex length

    # Verification must succeed
    assert verify_envelope(envelope, secret_key=secret) is True


def test_tampered_payload_signature_failure():
    """Verify HMAC signature verification fails when payload is tampered with."""
    secret = "my_secret_key"
    envelope = create_envelope(
        message_type=ProtocolMessageType.HEARTBEAT,
        sender_id="worker_01",
        recipient_id="control_plane",
        payload={"status": "IDLE"},
        secret_key=secret,
    )

    # Tamper with payload
    envelope.payload["status"] = "BUSY"

    with pytest.raises(InvalidSignatureError):
        verify_envelope(envelope, secret_key=secret)


def test_wrong_secret_signature_failure():
    """Verify verification fails when verified with wrong secret."""
    envelope = create_envelope(
        message_type=ProtocolMessageType.HEARTBEAT,
        sender_id="worker_01",
        recipient_id="control_plane",
        payload={"status": "IDLE"},
        secret_key="correct_secret",
    )

    with pytest.raises(InvalidSignatureError):
        verify_envelope(envelope, secret_key="wrong_secret")


def test_unsupported_protocol_version():
    """Verify rejection when an unsupported protocol version is presented."""
    envelope = create_envelope(
        message_type=ProtocolMessageType.HEARTBEAT,
        sender_id="worker_01",
        recipient_id="control_plane",
        payload={"status": "IDLE"},
        secret_key="secret",
        protocol_version="ATLAS-REP/99.0",
    )

    with pytest.raises(ProtocolVersionMismatchError):
        verify_envelope(envelope, secret_key="secret")


def test_clock_drift_and_expired_message():
    """Verify message exceeding allowable timestamp TTL is rejected."""
    secret = "secret"
    envelope = create_envelope(
        message_type=ProtocolMessageType.HEARTBEAT,
        sender_id="worker_01",
        recipient_id="control_plane",
        payload={"status": "IDLE"},
        secret_key=secret,
    )

    # Simulate 10-minute old timestamp
    envelope.timestamp = datetime.now(UTC) - timedelta(minutes=10)

    with pytest.raises(MessageExpiredError):
        verify_envelope(envelope, secret_key=secret, max_drift_seconds=300.0)


def test_deduplicator_replay_protection():
    """Verify MessageDeduplicator blocks duplicate message IDs and non-monotonic sequences."""
    dedup = MessageDeduplicator(ttl_seconds=300.0)
    secret = "secret"

    env1 = create_envelope(
        message_type=ProtocolMessageType.HEARTBEAT,
        sender_id="node_a",
        recipient_id="cp",
        payload={"ping": 1},
        secret_key=secret,
        sequence_number=1,
    )
    env2 = create_envelope(
        message_type=ProtocolMessageType.HEARTBEAT,
        sender_id="node_a",
        recipient_id="cp",
        payload={"ping": 2},
        secret_key=secret,
        sequence_number=2,
    )

    # First envelope should pass
    dedup.process_envelope(env1)

    # Replaying same envelope must raise ReplayAttackError
    with pytest.raises(ReplayAttackError) as exc_dup:
        dedup.process_envelope(env1)
    assert "Duplicate message detected" in str(exc_dup.value)

    # Next monotonic sequence passes
    dedup.process_envelope(env2)

    # Out-of-order or duplicate sequence number from same sender must raise ReplayAttackError
    env_stale_seq = create_envelope(
        message_type=ProtocolMessageType.HEARTBEAT,
        sender_id="node_a",
        recipient_id="cp",
        payload={"ping": 3},
        secret_key=secret,
        sequence_number=2,  # Already processed sequence 2
    )
    with pytest.raises(ReplayAttackError) as exc_seq:
        dedup.process_envelope(env_stale_seq)
    assert "Out of order sequence number" in str(exc_seq.value)


def test_encode_decode_roundtrip():
    """Verify wire encoding and decoding roundtrip preserves all fields and signature."""
    secret = "secret"
    orig = create_envelope(
        message_type=ProtocolMessageType.ASSIGNMENT_OFFER,
        sender_id="cp",
        recipient_id="worker_node",
        payload={"task_id": "t1", "action": "run"},
        secret_key=secret,
        tenant_id="tenant_test",
        sequence_number=42,
    )

    wire_str = encode_envelope(orig)
    assert isinstance(wire_str, str)

    restored = decode_envelope(wire_str)
    assert restored.message_id == orig.message_id
    assert restored.message_type == orig.message_type
    assert restored.sender_id == orig.sender_id
    assert restored.recipient_id == orig.recipient_id
    assert restored.tenant_id == orig.tenant_id
    assert restored.sequence_number == 42
    assert restored.signature == orig.signature
    assert verify_envelope(restored, secret_key=secret) is True
