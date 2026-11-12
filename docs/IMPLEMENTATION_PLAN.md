# Master Implementation Plan

## Overview

This document tracks the phased implementation roadmap for ATLAS (Autonomous Task & Lifecycle Automation System).

---

## Phase 1: Foundation & Core Lifecycle (COMPLETE)

**Target:** Establish zero-dependency core domain, finite state machine, event-sourced storage, action firewall, structured observability, FastAPI service, developer CLI, and multi-platform CI verification matrix.  
**Status:** **100% COMPLETE (14/14 Acceptance Criteria Verified)**  
**Completed Date:** 2026-11-12  

### Task Breakdown & Progress

- [x] **Task 1: Monorepo Workspace, Governance & Documentation Scaffolding**
  - Scaffold `uv` workspace (`pyproject.toml`), `ruff.toml`, `.gitignore`.
  - Author Engineering Constitution (`AGENTS.md`) with 8 mandatory rules.
  - Establish continuity documentation (`ARCHITECTURE.md`, `DECISIONS.md`, `IMPLEMENTATION_PLAN.md`, `PROJECT_STATUS.md`, `TEST_RESULTS.md`, `KNOWN_ISSUES.md`, `CHANGELOG.md`).
  - Author foundational ADRs: ADR-0001, ADR-0002, ADR-0003.

- [x] **Task 2: Core Data Contracts (`packages/atlas-core`)**
  - Define Pydantic v2 domain schemas (`Task`, `TaskRequest`, `TaskStatus`, `TaskPriority`).
  - Define action contracts (`ComputerAction`, `ActionTarget`, `ActionResult`, `ExpectedState`).
  - Define event, observation, checkpoint, session, model, and policy contracts.
  - Unit tests verifying contract immutability, schema versioning ("1.0"), and serialization.

- [x] **Task 3: Task State Machine & Lifecycle Exceptions (`packages/atlas-core`)**
  - Implement 14-state task state machine.
  - Implement transition validation table and `InvalidStateTransitionError`.
  - Implement transition event emission hook and runtime protocol.
  - Comprehensive unit tests covering all valid transitions, invalid transitions, and terminal locking.

- [x] **Task 4: Action Firewall Policy Engine (`packages/atlas-policy`)**
  - Implement Action Firewall pipeline and evaluation rules (`ALLOW`, `REQUIRE_APPROVAL`, `DENY`).
  - Destructive command inspection (`rm -rf`, `format`, `dd`, fork bomb).
  - Domain allowlist and blocklist filtering with failsafe deny on malformed URLs.
  - Parameter validation and target matching rules.

- [x] **Task 5: Contextual Observability & Structured Logging (`packages/atlas-observability`)**
  - Implement JSON structured formatter with contextual tags (`task_id`, `session_id`, `step_id`).
  - Contextvars async context propagation and context scoping.
  - High-speed regex and key-based secret masking for API tokens, passwords, and private keys.
  - Unit tests validating JSON formatting, isolation, and secret redaction.

- [x] **Task 6: Event-Sourced Storage Engine (`packages/atlas-storage`)**
  - Implement storage interface definitions (`TaskStoreProtocol`, `EventStoreProtocol`).
  - Implement SQLite storage engine with WAL mode, busy timeout, and connection pragmas.
  - Implement materialized `tasks` table with optimistic concurrency control.
  - Implement append-only `execution_events` table with monotonic sequence guarantees.
  - Implement PostgreSQL abstract interface and specification.
  - Unit tests for append, query, sequence ordering, concurrency, and rollback.

- [x] **Task 7: FastAPI Service & Health Endpoints (`apps/api`)**
  - Create FastAPI application with modular routing and lifespan management.
  - Expose `/healthz` (liveness), `/readyz` (readiness with SQLite storage validation), and `/api/v1/status`.
  - Handle degraded storage states with HTTP 503 response.
  - Comprehensive API tests using `TestClient`.

- [x] **Task 8: Developer CLI Suite (`apps/cli`)**
  - Implement Click-based `atlas` CLI commands:
    - `atlas doctor`: Check Python version, SQLite WAL support, OS environment, and directory health.
    - `atlas init`: Initialize local database and workspace directory with automatic migration.
    - `atlas task`: Task management subcommands (`create`, `list`, `inspect` with secret masking).
  - Integration tests for CLI commands, argument parsing, and error handling.

- [x] **Task 9: Automated CI Workflow, Test Matrix & Phase 1 Acceptance Verification**
  - Cross-platform GitHub Actions matrix (`.github/workflows/ci.yml`) targeting Windows and Ubuntu/Linux across Python 3.11 and 3.12.
  - Ruff linting (`uv run ruff check .`), Ruff formatting check (`uv run ruff format --check .`), and Pytest (`uv run pytest -v`).
  - Verification of all 14 Phase 1 acceptance criteria (97 passed tests across unit and integration suites).
  - Update project status, test results ledger, changelog, and implementation plan.

---

## Next Phase

### Phase 2: Computer-Use Execution Engine & Drivers (Upcoming)
- **Browser Automation Driver**:
  - Playwright integration with accessibility tree (a11y tree) introspection and ARIA selector resolution.
  - Action execution: click, type, scroll, drag, wait for state.
  - Session lifecycle and cookie/storage persistence.
- **Desktop Automation Driver**:
  - Windows UI Automation (UIA) driver for native application control.
  - Synthetic input dispatch with rate limiting and hardware simulation.
- **Deterministic Verification Engine**:
  - Visual screenshot capture and perceptual diffing.
  - DOM state and accessibility condition assertions.
  - Post-action invariant verification before advancing lifecycle states.

---

## Future Phases

### Phase 3: Autonomous Planning & Multi-Agent Collaboration
- Hierarchical planner (goal decomposition, subtask generation).
- Multi-agent collaboration protocols (specialized subagents: researcher, executor, verifier).
- Dynamic error recovery and replanning loops.

### Phase 4: Production Hardening & Enterprise Governance
- PostgreSQL and Redis production backend implementations.
- Distributed task worker queue and lease management.
- Enterprise role-based access control (RBAC), SSO, and audit export.
