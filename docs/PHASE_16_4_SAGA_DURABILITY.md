# Phase 16.4 — Saga Durability, Crash Recovery & Reconciliation Records

## 1. Executive Summary

This document details the architectural remediation of **NEW-16.3-02** (In-Memory Saga State and Non-Durable Transitions) and **NEW-16.3-04** (Reconciliation Record Retention).

In Phase 16.2, `SagaCoordinator` managed saga steps, states, and compensation histories entirely in in-memory Python dictionaries (`self._sagas`). A process engine restart or node crash caused active distributed transactions, compensation histories, and failed step details to be permanently lost.

## 2. Root Cause Analysis

1. **Missing Storage Injection**: `SagaCoordinator` did not accept a `ProcessStorageProtocol` instance in its constructor, preventing any database reads or writes during forward step execution or reverse compensation.
2. **Missing Saga Step Persistence**: While `process_saga_transactions` existed in the database, individual saga step objects (`SagaStep`), forward results, and compensation payloads were never synchronized to `process_saga_steps`.
3. **Loss of Failed Compensations**: When an external compensation failed (e.g. timeout on banking wire or ERP call), the discrepancy was captured only in RAM and never written to the `process_reconciliation_records` audit table.

## 3. Implemented Remediation

### 3.1 Storage Integration in `SagaCoordinator`
- `SagaCoordinator.__init__(storage: Any | None = None)` accepts any storage implementation conforming to `ProcessStorageProtocol`.
- All transaction state changes are persisted atomically:
  - `create_saga`: writes initial `SagaTransaction` row.
  - `execute_step`: appends step and updates forward results and execution timestamps.
  - `compensate_saga`: updates each step's status (`COMPENSATING`, `COMPENSATED`, `COMPENSATION_FAILED`) and appends to `compensation_history`.
  - `recover_saga`: re-hydrates full transaction and step state from database storage into active memory.

### 3.2 Relational Step Synchronization
- In `PostgresProcessStorage`:
  - `save_saga(saga)` performs atomic `INSERT ... ON CONFLICT (saga_id) DO UPDATE` on `process_saga_transactions`.
  - Loops over `saga.steps` and performs `INSERT ... ON CONFLICT (step_id) DO UPDATE` into `process_saga_steps`, serializing `forward_payload`, `forward_result`, `compensation_payload`, and `compensation_history` as JSONB.
  - `get_saga(saga_id)` queries `process_saga_transactions` and joins `process_saga_steps`, deserializing and reconstructing the full `SagaTransaction` object graph.
- Equivalent SQLite implementation provided in `SqliteProcessStorage`.

### 3.3 Durable Reconciliation on Compensation Failures
- If a compensation handler fails or is unavailable, the coordinator:
  1. Sets step status to `COMPENSATION_FAILED` or `COMPENSATION_UNAVAILABLE`.
  2. Sets saga transaction status to `PARTIAL_FAILURE` or `MANUAL_INTERVENTION_REQUIRED`.
  3. Writes a durable record into `process_reconciliation_records` via `storage.record_reconciliation(saga_id, step_id, reason, notes)`.
  4. Returns `False` from `compensate_saga()`.
- Provides `manual_resolve(saga_id, resolved_by, notes, mark_as)`:
  - Updates saga state to `COMPENSATED` or `COMPLETED`.
  - Locates matching `PENDING` records in `process_reconciliation_records` and updates them to `RESOLVED` with resolver identity and resolution notes.

## 4. Verification Evidence

- `tests/unit/test_phase16_4_sagas.py`: 6/6 passed (both in-memory and SQLite).
- `tests/integration/test_phase16_4_postgres_full.py::test_pg_16_4_04_saga_persistence_and_recovery`: PASSED against native PostgreSQL.
