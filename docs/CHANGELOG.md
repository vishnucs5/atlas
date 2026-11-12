# Changelog

All notable changes to the ATLAS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - 2026-11-12 — Phase 1 Foundation & Core Lifecycle Release

### Added
- **Monorepo Architecture & Governance**:
  - Root monorepo workspace configuration using `uv` (`pyproject.toml`) linking packages (`atlas-core`, `atlas-storage`, `atlas-policy`, `atlas-observability`) and applications (`apps/api`, `apps/cli`).
  - Code style and linting configuration in `ruff.toml` targeting Python 3.11+.
  - Comprehensive `.gitignore` filtering out bytecode, test caches, virtual environments, and SQLite databases.
  - Engineering Constitution (`AGENTS.md`) enforcing 8 mandatory rules for contributors and AI agents.
  - Documentation suite: `ARCHITECTURE.md`, `DECISIONS.md`, `IMPLEMENTATION_PLAN.md`, `PROJECT_STATUS.md`, `TEST_RESULTS.md`, `KNOWN_ISSUES.md`.
  - Foundational Architectural Decision Records (ADRs):
    - `0001-monorepo-and-runtime-ownership.md`
    - `0002-event-sourced-task-persistence.md`
    - `0003-action-firewall-policy-separation.md`

- **Core Domain & State Machine (`packages/atlas-core`)**:
  - Zero-dependency Pydantic v2 data contracts with schema versioning (`"1.0"`) covering `TaskRequest`, `Task`, `ComputerAction`, `ActionTarget`, `ActionResult`, `ExecutionEvent`, `Observation`, `Session`, `Checkpoint`, `Model`, `Policy`.
  - Explicit 14-state Task State Machine enforcing strict transition rules and raising `InvalidStateTransitionError` on illegal moves.
  - Execution event emission hooks and runtime protocol definitions.

- **Action Firewall & Policy Engine (`packages/atlas-policy`)**:
  - Action firewall evaluation pipeline with `ALLOW`, `REQUIRE_APPROVAL`, and `DENY` decision types.
  - Risk classification (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
  - Destructive command pattern filters blocking catastrophic shell commands (`rm -rf /`, `mkfs`, format, fork bombs, PowerShell recursive deletion).
  - Domain security policies with allowlists, blocklists, wildcard matching, and fail-closed denial on malformed or unparseable URLs.

- **Contextual Observability & Structured Logging (`packages/atlas-observability`)**:
  - RFC-compliant structured JSON logging formatter with contextual attributes (`task_id`, `session_id`, `step_id`).
  - Async context propagation using Python `contextvars` and scoped context managers.
  - High-performance regex and key-based credential masking for OpenAI, Anthropic, Google AI, AWS, Bearer tokens, passwords, and PEM private keys.

- **Event-Sourced Storage Engine (`packages/atlas-storage`)**:
  - SQLite storage engine with WAL journal mode (`PRAGMA journal_mode=WAL`), busy timeout (5000ms), and foreign key integrity.
  - Append-only `execution_events` table guaranteeing monotonic sequence numbering per task.
  - Materialized `tasks` view with optimistic concurrency control (`expected_state`).
  - Concurrency safety with multi-connection WAL readers and transactional rollback on failure.
  - Abstract PostgreSQL storage interface specification.

- **FastAPI Service (`apps/api`)**:
  - Production FastAPI application with modular routers and lifespan management.
  - Liveness endpoint (`/health`, `/healthz`), readiness probe (`/readyz` with SQLite connection check), and detailed status (`/api/v1/status`).
  - Graceful degradation returning HTTP 503 when backing storage is unavailable.

- **Developer CLI Suite (`apps/cli`)**:
  - Click-powered `atlas` CLI command suite.
  - `atlas doctor`: Environment verification (Python 3.11+, SQLite WAL support, OS environment).
  - `atlas init`: Automated workspace initialization and database schema provisioning.
  - `atlas task`: Task lifecycle management (`create`, `list`, `inspect` with sensitive data redaction).

- **CI Matrix & Verification Suite (`.github/workflows/ci.yml`)**:
  - Cross-platform GitHub Actions matrix running on Windows 11 and Ubuntu across Python 3.11 and Python 3.12.
  - Enforced quality gates: Ruff linting (`uv run ruff check .`), Ruff formatting check (`uv run ruff format --check .`), and Pytest test suite (`uv run pytest -v`).
  - 97 automated unit and integration tests passing with 100% pass rate.
  - Complete verification of all 14 Phase 1 acceptance criteria (14/14).
