"""Tests for webhook secret provisioning and replay protection in atlas_process.triggers."""

import json
import time

import pytest
from atlas_process.triggers import (
    EventTriggerEngine,
    ForgedEventError,
    UnauthorizedTriggerError,
)


def test_missing_tenant_secret_raises_unauthorized_trigger_error():
    # Engine created with no default secret
    engine = EventTriggerEngine()
    body = b'{"event_type": "order.completed"}'

    with pytest.raises(UnauthorizedTriggerError, match="No webhook secret configured"):
        engine.verify_webhook(body, "sha256=invalid", tenant_id="tenant_unknown")


def test_tenant_secret_isolation():
    engine = EventTriggerEngine()
    engine.provision_tenant_secret("tenant_alpha", "super_secret_alpha_key_12345")
    engine.provision_tenant_secret("tenant_beta", "super_secret_beta_key_67890")

    body = json.dumps({"event_type": "invoice.paid"}).encode("utf-8")

    # Alpha signature
    alpha_sig = engine.compute_signature(body, tenant_id="tenant_alpha")

    # Alpha signature verifies for Alpha
    event = engine.verify_webhook(body, f"sha256={alpha_sig}", tenant_id="tenant_alpha")
    assert event.tenant_id == "tenant_alpha"

    # Attempting to use Alpha signature for Beta MUST fail
    with pytest.raises(ForgedEventError):
        engine.verify_webhook(body, f"sha256={alpha_sig}", tenant_id="tenant_beta")


def test_secret_rotation():
    engine = EventTriggerEngine()
    engine.provision_tenant_secret("tenant_gamma", "old_webhook_secret_key_11111")
    body = b'{"event_type": "ticket.created"}'
    old_sig = engine.compute_signature(body, tenant_id="tenant_gamma")

    # Rotate secret
    engine.rotate_tenant_secret("tenant_gamma", "new_webhook_secret_key_22222")
    new_sig = engine.compute_signature(body, tenant_id="tenant_gamma")

    # Old signature must now be rejected
    with pytest.raises(ForgedEventError):
        engine.verify_webhook(body, f"sha256={old_sig}", tenant_id="tenant_gamma")

    # New signature succeeds
    event = engine.verify_webhook(body, f"sha256={new_sig}", tenant_id="tenant_gamma")
    assert event.tenant_id == "tenant_gamma"


def test_timestamp_drift_replay_protection():
    engine = EventTriggerEngine(secret_key="common_test_secret_key_123456")
    body = b'{"event_type": "user.signup"}'
    sig = engine.compute_signature(body)

    # 10 minutes ago (> 300s)
    stale_timestamp = time.time() - 600.0

    with pytest.raises(ForgedEventError, match="Timestamp drift"):
        engine.verify_webhook(body, sig, tenant_id="tenant_01", timestamp=stale_timestamp)
