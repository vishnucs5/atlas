"""Unit tests for Phase 16.4 Webhook Determinism, Idempotency & Inbox Deduplication."""

import hashlib
import hmac
import json
import time

import pytest
from atlas_process.storage import (
    InMemoryProcessStorage,
    SqliteProcessStorage,
)
from atlas_process.triggers import (
    BusinessEvent,
    DuplicateEventError,
    EventTriggerEngine,
)


@pytest.fixture(params=["memory", "sqlite"])
def storage(request, tmp_path):
    if request.param == "memory":
        return InMemoryProcessStorage()
    db_path = str(tmp_path / "test_webhooks.db")
    s = SqliteProcessStorage(db_path)
    s.initialize()
    return s


def test_deterministic_event_id_and_replay_detection(storage):
    """Verify that replayed webhooks within the timestamp window produce the same event ID and are rejected."""
    engine = EventTriggerEngine(storage=storage)
    secret = "test_webhook_secret_key_123"
    engine.provision_tenant_secret("tenant_acme", secret)

    now = time.time()
    payload = {"event_type": "invoice.paid", "data": {"invoice_id": "INV-100", "amount": 2500}}
    raw_body = json.dumps(payload).encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # First webhook verification
    event1 = engine.verify_webhook(
        raw_body=raw_body,
        signature_header=f"sha256={mac}",
        tenant_id="tenant_acme",
        timestamp=now,
    )
    assert event1.event_id is not None
    assert event1.event_id.startswith("bev_")

    # Second webhook verification with identical signature & timestamp
    event2 = engine.verify_webhook(
        raw_body=raw_body,
        signature_header=f"sha256={mac}",
        tenant_id="tenant_acme",
        timestamp=now,
    )
    # Must yield the exact same deterministic event_id!
    assert event2.event_id == event1.event_id

    # Ingest event 1 succeeds
    engine.ingest_event(event1)

    # Ingesting event 2 (the replayed webhook) MUST fail with DuplicateEventError
    with pytest.raises(DuplicateEventError, match="Duplicate event.*detected"):
        engine.ingest_event(event2)


def test_durable_event_inbox_deduplication_across_engine_restart(storage):
    """Verify that deduplication persists across engine restarts using durable storage."""
    engine1 = EventTriggerEngine(storage=storage)
    event = BusinessEvent(
        event_id="bev_unique_persistent_01",
        tenant_id="tenant_payments",
        event_type="charge.succeeded",
        source="stripe_webhook",
        payload={"charge_id": "ch_555"},
        timestamp=time.time(),
    )

    # Ingest on engine 1
    engine1.ingest_event(event)

    # Verify event inbox in storage has it
    assert storage.has_event_inbox("tenant_payments", "bev_unique_persistent_01") is True

    # RESTART ENGINE: engine2 starts fresh with empty memory
    engine2 = EventTriggerEngine(storage=storage)

    # Ingesting same event on engine2 must be rejected by durable storage inbox check
    with pytest.raises(
        DuplicateEventError, match="Duplicate event.*detected and suppressed in durable storage"
    ):
        engine2.ingest_event(event)
