# Phase 4 Status Tracker: Durable Execution & Recovery Infrastructure

**Target Branch:** `feat/phase-4-durable-execution-and-recovery`  
**Current Status:** **IN PROGRESS (Plan Complete, Milestone 1 Underway)**  
**Start Date:** 2026-11-12  
**Target Completion:** 2026-11-13  
**Passing Tests:** 156 / 156 (Phase 1–3 baseline preserved)

---

## Acceptance Criteria Checklist (0/10 Complete)

- [ ] **AC-P4-01: Versioned Checkpoint Contract & Manager**
  - Fully-typed Pydantic v2 `Checkpoint` schema with fencing generations, step progress, action lists, environment metadata, and SHA-256 integrity hash.
  - `CheckpointManager` supporting transactional creation, validation, corruption detection, and secret sanitization.

- [ ] **AC-P4-02: Worker Registry & Lifecycle**
  - `WorkerRegistry` managing worker capabilities, status (`IDLE`, `BUSY`, `DRAINING`, `DISCONNECTED`), heartbeats, and graceful draining.
  - Automated worker timeout and disconnection detection.

- [ ] **AC-P4-03: Stale Worker Fencing & Lease Generations**
  - Monotonically increasing lease generations (fencing tokens).
  - Commit-time validation rejecting writes from stale or expired workers with `StaleWorkerError`.

- [ ] **AC-P4-04: Durable Action Execution Ledger**
  - Independent action tracking with statuses: `NOT_STARTED`, `STARTED`, `SUCCEEDED`, `FAILED`, `UNKNOWN`, `VERIFIED`, `REJECTED`.
  - Idempotency key deduplication, attempt counting, and safe retry evaluation.

- [ ] **AC-P4-05: Eight-Stage Crash Recovery Coordinator**
  - State machine: DETECT $\to$ CLASSIFY $\to$ COLLECT EVIDENCE $\to$ SELECT STRATEGY $\to$ APPLY POLICY $\to$ RECOVER $\to$ VERIFY $\to$ RECORD.
  - Full `ActionFirewall` policy gating ensuring recovery actions cannot bypass approvals.

- [ ] **AC-P4-06: Environment Reconciliation Before Resumption**
  - `EnvironmentReconciler` inspecting physical browser/driver state (URL, title, DOM) before checkpoint resumption.
  - Decides whether to resume, restart step, request operator approval, or abort safely.

- [ ] **AC-P4-07: Execution Replay & State Reconstruction**
  - `ExecutionReplayEngine` reconstructing point-in-time task projections at any sequence number $N$.
  - Audit timeline export of events, worker handoffs, and verification outcomes.

- [ ] **AC-P4-08: Capability-Aware Worker Scheduler**
  - `WorkerScheduler` matching task requirements to available registered workers without OS coupling.

- [ ] **AC-P4-09: 20-Scenario Fault-Injection Test Suite**
  - Automated tests covering API process crashes, worker crashes, mid-action drops, duplicate deliveries, lease expiries, corrupted checkpoints, and browser disconnects.

- [ ] **AC-P4-10: Schema Migrations & Production Specification**
  - Backwards-compatible SQLite schema migrations (`checkpoints`, `action_ledger`, `worker_registry`, `worker_leases`).
  - Documented PostgreSQL production storage specification.

---

## Phase 4 Milestone Progress Ledger

| Milestone | Subsystem / Component | Status | Assigned Target |
|---|---|:---:|---|
| **Milestone 1** | Core Durable Contracts (`packages/atlas-core`) | **IN PROGRESS** | `checkpoint.py`, `worker.py`, `ledger.py`, `recovery.py` |
| **Milestone 2** | Storage Protocols & SQLite Persistence (`packages/atlas-storage`) | NOT STARTED | DDL, `interfaces.py`, `sqlite.py`, `postgres.py` |
| **Milestone 3** | Package Scaffolding & Checkpoint Manager (`packages/atlas-coordination`) | NOT STARTED | `checkpoint_manager.py` |
| **Milestone 4** | Worker Registry, Lease Lifecycle & Scheduler (`packages/atlas-coordination`) | NOT STARTED | `worker_registry.py`, `scheduler.py` |
| **Milestone 5** | Durable Action Execution Ledger (`packages/atlas-coordination`) | NOT STARTED | `action_ledger.py` |
| **Milestone 6** | Environment Reconciliation & Crash Recovery Coordinator | NOT STARTED | `reconciler.py`, `recovery.py` |
| **Milestone 7** | Replay Engine, Fault-Injection Suite & Demonstration Script | NOT STARTED | `replay.py`, tests, demo |
