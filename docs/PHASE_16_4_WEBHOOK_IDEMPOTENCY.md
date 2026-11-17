# Phase 16.4 — Webhook Idempotency, Deterministic Identity & Event Inbox

## 1. Executive Summary

This document details the architectural remediation of **NEW-16.3-05** (Webhook Random Event IDs Defeating Replay Deduplication).

In Phase 16.2, `EventTriggerEngine.verify_webhook` generated event IDs using random UUIDs (`event_id = f"bev_{uuid.uuid4().hex[:12]}"`). Because each delivery of an identical webhook generated a unique ID, the deduplication cache in `ingest_event` (`if event.event_id in self._processed_event_ids`) was completely ineffective against duplicate deliveries and replay attacks within the 300-second acceptance window.

## 2. Root Cause Analysis

1. **Non-Deterministic Identity**: Webhooks lacking a vendor-provided ID were assigned random UUIDs rather than a deterministic fingerprint derived from the request payload and headers.
2. **Volatile In-Memory Cache**: Deduplication state was stored only in an ephemeral Python dictionary, meaning engine restarts or multi-instance deployments allowed duplicate event processing.

## 3. Implemented Remediation

### 3.1 Deterministic Event Fingerprinting
In `EventTriggerEngine.verify_webhook`:
- If the payload specifies a provider ID (`id`, `event_id`, or `delivery_id`), a tenant-scoped deterministic hash is generated:
  ```python
  deterministic_id = (
      f"bev_{hashlib.sha256(f'{tenant_id}:{provider_event_id}'.encode('utf-8')).hexdigest()[:24]}"
  )
  ```
- If no provider ID is present, a deterministic fingerprint is derived from the tenant ID, the HMAC signature, the timestamp, and the SHA-256 hash of the raw body bytes:
  ```python
  body_hash = hashlib.sha256(raw_body).hexdigest()
  ts_str = f"{timestamp:.3f}" if timestamp is not None else ""
  deterministic_id = f"bev_{hashlib.sha256(f'{tenant_id}:{cleaned_sig}:{ts_str}:{body_hash}'.encode('utf-8')).hexdigest()[:24]}"
  ```
Any replayed webhook within the tolerance window produces the exact same `event_id`.

### 3.2 Durable Event Inbox Table
- Added table `process_event_inbox` in PostgreSQL and SQLite:
  ```sql
  CREATE TABLE IF NOT EXISTS process_event_inbox (
      event_id VARCHAR(64) NOT NULL,
      tenant_id VARCHAR(64) NOT NULL,
      source VARCHAR(128) NOT NULL,
      event_type VARCHAR(128) NOT NULL,
      payload JSONB NOT NULL DEFAULT '{}'::jsonb,
      received_at DOUBLE PRECISION NOT NULL,
      PRIMARY KEY (tenant_id, event_id)
  );
  ```
- In `EventTriggerEngine.ingest_event`:
  1. Checks local memory cache `_processed_event_ids`.
  2. Queries `storage.has_event_inbox(tenant_id, event_id)`.
  3. Inserts into database via `storage.record_event_inbox(...)`. If the insert encounters a primary key conflict, `record_event_inbox` returns `False` and `DuplicateEventError` is raised.

## 4. Verification Evidence

- `tests/unit/test_phase16_4_webhooks.py`: 4/4 passed (memory and SQLite).
- `tests/integration/test_phase16_4_postgres_full.py::test_pg_16_4_06_archival_retention_and_event_inbox`: PASSED against native PostgreSQL.
