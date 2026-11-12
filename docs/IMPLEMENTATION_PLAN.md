# Master Implementation Plan

## Overview

This document tracks the phased implementation roadmap for ATLAS (Autonomous Task & Lifecycle Automation System).

---

## Phase 1: Foundation & Core Lifecycle

**Target:** Establish zero-dependency core domain, finite state machine, event-sourced storage, action firewall, structured observability, FastAPI service, and developer CLI.

### Task Breakdown & Progress

- [x] **Task 1: Monorepo Workspace, Governance & Documentation Scaffolding**
  - Scaffold `uv` workspace (`pyproject.toml`), `ruff.toml`, `.gitignore`.
  - Author Engineering Constitution (`AGENTS.md`) with 8 mandatory rules.
  - Establish continuity documentation (`ARCHITECTURE.md`, `DECISIONS.md`, `IMPLEMENTATION_PLAN.md`, `PROJECT_STATUS.md`, `TEST_RESULTS.md`, `KNOWN_ISSUES.md`, `CHANGELOG.md`).
  - Author foundational ADRs: ADR-0001, ADR-0002, ADR-0003.

- [ ] **Task 2: Core Data Contracts (`packages/atlas-core`)**
  - Define Pydantic v2 domain schemas (`Task`, `TaskRequest`, `TaskStatus`, `TaskPriority`).
  - Define action contracts (`ComputerAction`, `ActionTarget`, `ActionResult`, `ExpectedState`).
  - Define event, observation, checkpoint, session, model, and policy contracts.
  - Unit tests verifying contract immutability and serialization.

- [ ] **Task 3: Task State Machine & Lifecycle Exceptions (`packages/atlas-core`)**
  - Implement 14-state task state machine.
  - Implement transition validation table and `InvalidStateTransitionError`.
  - Implement transition event emission hook.
  - Comprehensive unit tests covering all valid transitions and invalid transitions.

- [x] **Task 4: Event-Sourced Storage Engine (`packages/atlas-storage`)**
  - Implement storage interface definitions (`TaskStoreProtocol`, `EventStoreProtocol`).
  - Implement SQLite storage engine with WAL mode and `busy_timeout`.
  - Implement materialized `tasks` table and append-only `execution_events` table.
  - Implement PostgreSQL abstract interface and specification.
  - Unit tests for append, query, sequence ordering, and concurrency.

- [ ] **Task 5: Action Firewall Policy Engine (`packages/atlas-policy`)**
  - Implement Action Firewall pipeline.
  - Support rule evaluations: `ALLOW`, `REQUIRE_APPROVAL`, `BLOCK`, `DRY_RUN`.
  - Implement parameter validation and target matching rules.
  - Unit tests covering safe actions, dangerous actions, and human-in-the-loop approvals.

- [ ] **Task 6: Contextual Observability & Structured Logging (`packages/atlas-observability`)**
  - Implement JSON structured formatter with contextual tags (`task_id`, `session_id`, `step_id`).
  - Implement high-speed regex secret masking for tokens, passwords, and API keys.
  - Unit tests validating JSON output and secret redaction.

- [ ] **Task 7: FastAPI Service & Health Endpoints (`apps/api`)**
  - Create FastAPI application with modular routing.
  - Expose `/healthz` (liveness), `/readyz` (readiness with SQLite check), and `/api/v1/status`.
  - Unit and API tests using `TestClient`.

- [ ] **Task 8: Developer CLI Suite (`apps/cli`)**
  - Implement `atlas` CLI commands:
    - `atlas doctor`: Check Python version, SQLite WAL support, OS environment.
    - `atlas init`: Initialize local database and default workspace directory.
    - `atlas task`: Task management subcommands (create, get, list).
  - Integration tests for CLI commands and error handling.

- [ ] **Task 9: Automated CI Workflow (`.github/workflows/ci.yml`)**
  - Multi-platform GitHub Actions matrix (Windows, Ubuntu, macOS).
  - Ruff linting, formatting check, and Pytest coverage report enforcement.

- [ ] **Task 10: System Integration & Phase 1 Verification Suite**
  - End-to-end integration test validating full task lifecycle: task creation -> event emission -> state transitions -> action firewall evaluation -> storage query -> CLI output.
  - Verify all 14 Phase 1 acceptance criteria.

- [ ] **Task 11: Final Governance, Documentation Sync & Milestone Release**
  - Synchronize documentation, update `PROJECT_STATUS.md`, `TEST_RESULTS.md`, and `CHANGELOG.md`.
  - Tag Phase 1 milestone.

---

## Future Phases

### Phase 2: Computer-Use Execution Engine & Drivers
- Browser automation driver (Playwright integration with accessibility tree introspection).
- Desktop automation driver (Windows UI Automation, mouse/keyboard input synthesis).
- Deterministic verification engine (visual screenshots, DOM element state, OCR).

### Phase 3: Autonomous Planning & Multi-Agent Collaboration
- Hierarchical planner (goal decomposition, subtask generation).
- Multi-agent collaboration protocols (specialized subagents: researcher, executor, verifier).
- Dynamic error recovery and replanning loops.

### Phase 4: Production Hardening & Enterprise Governance
- PostgreSQL and Redis production backend implementations.
- Distributed task worker queue and lease management.
- Enterprise role-based access control (RBAC), SSO, and audit export.
