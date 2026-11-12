# ADR-0007: Durable Execution, Worker Leases, and Crash Recovery Infrastructure

- **Status**: Accepted
- **Date**: 2026-11-12
- **Author**: ATLAS Software Architecture Team
- **Deciders**: ATLAS Core Team, Security Architecture, Runtime Engineering
- **Consulted**: Action Firewall, Storage, Observability, Browser Runtime Teams
- **Informed**: All ATLAS Contributors

---

## Context & Problem Statement

Autonomous computer-use runtimes execute consequential, multi-turn workflows in volatile real-world environments. During execution, multiple failure modes inevitably occur:
1. **Worker Crashes & Disconnections**: Workers executing browser or OS actions may crash due to out-of-memory errors, host reboots, or network disconnects.
2. **API & Process Restarts**: Control plane processes running task loops may restart mid-turn.
3. **Split-Brain / Stale Worker Mutations**: A disconnected worker may reconnect and attempt to write action results or state transitions after its lease has expired and the task has been reassigned.
4. **Unknown External Action Outcomes**: A process crash occurring after an external action was dispatched (e.g., clicking "Submit Order") but before the result was recorded leaves the real-world outcome ambiguous. Treating a timeout as proof that the action did not happen causes hazardous duplicate submissions.
5. **Divergence Between Checkpoint and Reality**: A saved state checkpoint does not guarantee that the real browser or desktop environment still matches that state upon reboot or worker handover.
6. **Corrupted or Tampered State**: In-flight storage disruptions or data tampering can lead to invalid recovery attempts.

ATLAS requires a production-grade durable execution and recovery infrastructure that guarantees crash recoverability, stale-worker fencing, action idempotency, environment reconciliation, and evidence-based replay while strictly upholding the ATLAS Engineering Constitution (`AGENTS.md`).

---

## Decision Drivers

- **Constitutional Compliance**:
  - Rule 1 (Architecture Ownership): Control plane owns task lifecycle, lease issuance, and recovery decisions. Workers execute work; models only advise.
  - Rule 2 (Action Firewall): Recovery actions must never bypass firewall authorization or human approval requirements.
  - Rule 3 (Zero-Dependency Core): Core contracts in `packages/atlas-core` must remain zero-dependency Pydantic v2 domain schemas.
  - Rule 4 (No Placeholders): All recovery paths, fencing mechanisms, and reconcilers must be functional and non-stubbed.
  - Rule 5 (No Swallowing Exceptions): Unhandled crashes and failures must be classified and recorded with full diagnostic context.
  - Rule 6 (No Secret Leaks): Checkpoints and action ledgers must redact secrets before persistence.
  - Rule 7 (Verification Invariant): Resumed workflows must verify post-conditions deterministically.
- **Safety in the Face of Uncertainty**: Never assume an external action failed just because a timeout occurred. Explicitly model and handle the `UNKNOWN` state.
- **Strict Fencing**: Monotonically increasing lease generations (fencing tokens) validated at commit time to eliminate split-brain write hazards.
- **Physical Reconciliation**: Inspect the live browser/environment before resuming execution from a checkpoint.
- **Replayability**: Reconstruct task state at any historical event sequence number from immutable event streams without re-executing actions.

---

## Considered Options

1. **Option 1: Rely on Celery / Temporal / Distributed Workflow Frameworks**
   - *Pros*: Pre-built distributed worker leases and replay capabilities.
   - *Cons*: Violates ADR-0001 (Monorepo and Runtime Ownership). Introduces heavy external dependencies (Redis, RabbitMQ, Temporal Server), breaking lightweight local SQLite development and zero-dependency core requirements.
2. **Option 2: Stateless Retries with Naive Loop Resumption**
   - *Pros*: Minimal code complexity.
   - *Cons*: Disastrous in computer-use automation. Retrying actions without fencing or environment verification causes duplicated external actions, form re-submissions, and corrupted sessions.
3. **Option 3: Native ATLAS Coordination & Durable Recovery Engine (`packages/atlas-coordination`)**
   - *Pros*: Fully adheres to ADR-0001 through ADR-0006. Native SQLite and PostgreSQL support, zero external daemon requirements for local runs, explicit fencing tokens, durable action ledgers, and live physical environment reconciliation.
   - *Cons*: Requires deliberate architectural design and implementation across the control plane.

---

## Decision

We adopt **Option 3**: Implement native durable execution, worker leasing, action ledgers, and crash recovery infrastructure within ATLAS, partitioned across clean package boundaries:

### 1. Architectural Distribution

```text
packages/
├── atlas-core/                  # Zero-dependency contracts (Rule 3)
│   └── contracts/
│       ├── checkpoint.py        # Versioned Checkpoint with fencing & hash
│       ├── worker.py            # WorkerRecord, WorkerLease, LeaseStatus, FencingToken
│       ├── ledger.py            # ActionExecutionRecord, ActionExecutionStatus
│       └── recovery.py          # RecoveryStrategy, FailureClassification, ReconciliationDecision
├── atlas-storage/               # Transactional Persistence & Storage Protocols
│   ├── interfaces.py            # CheckpointStoreProtocol, ActionLedgerStoreProtocol, WorkerStoreProtocol
│   └── sqlite.py                # Schema DDL (checkpoints, action_ledger, worker_leases) + WAL
└── atlas-coordination/          # Control Plane Coordination Engine
    ├── checkpoint_manager.py    # Transactional checkpointing, hashing, corruption recovery
    ├── worker_registry.py       # Worker lifecycle, heartbeats, draining, lease allocation
    ├── action_ledger.py         # Durable action tracking, commit-time fencing, retry policies
    ├── reconciler.py            # Physical environment observation vs checkpoint reconciliation
    ├── recovery.py              # 8-stage recovery coordinator (DETECT -> RECORD)
    ├── replay.py                # State reconstruction, evidence timeline export
    └── scheduler.py             # Capability-aware worker assignment
```

### 2. Monotonically Increasing Lease Generations (Fencing Tokens)

To prevent split-brain writes:
- Every task assignment to a worker increments the task's `lease_generation` integer.
- Leases have an expiration window renewed periodically via heartbeats.
- **Commit-Time Validation**: Whenever a worker attempts to append an event, update an action outcome, or persist a checkpoint, storage validates that `worker_lease_generation == current_task_lease_generation`.
- If a lease has expired or been reassigned to another worker generation, the write is atomically rejected with a `StaleWorkerError`.

### 3. Action Execution Ledger & Tri-State Outcomes

Instead of binary success/failure, actions are tracked in a durable ledger:
- Statuses: `NOT_STARTED`, `STARTED`, `SUCCEEDED`, `FAILED`, `UNKNOWN`, `VERIFIED`, `REJECTED`.
- If a worker crashes or drops while an action is `STARTED`, its status transitions to `UNKNOWN`.
- Safe retry policies:
  - Idempotent actions (e.g. read-only queries, navigations, idempotent key typing) may be retried after verification.
  - Non-idempotent or high-consequence actions (e.g. submissions, payments, deletions) are gated: they require physical environment reconciliation or human approval before any retry attempt.

### 4. Versioned Checkpoints with Tamper-Evident Integrity Hashes

- Checkpoints capture comprehensive execution state: task status, plan ID, step ID, lease generation, completed/pending/uncertain action IDs, last sequence number, and environment metadata.
- Each checkpoint computes a SHA-256 integrity hash over canonical JSON.
- If a checkpoint hash mismatch is detected upon loading, it is classified as `CORRUPTED_CHECKPOINT` and the recovery coordinator safely falls back to the preceding valid checkpoint or initiates reconciliation.
- Sensitive information (tokens, passwords) is scrubbed using `mask_credential` before persistence.

### 5. Eight-Stage Recovery Lifecycle

When an interruption or crash is detected, `RecoveryCoordinator` executes an explicit state machine:
$$\text{DETECT} \longrightarrow \text{CLASSIFY} \longrightarrow \text{COLLECT EVIDENCE} \longrightarrow \text{SELECT STRATEGY} \longrightarrow \text{APPLY POLICY} \longrightarrow \text{RECOVER} \longrightarrow \text{VERIFY} \longrightarrow \text{RECORD}$$

1. **DETECT**: Unresponsive worker, expired lease, API process restart, or browser crash.
2. **CLASSIFY**: Classify failure into a concrete category (e.g., `WORKER_CRASH`, `UNKNOWN_ACTION_OUTCOME`, `BROWSER_DISCONNECTION`).
3. **COLLECT EVIDENCE**: Gather last committed event sequence, latest checkpoint, ledger records, and active browser tab diagnostics.
4. **SELECT STRATEGY**: Choose deterministic recovery strategy (`RECONCILE_ENVIRONMENT`, `RESUME_FROM_CHECKPOINT`, `REQUEST_APPROVAL`, `FAIL_TASK`).
5. **APPLY POLICY**: Pass proposed recovery action through `ActionFirewall`. If recovery involves high-risk action re-execution, require human approval.
6. **RECOVER**: Execute recovery step (re-launch browser, assign new worker with bumped fencing token, roll back step).
7. **VERIFY**: Run `VerificationEngine` to ensure environment aligns with expected recovery state.
8. **RECORD**: Persist recovery audit events (`RECOVERY_STARTED`, `RECOVERY_COMPLETED`) to the append-only event stream.

### 6. Environment Reconciliation Before Resumption

Before resuming an interrupted workflow from a checkpoint:
- The `EnvironmentReconciler` inspects the live environment (e.g. Playwright browser page, active URL, window title, DOM snapshot).
- Compares live state with checkpoint expected state.
- If the live state matches the checkpoint, resumes execution seamlessly.
- If divergence is detected or an `UNKNOWN` action outcome cannot be deterministically resolved, the reconciler halts and requests operator approval or safely aborts.

### 7. Execution Replay

- **State Reconstruction**: Reconstruct task status, variables, and completed actions at any historical sequence number $N$ by replaying events from sequence 1 to $N$.
- **Audit Timeline**: Export structured timeline of events, worker assignments, lease handoffs, and verification outcomes.
- **Simulation vs Re-execution**: Pure time-travel state reconstruction does not dispatch driver actions to the physical environment.

---

## Consequences

### Positive
- **Rock-Solid Fault Tolerance**: Processes and workers can crash at any instant without leaving tasks in irrecoverable or corrupt states.
- **Split-Brain Elimination**: Fencing tokens prevent zombie workers from committing stale results.
- **No Duplicate Actions**: Explicit `UNKNOWN` action handling and reconciliation prevent duplicate form submissions or destructive side effects.
- **Full Observability & Auditability**: Every recovery decision, lease handoff, and replay is tracked in the immutable event log.
- **Zero Core SDK Dependencies**: Maintains strict compliance with Rule 3 of the Engineering Constitution.

### Negative & Trade-Offs
- Added storage tables (`checkpoints`, `action_ledger`, `worker_leases`) requiring schema initialization and migration support.
- Slight latency overhead for atomic fencing validation and checkpoint hashing during action commits.

---

## References
- `AGENTS.md` (ATLAS Engineering Constitution)
- `docs/adr/0001-monorepo-and-runtime-ownership.md`
- `docs/adr/0002-event-sourced-task-persistence.md`
- `docs/adr/0003-action-firewall-policy-separation.md`
- `docs/adr/0004-browser-runtime-architecture.md`
- `docs/adr/0005-model-provider-adapter-architecture.md`
- `docs/adr/0006-autonomous-planning-and-execution-loop.md`
