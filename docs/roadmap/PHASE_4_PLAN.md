# Phase 4 Implementation Plan: Durable Execution & Recovery Infrastructure

**Target Branch:** `feat/phase-4-durable-execution-and-recovery`  
**Base Commit:** `0238b3b` (Phase 3 Verified & Accepted)  
**Start Date:** 2026-11-12  
**Target Completion:** 2026-11-13  
**Status:** **PLANNING COMPLETE — READY FOR EXECUTION**  
**Architectural ADR:** [ADR-0007](../adr/0007-durable-execution-and-recovery.md)

---

## 1. Existing Architecture Assessment

ATLAS currently possesses:
- **Phase 1 Foundation**: 14-state task state machine, event sourcing (`execution_events`), SQLite storage with WAL, Action Firewall (`packages/atlas-policy`), contextual logging (`packages/atlas-observability`), FastAPI health endpoints, and Click CLI.
- **Phase 2 Browser Runtime**: `PlaywrightBrowserDriver` behind `ComputerDriver` protocol, multimodal observations (DOM, accessibility, screenshot), deterministic `VerificationEngine`, and download/network managers.
- **Phase 3 Model Adapters & Agent Loop**: Model provider adapters (OpenAI, Anthropic, Gemini, Ollama, OpenAI-compatible), capability-based `ModelRouter` with circuit breakers and cost accounting, `StructuredPlanner`, `ContextManager` with prompt injection defense, `SafetyEngine` with loop detection, and an 11-step `AutonomousAgentLoop`.

### Current Gaps Addressed by Phase 4:
1. **Volatile In-Memory Execution State**: While `execution_events` records historical events, fine-grained checkpoints with fencing tokens, step progress, pending action references, and physical environment state are not yet persisted durably.
2. **Split-Brain Worker Mutations**: If a worker drops network connectivity and subsequently reconnects, there is no lease fencing generation check preventing stale commits.
3. **Ambiguity in Interrupted External Actions**: If a process crashes while executing an external browser action, the state is binary (failed/succeeded). An explicit `UNKNOWN` state and recovery reconciliation are required to prevent dangerous double submissions.
4. **Physical Divergence on Resume**: Resuming from a stored checkpoint does not verify whether the physical browser session, tabs, and URLs still match expected state.
5. **Time-Travel State Replay**: No mechanism currently reconstructs point-in-time task projections at sequence $N$ without re-executing live driver actions.

---

## 2. Current Implementation Inventory & Reused Components

| Component | Existing Package | Reused in Phase 4 |
|---|---|---|
| `TaskStateMachine` | `packages/atlas-core` | State transitions (`RECOVERING`, `RETRYING`, `FAILED`, `CANCELLED`). |
| `ComputerAction`, `ActionResult` | `packages/atlas-core` | Schema for actions stored in the durable action ledger. |
| `ExecutionEvent`, `EventType` | `packages/atlas-core` | Event stream expanded with Phase 4 recovery and lease lifecycle events. |
| `SQLiteStorage` | `packages/atlas-storage` | Extended with `checkpoints`, `action_ledger`, and `worker_leases` tables. |
| `ActionFirewall` | `packages/atlas-policy` | Evaluates recovery strategies to ensure automated recovery cannot bypass security policies. |
| `VerificationEngine` | `packages/atlas-verification` | Evaluates expected state post-conditions during environment reconciliation. |
| `PlaywrightBrowserDriver` | `packages/atlas-browser` | Provides active page state inspection for live environment reconciliation. |
| `AutonomousAgentLoop` | `packages/atlas-agent` | Integrates with lease validation, checkpoint manager, and recovery coordinator. |

---

## 3. Dependency Graph

```mermaid
graph TD
    subgraph Core ["packages/atlas-core (Rule 3 Zero-Dependency)"]
        Contracts[contracts/checkpoint.py<br/>contracts/worker.py<br/>contracts/ledger.py<br/>contracts/recovery.py]
        Lifecycle[lifecycle/state_machine.py]
    end

    subgraph Storage ["packages/atlas-storage"]
        StorageInterfaces[interfaces.py (Protocols)]
        SQLiteEngine[sqlite.py (WAL & Tables)]
        PostgresEngine[postgres.py (Production Spec)]
    end

    subgraph PolicyObservability ["packages/atlas-policy & atlas-observability"]
        Firewall[atlas_policy/firewall.py]
        Redactor[atlas_observability/logging.py]
    end

    subgraph Coordination ["packages/atlas-coordination (NEW)"]
        WorkerRegistry[worker_registry.py & scheduler.py]
        ActionLedger[action_ledger.py]
        CheckpointMgr[checkpoint_manager.py]
        Reconciler[reconciler.py]
        RecoveryCoord[recovery.py]
        ReplayEngine[replay.py]
    end

    subgraph Runtime ["Execution Engine"]
        Driver[packages/atlas-browser/driver.py]
        Verification[packages/atlas-verification/engine.py]
        AgentLoop[packages/atlas-agent/loop.py]
    end

    Contracts --> StorageInterfaces
    StorageInterfaces --> SQLiteEngine
    StorageInterfaces --> PostgresEngine
    Contracts --> Coordination
    StorageInterfaces --> Coordination
    Firewall --> Coordination
    Redactor --> Coordination
    Driver --> Coordination
    Verification --> Coordination
    Coordination --> AgentLoop
```

---

## 4. New Interfaces and Contracts

### 4.1. Core Contracts (`packages/atlas-core/src/atlas_core/contracts/`)
1. **`checkpoint.py`**:
   - `Checkpoint`: versioned snapshot with `lease_generation`, `plan_id`, `plan_version`, `current_step_id`, `completed_action_ids`, `pending_action_ids`, `uncertain_action_ids`, `last_event_sequence`, `environment_metadata`, `verification_evidence_refs`, `recovery_metadata`, `checkpoint_hash`, `schema_version`, and `created_at`.
2. **`worker.py`**:
   - `WorkerStatus` (`IDLE`, `BUSY`, `DRAINING`, `DISCONNECTED`, `TERMINATED`).
   - `LeaseStatus` (`ACTIVE`, `EXPIRED`, `RELEASED`, `REVOKED`).
   - `WorkerRecord`: worker registration, capabilities, heartbeat timestamp, metadata.
   - `WorkerLease`: lease ID, task ID, worker ID, generation (fencing token), acquired timestamp, expiration timestamp.
3. **`ledger.py`**:
   - `ActionExecutionStatus` (`NOT_STARTED`, `STARTED`, `SUCCEEDED`, `FAILED`, `UNKNOWN`, `VERIFIED`, `REJECTED`).
   - `ActionExecutionRecord`: action ID, task ID, idempotency key, attempt number, status, worker ID, lease generation, timestamps, parameters, output, verification result, error.
4. **`recovery.py`**:
   - `FailureClassification` (`WORKER_CRASH`, `LEASE_EXPIRED`, `NETWORK_DISCONNECTION`, `BROWSER_DISCONNECTION`, `UNKNOWN_ACTION_OUTCOME`, `VERIFICATION_FAILED`, `CORRUPTED_CHECKPOINT`).
   - `RecoveryStrategy` (`RETRY_ACTION`, `RECONCILE_ENVIRONMENT`, `RESUME_FROM_CHECKPOINT`, `REQUEST_APPROVAL`, `FAIL_TASK`).
   - `ReconciliationDecision` (`RESUME`, `RESTART_STEP`, `REQUEST_APPROVAL`, `ABORT`).
   - `ReconciliationResult`: matches expected, observed URL/title, decision, details.

### 4.2. Storage Protocols (`packages/atlas-storage/src/atlas_storage/interfaces.py`)
- `CheckpointStoreProtocol`: `save_checkpoint`, `get_checkpoint`, `get_latest_checkpoint`, `list_checkpoints`.
- `ActionLedgerStoreProtocol`: `record_action_attempt`, `update_action_status`, `get_action_record`, `get_task_actions`, `get_action_by_idempotency_key`.
- `WorkerStoreProtocol`: `register_worker`, `heartbeat_worker`, `get_worker`, `list_workers`, `acquire_lease`, `renew_lease`, `release_lease`, `get_active_lease`, `validate_lease_fencing`.
- Error Hierarchy: `StaleWorkerError`, `LeaseExpiredError`, `CorruptedCheckpointError`.

---

## 5. Database & Event Store Changes

### 5.1. SQLite Tables
```sql
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    session_id TEXT,
    worker_id TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL,
    plan_id TEXT,
    plan_version INTEGER NOT NULL DEFAULT 1,
    current_step_id TEXT,
    completed_action_ids TEXT NOT NULL DEFAULT '[]',
    pending_action_ids TEXT NOT NULL DEFAULT '[]',
    uncertain_action_ids TEXT NOT NULL DEFAULT '[]',
    last_event_sequence INTEGER NOT NULL,
    environment_metadata TEXT NOT NULL DEFAULT '{}',
    verification_evidence_refs TEXT NOT NULL DEFAULT '[]',
    recovery_metadata TEXT NOT NULL DEFAULT '{}',
    checkpoint_hash TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '1.0',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_task ON checkpoints(task_id, created_at);

CREATE TABLE IF NOT EXISTS action_ledger (
    action_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    lease_generation INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    action_type TEXT NOT NULL,
    parameters TEXT NOT NULL DEFAULT '{}',
    output TEXT,
    verification_result TEXT,
    error TEXT,
    schema_version TEXT NOT NULL DEFAULT '1.0',
    PRIMARY KEY (task_id, idempotency_key, attempt)
);
CREATE INDEX IF NOT EXISTS idx_ledger_action_id ON action_ledger(action_id);
CREATE INDEX IF NOT EXISTS idx_ledger_task_status ON action_ledger(task_id, status);

CREATE TABLE IF NOT EXISTS worker_registry (
    worker_id TEXT PRIMARY KEY,
    hostname TEXT NOT NULL,
    status TEXT NOT NULL,
    capabilities TEXT NOT NULL DEFAULT '[]',
    registered_at TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS worker_leases (
    lease_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE,
    worker_id TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '1.0'
);
CREATE INDEX IF NOT EXISTS idx_leases_worker ON worker_leases(worker_id);
```

### 5.2. Migration Strategy
All DDL statements use `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` inside `SQLiteStorage.initialize()`, preserving 100% backwards compatibility with existing Phase 1–3 databases without requiring data loss or manual database deletion.

---

## 6. Security Threat Analysis

| Threat ID | Threat Description | Mitigation Strategy | Implementation |
|---|---|---|---|
| **THR-401** | Split-brain write: Stale worker re-awakens and overwrites active worker's state | Atomic fencing token checks (`lease_generation`) at write time. If generation is stale, transaction aborts with `StaleWorkerError`. | Storage & `ActionLedger` |
| **THR-402** | Accidental double-spend / duplicated external action after timeout | Explicit `UNKNOWN` action outcome classification; non-idempotent actions cannot be re-executed without physical reconciliation or human approval. | `ActionLedger` & `RecoveryCoordinator` |
| **THR-403** | Checkpoint tampering or corruption leading to arbitrary state injection | SHA-256 canonical JSON integrity hashing on checkpoint creation; validation on load; fallback to last valid checkpoint on mismatch. | `CheckpointManager` |
| **THR-404** | Secret leakage in checkpoint snapshots or action parameters | Attribute-level sanitization using `mask_credential` and contextual secret redaction before writing to SQLite. | `CheckpointManager` & `ActionLedger` |
| **THR-405** | Model-prompted bypass of Action Firewall during automated recovery | Recovery actions must pass through `ActionFirewall.evaluate(action)`. High-risk actions require human approval regardless of recovery mode. | `RecoveryCoordinator` |
| **THR-406** | Zombie worker hijacking task assignment | Strict worker lease timeouts with automated expiration and lease reclamation by coordinator. | `WorkerRegistry` & `scheduler.py` |

---

## 7. Implementation Milestones

### Milestone 1: Core Durable Contracts (`packages/atlas-core`)
- Enhance `Checkpoint` with fencing generation, plan versioning, action tracking lists, environment metadata, and integrity hash.
- Implement `WorkerRecord`, `WorkerLease`, `ActionExecutionRecord`, `RecoveryEvent`, `ReconciliationResult`.
- Update `atlas_core` exports and test immutability and schema versioning.

### Milestone 2: Storage Interfaces & SQLite Persistence (`packages/atlas-storage`)
- Define `CheckpointStoreProtocol`, `ActionLedgerStoreProtocol`, `WorkerStoreProtocol` in `interfaces.py`.
- Implement `checkpoints`, `action_ledger`, `worker_registry`, `worker_leases` tables in `sqlite.py`.
- Implement commit-time lease fencing validation and optimistic concurrency.
- Update PostgreSQL production specification in `postgres.py`.

### Milestone 3: Package Scaffolding & Checkpoint Manager (`packages/atlas-coordination`)
- Scaffold `packages/atlas-coordination` package (`pyproject.toml`, workspace integration).
- Implement `CheckpointManager`: versioning, SHA-256 hash calculation, corruption detection, rollback, and secret masking.
- Unit tests for checkpoint creation, validation, tampering detection, and corruption fallback.

### Milestone 4: Worker Registry, Lease Lifecycle & Scheduler (`packages/atlas-coordination`)
- Implement `WorkerRegistry`: registration, heartbeats, draining, capability discovery.
- Implement `WorkerScheduler`: capability-aware task assignment.
- Implement lease management with monotonically increasing generation numbers (fencing tokens).
- Unit tests for lease renewal, expiry, and stale worker rejection.

### Milestone 5: Durable Action Execution Ledger (`packages/atlas-coordination`)
- Implement `ActionLedger`: status tracking (`NOT_STARTED` to `VERIFIED`), idempotency key mapping, attempt counting, and commit-time lease fencing.
- Safe retry policy evaluation (idempotent vs non-idempotent vs high-risk).
- Unit tests for action state tracking, duplicate suppression, and stale-lease rejection.

### Milestone 6: Environment Reconciliation & Crash Recovery Coordinator (`packages/atlas-coordination`)
- Implement `EnvironmentReconciler`: physical environment inspection, URL/DOM verification, comparison against checkpoint.
- Implement `RecoveryCoordinator`: 8-stage lifecycle (DETECT $\to$ CLASSIFY $\to$ COLLECT EVIDENCE $\to$ SELECT STRATEGY $\to$ APPLY POLICY $\to$ RECOVER $\to$ VERIFY $\to$ RECORD).
- Unit tests for recovery lifecycle, policy gating, and reconciliation decisions.

### Milestone 7: Execution Replay Engine & Integration Fault-Injection Suite
- Implement `ExecutionReplayEngine`: time-travel state reconstruction at sequence $N$, event timeline export.
- Integration fault-injection test suite covering all 20 required crash/failure scenarios.
- Standalone executable demonstration script: `scripts/demo_durable_recovery.py`.
- Acceptance audit and documentation updates.

---

## 8. Test Strategy & Minimum Fault-Injection Test Matrix

The test suite will validate 100% offline functionality across all 20 required failure scenarios:
1. `test_fault_api_process_crash_during_execution`
2. `test_fault_worker_crash_during_action_execution`
3. `test_fault_crash_after_external_action_before_persistence`
4. `test_fault_crash_after_result_persistence_before_checkpoint`
5. `test_fault_duplicate_action_requests`
6. `test_fault_duplicate_event_delivery`
7. `test_fault_out_of_order_event_delivery`
8. `test_fault_worker_lease_expiry`
9. `test_fault_stale_worker_commit_rejection`
10. `test_fault_concurrent_task_ownership_prevention`
11. `test_fault_corrupted_checkpoint_recovery`
12. `test_fault_missing_checkpoint_fallback`
13. `test_fault_browser_disconnection_reconciliation`
14. `test_fault_unknown_external_action_outcome_handling`
15. `test_fault_verification_failure_recovery`
16. `test_fault_recovery_policy_denial_blocks_recovery`
17. `test_fault_recovery_approval_requirement_enforced`
18. `test_replay_task_state_at_arbitrary_sequence`
19. `test_sqlite_restart_persistence_and_recovery`
20. `test_postgres_production_spec_conformance`

---

## 9. Acceptance Criteria (10 / 10 Target)

- [ ] **AC-P4-01**: Versioned, tamper-evident `Checkpoint` contract and `CheckpointManager` with SHA-256 integrity checks and corruption fallback.
- [ ] **AC-P4-02**: `WorkerRegistry` with heartbeats, draining, capability discovery, and lease lifecycle.
- [ ] **AC-P4-03**: Monotonically increasing lease generations (fencing tokens) rejecting stale worker commits at storage write time.
- [ ] **AC-P4-04**: Durable `ActionLedger` tracking action states (`NOT_STARTED` through `VERIFIED`), handling `UNKNOWN` safely, and enforcing idempotency.
- [ ] **AC-P4-05**: 8-stage `RecoveryCoordinator` resolving worker crashes, API restarts, and network drops under `ActionFirewall` policy gating.
- [ ] **AC-P4-06**: `EnvironmentReconciler` verifying actual physical browser/environment state before resuming from a checkpoint.
- [ ] **AC-P4-07**: `ExecutionReplayEngine` reconstructing task state at sequence $N$ and exporting audit timelines.
- [ ] **AC-P4-08**: Capability-aware `WorkerScheduler` matching task requirements to workers without OS coupling.
- [ ] **AC-P4-09**: Complete fault-injection test suite passing all 20 required failure scenarios 100% offline.
- [ ] **AC-P4-10**: Backwards-compatible SQLite schema migrations and documented PostgreSQL production specification.

---

## 10. Known Limitations

1. **Physical Browser Continuity across Process Restarts**: A killed Playwright process cannot have its live memory socket "reattached" across different OS processes without browser persistent user-data-dir; the reconciliation engine detects this and re-verifies the target URL and DOM state.
2. **Arbitrary External Non-Idempotent APIs**: Exactly-once execution cannot be mathematically guaranteed for arbitrary third-party APIs without distributed transactions (2PC) or native idempotency tokens; ATLAS classifies these as `UNKNOWN` and requires verification/approval.
3. **Local SQLite Concurrency**: SQLite WAL mode supports multiple concurrent readers and a single writer with busy timeouts; heavy distributed concurrency is intended for the PostgreSQL production target.
