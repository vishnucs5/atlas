# Phase 1: Foundation Design Specification

- **Project:** ATLAS (Autonomous Task & Lifecycle Automation System)
- **Status:** Approved Design
- **Date:** 2026-11-12
- **Milestone:** Phase 1 (Foundation & Core Lifecycle)
- **Target OS:** Windows 11 primary, cross-platform extensible

---

## 1. Executive Summary & Objective

ATLAS is an independent, model-agnostic computer-use runtime designed to orchestrate AI agents operating across web browsers, desktop applications, and operating systems. The foundational architectural axiom of ATLAS is:

> **The model makes decisions. ATLAS controls execution.**

The AI model never possesses unrestricted operating system, network, or credential access. All agent intentions are translated into standardized, versioned action requests that pass through runtime authorization, verification, and transactional event sourcing.

Phase 1 establishes the bedrock infrastructure:
1. Monorepo and package boundaries (`uv` workspace).
2. The Engineering Constitution (`AGENTS.md`) and Architectural Decision Records (ADRs).
3. Strongly-typed, versioned Pydantic v2 contracts for all core runtime entities.
4. An explicit, finite Task State Machine enforcing valid state transitions.
5. An event-sourced persistence architecture with a working SQLite local store and PostgreSQL production interface.
6. Contextual structured logging with automatic secret masking.
7. A FastAPI service with health and status endpoints.
8. A developer CLI (`atlas`) supporting environment health diagnostics (`atlas doctor`) and task initialization (`atlas init`).
9. Automated CI workflow and comprehensive test coverage.

---

## 2. Monorepo Structure & Package Boundaries

The project uses a Python `uv` workspace to enforce package modularity and isolation:

```
atlas-runtime/
├── .github/
│   └── workflows/
│       └── ci.yml
├── apps/
│   ├── api/
│   │   ├── pyproject.toml
│   │   └── src/atlas_api/
│   │       ├── __init__.py
│   │       ├── main.py
│   │       └── routes/
│   │           ├── __init__.py
│   │           └── health.py
│   └── cli/
│       ├── pyproject.toml
│       └── src/atlas_cli/
│           ├── __init__.py
│           ├── main.py
│           └── commands/
│               ├── __init__.py
│               ├── doctor.py
│               ├── init.py
│               └── task.py
├── packages/
│   ├── atlas-core/
│   │   ├── pyproject.toml
│   │   └── src/atlas_core/
│   │       ├── __init__.py
│   │       ├── contracts/
│   │       │   ├── __init__.py
│   │       │   ├── action.py
│   │       │   ├── checkpoint.py
│   │       │   ├── event.py
│   │       │   ├── model.py
│   │       │   ├── observation.py
│   │       │   ├── policy.py
│   │       │   ├── session.py
│   │       │   └── task.py
│   │       ├── lifecycle/
│   │       │   ├── __init__.py
│   │       │   ├── exceptions.py
│   │       │   └── state_machine.py
│   │       └── runtime/
│   │           ├── __init__.py
│   │           └── interface.py
│   ├── atlas-policy/
│   │   ├── pyproject.toml
│   │   └── src/atlas_policy/
│   │       ├── __init__.py
│   │       └── firewall.py
│   ├── atlas-storage/
│   │   ├── pyproject.toml
│   │   └── src/atlas_storage/
│   │       ├── __init__.py
│   │       ├── interfaces.py
│   │       ├── postgres.py
│   │       └── sqlite.py
│   └── atlas-observability/
│       ├── pyproject.toml
│       └── src/atlas_observability/
│           ├── __init__.py
│           └── logging.py
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CHANGELOG.md
│   ├── DECISIONS.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── KNOWN_ISSUES.md
│   ├── PROJECT_STATUS.md
│   ├── TEST_RESULTS.md
│   └── adr/
│       ├── 0001-monorepo-and-runtime-ownership.md
│       ├── 0002-event-sourced-task-persistence.md
│       └── 0003-action-firewall-policy-separation.md
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_contracts.py
│   │   ├── test_state_machine.py
│   │   ├── test_sqlite_storage.py
│   │   ├── test_policy_firewall.py
│   │   ├── test_observability.py
│   │   └── test_api_health.py
│   └── integration/
│       └── test_cli.py
├── AGENTS.md
├── pyproject.toml
├── ruff.toml
└── README.md
```

### Dependency Hierarchy Rule
- `atlas-core` has **zero external runtime dependencies** beyond standard library and `pydantic`. It must **never** import `atlas-storage`, `atlas-policy`, `atlas-api`, or any specific driver.
- `atlas-storage`, `atlas-policy`, and `atlas-observability` depend only on `atlas-core`.
- `apps/api` and `apps/cli` orchestrate the packages.

---

## 3. Core Data Contracts (`packages/atlas-core/contracts`)

All contracts subclass `pydantic.BaseModel` configured with `frozen=True` (immutable) or validated mutations with `schema_version = "1.0"`.

### 3.1 Task & Request
- `TaskStatus` (Enum): `CREATED`, `QUEUED`, `PLANNING`, `READY`, `RUNNING`, `PAUSED`, `WAITING_APPROVAL`, `WAITING_FOR_ENVIRONMENT`, `RECOVERING`, `VERIFYING`, `COMPLETED`, `FAILED`, `CANCELLED`, `EXPIRED`.
- `TaskPriority` (Enum): `LOW`, `NORMAL`, `HIGH`, `CRITICAL`.
- `TaskRequest`: `objective: str`, `priority: TaskPriority = NORMAL`, `metadata: dict[str, Any] = {}`, `timeout_seconds: int = 3600`.
- `Task`: `task_id: str`, `objective: str`, `status: TaskStatus`, `priority: TaskPriority`, `created_at: datetime`, `updated_at: datetime`, `metadata: dict[str, Any]`, `current_checkpoint_id: str | None`.

### 3.2 Action & Result
- `ActionTarget`: `strategy: str` (e.g., `accessible_role`, `css_selector`, `coordinates`, `window_title`), `parameters: dict[str, Any]`.
- `ExpectedState`: `condition: str`, `target: str`, `value: Any | None`, `timeout_ms: int = 5000`.
- `ComputerAction`: `action_id: str`, `task_id: str`, `session_id: str`, `action_type: str` (e.g., `browser.click`, `desktop.key_press`), `target: ActionTarget | None`, `parameters: dict[str, Any] = {}`, `expected_state: ExpectedState | None`, `idempotency_key: str`, `timeout_ms: int = 10000`, `schema_version: str = "1.0"`.
- `ActionResult`: `action_id: str`, `success: bool`, `output: Any | None`, `error: str | None`, `duration_ms: int`, `evidence: dict[str, Any] = {}`.

### 3.3 Observation & State
- `Observation`: `observation_id: str`, `task_id: str`, `session_id: str`, `timestamp: datetime`, `screenshot_ref: str | None`, `dom_snapshot: str | None`, `accessibility_tree: dict[str, Any] | None`, `focused_element: str | None`, `window_title: str | None`.

### 3.4 Execution Events
- `EventType` (Enum): `TASK_CREATED`, `TASK_QUEUED`, `PLAN_GENERATED`, `MODEL_REQUESTED`, `MODEL_RESPONDED`, `ENVIRONMENT_ALLOCATED`, `OBSERVATION_CAPTURED`, `ACTION_PROPOSED`, `POLICY_EVALUATED`, `APPROVAL_REQUESTED`, `APPROVAL_GRANTED`, `APPROVAL_DENIED`, `ACTION_STARTED`, `ACTION_COMPLETED`, `ACTION_FAILED`, `VERIFICATION_COMPLETED`, `RECOVERY_STARTED`, `CHECKPOINT_CREATED`, `TASK_COMPLETED`, `TASK_FAILED`, `TASK_PAUSED`, `TASK_CANCELLED`.
- `ExecutionEvent`: `event_id: str`, `task_id: str`, `session_id: str | None`, `sequence: int`, `event_type: EventType`, `timestamp: datetime`, `payload: dict[str, Any]`, `correlation_id: str`, `schema_version: str = "1.0"`.

### 3.5 Policy & Risk
- `PolicyDecisionType` (Enum): `ALLOW`, `DENY`, `REQUIRE_APPROVAL`.
- `RiskLevel` (Enum): `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
- `PolicyDecision`: `decision: PolicyDecisionType`, `risk_level: RiskLevel`, `reason: str`, `rules_evaluated: list[str] = []`.
- `ApprovalRequest`: `approval_id: str`, `task_id: str`, `action_id: str`, `action_hash: str`, `risk_level: RiskLevel`, `reason: str`, `status: str` (`PENDING`, `APPROVED`, `REJECTED`).

---

## 4. Task State Machine (`packages/atlas-core/lifecycle`)

An explicit transition graph prevents invalid lifecycle mutations:

```
[CREATED] -> [QUEUED] -> [PLANNING] -> [READY] -> [RUNNING]
                                                     |
         +-----------------+-------------------------+--------------------+
         |                 |                         |                    |
         v                 v                         v                    v
 [WAITING_APPROVAL]   [RECOVERING]              [VERIFYING]            [PAUSED]
         |                 |                         |                    |
         +-------->--------+------------->-----------+                    |
                           |                                              v
                           v                                         [RUNNING]
                     +-----+-----+
                     |           |
                     v           v
                [COMPLETED]   [FAILED]

From any non-terminal state -> [CANCELLED] or [EXPIRED]
```

### Transition Invariants
- Terminal states: `COMPLETED`, `FAILED`, `CANCELLED`, `EXPIRED`. No transitions are permitted out of terminal states.
- Invalid transitions immediately raise `InvalidStateTransitionError(current_state, target_state)`.
- Re-entrant transitions to the same state are disallowed unless explicitly flagged.
- Transitions must emit an atomic, monotonic `ExecutionEvent`.

---

## 5. Storage Architecture (`packages/atlas-storage`)

ATLAS uses **Event Sourcing with Materialized View Projections**.

### 5.1 Protocols
- `TaskStoreProtocol`:
  - `save_task(task: Task) -> None`
  - `get_task(task_id: str) -> Task | None`
  - `list_tasks(status: TaskStatus | None = None, limit: int = 50) -> list[Task]`
  - `update_task_status(task_id: str, new_status: TaskStatus, expected_current_status: TaskStatus | None = None) -> Task`
- `EventStoreProtocol`:
  - `append_event(event: ExecutionEvent) -> None`
  - `get_events(task_id: str, after_sequence: int = 0) -> list[ExecutionEvent]`
  - `get_latest_sequence(task_id: str) -> int`

### 5.2 SQLite Development Store
- Uses `aiosqlite` / synchronous `sqlite3` in WAL (Write-Ahead Logging) mode with transactional concurrency:
  - Table `tasks`: primary record containing current state projection.
  - Table `execution_events`: immutable log with unique constraint on `(task_id, sequence)`.
- Zero external services required for local development.

### 5.3 PostgreSQL Production Interface
- Defined specification and protocol adapter designed for `asyncpg` with strict schema migrations and connection pooling.

---

## 6. Action Firewall & Security (`packages/atlas-policy`)

- Evaluates proposed `ComputerAction` objects before they reach execution drivers.
- Classifies operations by risk:
  - `LOW`: read-only observations, page scrolling, DOM queries $\to$ `ALLOW`.
  - `MEDIUM`: form input, navigation to allowed domains $\to$ `ALLOW` or policy-dependent.
  - `HIGH`: file downloads, external form submissions, system state alterations $\to$ `REQUIRE_APPROVAL`.
  - `CRITICAL`: payments, account deletions, execution of arbitrary terminal binaries $\to$ `REQUIRE_APPROVAL` with strict MFA/explicit user sign-off.
- Domain allowlisting and regex boundary matching.

---

## 7. Structured Observability (`packages/atlas-observability`)

- Standardized JSON log records:
  - Fields: `timestamp`, `level`, `logger`, `message`, `task_id`, `session_id`, `correlation_id`, `event_type`.
- Automatic redacting filters for API keys, authorization tokens, credit cards, and credential patterns.
- High-precision timestamps (ISO 8601 UTC).

---

## 8. Interfaces: API & CLI

### 8.1 FastAPI (`apps/api`)
- `GET /health` $\to$ `{"status": "healthy", "version": "0.1.0", "timestamp": "..."}`
- `GET /v1/status` $\to$ Returns detailed component health (storage, policy engine, worker availability).

### 8.2 Developer CLI (`apps/cli`)
- `atlas doctor`: Validates local environment (Python version, Windows OS info, SQLite writable, virtualenv health).
- `atlas init`: Initializes `.atlas/` local workspace configuration and SQLite database.
- `atlas task create "<objective>"`: Submits a new task request and prints the assigned `task_id`.
- `atlas task status <task_id>`: Queries and prints current task state.

---

## 9. Phase 1 Acceptance Verification Plan

| Tracker Item | Verification Method |
|---|---|
| Monorepo & boundaries | Verified by `uv workspace` directory structure and package `pyproject.toml` files |
| AGENTS.md Constitution | Validated root file with mandatory architectural principles |
| Architecture Docs | Complete docs in `docs/` (`ARCHITECTURE.md`, `DECISIONS.md`, etc.) |
| ADR Records | ADR 0001, 0002, 0003 established in `docs/adr/` |
| Shared Schemas | Unit test validating schema creation, serialization, deserialization |
| Task State Machine | Exhaustive unit tests testing all legal transitions and rejecting illegal ones |
| SQLite Dev Storage | Integration test verifying event append, replay, sequence validation |
| PostgreSQL Interface | Design interface and contract specification in `atlas_storage/postgres.py` |
| Structured Logging | Test ensuring log output contains JSON fields and masks sensitive keys |
| FastAPI Health | TestClient test verifying `200 OK` on `/health` and `/v1/status` |
| CLI Diagnostics | Subprocess test executing `atlas doctor` and `atlas init` returning exit code 0 |
| Tests & Type Checks | `pytest` passes 100%; `ruff check` passes clean |
| CI Workflow | `.github/workflows/ci.yml` linting, checking types, and testing matrix |
| Status Tracking | Updated `docs/PROJECT_STATUS.md` and `docs/IMPLEMENTATION_PLAN.md` |
