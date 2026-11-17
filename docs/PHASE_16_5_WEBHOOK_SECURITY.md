# ATLAS Phase 16.5 — Webhook Security & Idempotency Audit

## 1. Executive Summary

This audit evaluated event-driven trigger security, HMAC webhook authentication, timestamp drift mitigation, deterministic fingerprinting, and atomic database deduplication in `EventTriggerEngine` (`packages/atlas-process/src/atlas_process/triggers.py`) and persistent storage.

Finding `NEW-16.3-05` (static fallback HMAC secrets and memory-only deduplication susceptible to replay attacks across restarts) is **GENUINELY REMEDIATED**. Webhook authentication now enforces mandatory per-tenant secrets, constant-time HMAC-SHA256 signature validation, and database-level atomic deduplication.

---

## 2. Inbound Webhook Authentication & Replay Defense

In `EventTriggerEngine`:

### 1. Mandatory Per-Tenant Secrets
The static default secret (`"atlas-process-trigger-secret-v16"`) was eliminated.
If a webhook arrives for a tenant without an explicitly provisioned secret, `_get_secret_for_tenant()` raises:
```python
raise UnauthorizedTriggerError(
    f"No webhook secret configured for tenant '{tenant_id or 'unknown'}'. "
    "Insecure static default secrets are prohibited."
)
```

### 2. Constant-Time Signature Comparison
Signatures are validated using constant-time comparison to prevent side-channel timing attacks:
```python
if not hmac.compare_digest(expected, cleaned_sig):
    raise ForgedEventError("Webhook verification failed: Invalid HMAC-SHA256 signature.")
```

### 3. Timestamp Drift Window (Replay Defense)
Incoming webhooks with timestamps diverging by more than 300 seconds from host time are rejected immediately:
```python
if timestamp is not None and abs(now - timestamp) > max_drift_seconds:
    raise ForgedEventError(
        f"Webhook verification failed: Timestamp drift ({abs(now - timestamp):.1f}s) "
        f"exceeds tolerance of {max_drift_seconds}s."
    )
```

---

## 3. Deterministic Event Fingerprinting & Database Idempotency

### 1. Deterministic Event Identity
To guarantee deduplication across server restarts or clustered instances, `verify_webhook()` computes a deterministic event identity:
- If provider event ID exists (`id`, `event_id`, `delivery_id`):
  `event_id = "bev_" + sha256(tenant_id + ":" + provider_id)[:24]`
- If provider ID is absent:
  `event_id = "bev_" + sha256(tenant_id + ":" + signature + ":" + timestamp + ":" + body_hash)[:24]`

### 2. Atomic Database Deduplication
In `storage.py`, `record_event_inbox()` performs atomic insertion against table `process_event_inbox`:
```sql
INSERT INTO process_event_inbox (
    event_id, tenant_id, source, event_type, payload, status, received_at
) VALUES (%s, %s, %s, %s, %s, 'RECEIVED', %s)
ON CONFLICT (event_id) DO NOTHING;
```
`event_id` is the `PRIMARY KEY` in both PostgreSQL and SQLite.

### 3. Concurrency Protection
When two identical webhooks are delivered simultaneously to two independent ATLAS instances:
- Instance 1 executes `INSERT ... ON CONFLICT DO NOTHING`. `rowcount == 1`. Insertion succeeds.
- Instance 2 executes `INSERT ... ON CONFLICT DO NOTHING`. `rowcount == 0`.
- In `ingest_event()`:
  ```python
  if not recorded:
      raise DuplicateEventError(
          f"Duplicate event '{event.event_id}' detected during concurrent database ingestion."
      )
  ```
- Instance 2 suppresses the event and rejects the duplicate before any workflow is triggered.
- Verified across SQLite WAL and PostgreSQL 18.6 in `tests/unit/test_phase16_4_webhooks.py` and `tests/integration/test_phase16_4_postgres_full.py`.
