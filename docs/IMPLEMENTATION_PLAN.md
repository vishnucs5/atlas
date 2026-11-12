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

## Phase 2: Browser Execution Runtime (COMPLETE)

**Target:** Implement resilient, model-agnostic browser automation runtime using Playwright Chromium as low-level driver behind the ATLAS `ComputerDriver` contract, with multimodal observation, action execution, firewall gating, and deterministic verification.  
**Status:** **100% COMPLETE (9/9 Acceptance Criteria Verified)**  
**Completed Date:** 2026-11-12  

### Task Breakdown & Progress

- [x] **Task 2.1: Scaffolding, `ComputerDriver` Protocol & ADR-0004**
  - Define `ComputerDriver` and `DriverHealth` in `atlas_core.runtime.driver`.
  - Define browser runtime exception hierarchy (`DriverError`, `NavigationTimeoutError`, `ElementNotFoundError`, etc.).
  - Document architectural decisions in `docs/adr/0004-browser-runtime-architecture.md`.
- [x] **Task 2.2: Observation Engine (`packages/atlas-observation`)**
  - Extract structured DOM snapshots and interactive elements (`dom.py`).
  - Capture semantic accessibility trees via Chromium CDP `Accessibility.getFullAXTree` with DOM ARIA tree fallback (`accessibility.py`).
  - Capture full-page and viewport PNG screenshots with base64 data encoding (`capture.py`).
- [x] **Task 2.3: Browser Driver & Action Execution (`packages/atlas-browser`)**
  - Manage browser lifecycle (launch, headless/headed, isolated `BrowserContext`, page allocation, health check).
  - Execute core browser actions: `navigate`, `click` (by role/text/css/xpath/coords), `type`, `fill`, `select`, `scroll`, `press_key`, `wait`.
- [x] **Task 2.4: File Downloads, Uploads & Network Monitoring (`packages/atlas-browser`)**
  - Intercept downloads with path traversal prevention, SHA-256 calculation, and size tracking (`DownloadManager`).
  - Support file upload inputs with validation.
  - Intercept network requests, status codes, and console errors (`NetworkMonitor`).
- [x] **Task 2.5: Deterministic Post-Condition Verification (`packages/atlas-verification`)**
  - Implement matchers for `element_visible`, `element_hidden`, `text_present`, `url_matches`, `file_downloaded`, and `value_equals`.
  - Build `VerificationEngine` with async timeout polling for asynchronous operations.
- [x] **Task 2.6: Synthetic Fixtures & End-to-End Suite**
  - Hermetic `SyntheticServer` serving deterministic test pages (`/`, `/login`, `/interactive`, `/upload`, `/download`).
  - End-to-end integration test (`test_browser_runtime_e2e.py`) validating: Task $\to$ State Machine $\to$ Observation $\to$ Action Proposal $\to$ Action Firewall $\to$ Execution $\to$ Verification $\to$ SQLite Event Store.
- [x] **Task 2.7: Acceptance Verification & CLI Diagnostics**
  - Integrate Playwright Chromium checks into `atlas doctor`.
  - Implement `atlas environment test browser` CLI diagnostic.
  - Complete test matrix (115 tests passing).

---

## Phase 3: Model Provider Adapters & Planning Engine (IN PROGRESS - GATE VERIFIED)

**Target:** Implement provider-agnostic model adapters (OpenAI, Anthropic, Gemini, Ollama, OpenAI-compatible), resilient capability router with circuit breakers, structured planner, context manager with prompt injection defense, and the 11-step autonomous agent execution loop.  
**Status:** **DESIGN & ARCHITECTURE ACCEPTED — AWAITING IMPLEMENTATION AUTHORIZATION**  
**Roadmap Documents:** `docs/roadmap/PHASE_3_PLAN.md`, `docs/roadmap/PHASE_3_STATUS.md`, `docs/superpowers/plans/2026-11-12-phase-3-model-adapters-and-planning.md`  
**Architectural ADRs:** [ADR-0005](adr/0005-model-provider-adapter-architecture.md), [ADR-0006](adr/0006-autonomous-planning-and-execution-loop.md)

### Task Breakdown & Progress

- [x] **Task 3.1: Phase Gate Verification, Architectural Specs & ADRs**
  - Audit and accept Phase 2 final verification report (`docs/roadmap/PHASE_2_ACCEPTANCE_REPORT.md`).
  - Author ADR-0005 (Model Provider Adapter Architecture) and ADR-0006 (Autonomous Planning and Execution Loop).
  - Publish architecture specs: `docs/architecture/model-provider-architecture.md` and `docs/architecture/planning-engine.md`.
  - Establish `docs/roadmap/PHASE_3_PLAN.md` and `docs/roadmap/PHASE_3_STATUS.md`.
- [ ] **Task 3.2: Core Model Contracts (`packages/atlas-core`)**
  - Define `ModelMessage`, `TextPart`, `ImagePart`, `ToolDefinition`, `ToolCall`, `TokenUsage`, `ProviderHealth`, `ModelError`.
  - Unit tests verifying contract immutability and schema versioning.
- [ ] **Task 3.3: Scaffolding `packages/atlas-models` & `ModelAdapter` Protocol**
  - Define `ModelAdapter` protocol with async completion, streaming, health check, and capability discovery.
  - Establish credential sanitization helpers.
- [ ] **Task 3.4: Concrete Provider Adapters**
  - Implement `OpenAIAdapter`, `AnthropicAdapter`, `GeminiAdapter`, `OllamaAdapter`, `OpenAICompatibleAdapter`.
  - Normalize tool calling, vision, and token usage reporting across all adapters.
  - Unit tests running 100% offline via mock HTTP transports.
- [ ] **Task 3.5: Model Router, Circuit Breaker & Cost Accounting**
  - Capability-based routing, health-check probing, circuit breakers, rate-limit retry with jitter, cost tracking.
- [ ] **Task 3.6: Structured Planner Engine (`packages/atlas-agent`)**
  - Implement `ExecutionPlan`, `PlanStep`, `PlanBudget`, and `StructuredPlanner` with dynamic replanning.
- [ ] **Task 3.7: Context Management & Injection Demarcation**
  - DOM summarization to interactive nodes, screenshot optimization, sliding window pruning, and `<untrusted_external_content>` demarcation.
- [ ] **Task 3.8: 11-Step Autonomous Agent Loop & Safety Engine**
  - Enforce the 11-step execution cycle with Action Firewall gating and deterministic post-condition verification.
  - Enforce action idempotency loop detection and execution budgets.
- [ ] **Task 3.9: End-to-End Integration Suite & Acceptance Verification**
  - Synthetic end-to-end integration test with mock LLM and browser driver.

---

## Phase 4: Production Hardening & Enterprise Governance (Upcoming)
- PostgreSQL and Redis production backend implementations.
- Distributed task worker queue and lease management.
- Enterprise role-based access control (RBAC), SSO, and audit export.
