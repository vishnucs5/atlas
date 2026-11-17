# ATLAS Phase 16 Distributed Transaction & Saga Model

Specifies multi-system distributed transaction coordination, compensating transactions, and unknown-outcome reconciliation.

## 1. Saga Principles
1. **Compensations are New Operations**: Sagas do not pretend atomic rollback exists across external ERP/CRM systems. Compensations are forward compensating actions executed in reverse order.
2. **Idempotency Keys**: All forward and compensating steps carry explicit idempotency keys.
3. **No Blind Retries**: Non-idempotent operations fail-fast against retry attempts (`NonIdempotentBlindRetryError`).
4. **Unknown-Outcome Handling**: Timeouts and connection drops move steps into `RECONCILIATION_REQUIRED` state and enqueue for explicit reconciliation.
