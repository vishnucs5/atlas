# ADR-0002: Event-Sourced Task Persistence

- **Status**: Accepted
- **Date**: 2026-11-12
- **Deciders**: ATLAS Core Architecture Team
- **Technical Story**: Phase 1 Foundation

---

## Context and Problem Statement

Autonomous computer-use agents execute long-running, multi-step tasks across browsers, operating systems, and external applications. Throughout execution, agents generate intermediate plans, issue computer actions, receive environmental observations, transition through lifecycle states, and encounter unexpected errors.

In traditional CRUD (Create, Read, Update, Delete) database architectures, mutating a task record overwrites previous state values. This introduces major operational and safety failure modes:

1. **Loss of Causality & Auditability**: When an agent fails, takes an incorrect action, or halts, a simple status field of `FAILED` provides no insight into the sequence of steps, tool invocations, or policy evaluations that led to the failure.
2. **Inability to Replay or Recover**: Without an immutable history of events, recovering from a system crash or power outage requires guesswork rather than deterministic state rehydration.
3. **Compliance & Security Gaps**: Autonomous agents require forensic-grade event tracking to prove what actions were authorized, when they occurred, and what data was accessed.

---

## Decision Drivers

- **Forensic Auditability**: Every state change, action dispatch, observation, and policy decision must be recorded immutably.
- **Deterministic Replayability**: Any task state must be reconstructible from its historical events.
- **Query Performance**: Reading current task status and listing active tasks must remain fast without replaying thousands of events on every API request.
- **Local to Production Extensibility**: Painless single-node developer workflow (SQLite) with a clean migration path to enterprise relational databases (PostgreSQL).

---

## Considered Options

1. **Option A: CRUD Relational Model with Timestamp Columns**.
2. **Option B: Flat JSON Lines Files on Local Disk**.
3. **Option C: Event-Sourced Architecture with Materialized Projections** (Append-only event log + synchronous read view).

---

## Decision Outcome

**Chosen Option: Option C (Event-Sourced Architecture with Materialized Projections)**.

ATLAS implements an event-sourced persistence model in `packages/atlas-storage`.

### Storage Architecture Design

```
Command / State Mutation
        │
        ▼
[events Table] (Append-Only Event Log)
  ├── sequence_number (Strictly monotonic per task)
  ├── event_id (UUID)
  ├── task_id
  ├── event_type (e.g. TASK_CREATED, STATE_TRANSITIONED, ACTION_DISPATCHED)
  ├── payload (JSON document conforming to Pydantic contract)
  └── created_at (UTC timestamp)
        │
        ▼ (Synchronous Projection Update)
[tasks Table] (Materialized Read Model)
  ├── task_id (Primary Key)
  ├── objective
  ├── status (Current TaskStatus)
  ├── priority
  ├── metadata
  ├── current_checkpoint_id
  ├── created_at
  └── updated_at
```

### Key Implementation Specifications

1. **Monotonic Sequencing**: Each event associated with a `task_id` receives a strictly increasing `sequence_number` (1, 2, 3...). Concurrent appends with colliding sequence numbers are rejected.
2. **Materialized Read Projection**: For query speed, the `tasks` table is synchronously updated within the same transaction that appends the event.
3. **SQLite Engine Configuration**:
   - Write-Ahead Logging enabled: `PRAGMA journal_mode = WAL;`.
   - Busy timeout configured to 5000ms: `PRAGMA busy_timeout = 5000;`.
   - Normal synchronization: `PRAGMA synchronous = NORMAL;`.
4. **Target-Agnostic Storage Interfaces**:
   - `TaskStorageInterface` and `EventStoreInterface` defined in `atlas-storage` allow seamless switching between SQLite (local development / CLI) and PostgreSQL (production server deployments).

---

## Consequences

### Positive
- **Complete Historical Transparency**: Every action, transition, and observation is retained in chronological order.
- **Point-in-Time Recovery**: System crashes can be recovered by replaying uncommitted events or restoring from the latest checkpoint.
- **High Read Performance**: Common queries (e.g., `atlas task list`, GET `/api/v1/tasks/{id}`) read directly from the materialized `tasks` table without replaying events.
- **Zero External Dependencies for Local Dev**: Embedded SQLite requires no background database containers for developers running `atlas doctor` or `atlas init`.

### Negative / Risks
- **Storage Growth**: Event logs grow monotonically. In later phases, event archiving or snapshot compaction strategies may be required.
- **Schema Evolution**: Events are immutable; changes to event schemas must maintain backwards compatibility via explicit `schema_version` attributes and upcasting logic.

---

## Compliance & Verification

- `tests/unit/test_sqlite_storage.py` verifies sequential ordering, monotonic sequence numbering, and projection synchronization.
- Concurrency tests verify that multiple readers can query the database while writes are underway under WAL mode.
