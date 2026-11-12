# Pull Request: ATLAS Phase 1 — Foundation & Core Lifecycle

- **Branch:** `feat/phase-1-foundation`
- **Target Branch:** `master`
- **Latest Commit Hash:** `e8e8927`
- **Status:** Ready for Review (All 97 tests passing, CI configured)

---

## 1. Executive Summary

This Pull Request delivers **Phase 1 (Foundation & Core Lifecycle)** of **ATLAS (Autonomous Task & Lifecycle Automation System)**—an open-source, model-agnostic computer-use runtime designed around the central axiom:

> **The model makes decisions. ATLAS controls execution.**

Phase 1 establishes the monorepo workspace, core contracts, task lifecycle state machine, security Action Firewall, event-sourced SQLite storage engine, context-aware structured logging, FastAPI health service, developer CLI, and cross-platform GitHub Actions CI workflow.

---

## 2. All 14 Acceptance Criteria Verification

| ID | Acceptance Criterion | Status | Verification Detail |
|---|---|:---:|---|
| **AC-01** | Monorepo created with agreed package boundaries | ✅ Complete | Modular `uv` workspace with `atlas-core`, `atlas-storage`, `atlas-policy`, `atlas-observability`, `apps/api`, `apps/cli` |
| **AC-02** | `AGENTS.md` and engineering constitution created | ✅ Complete | Codified the 8 mandatory rules into root `AGENTS.md` |
| **AC-03** | Architecture documentation published | ✅ Complete | Published comprehensive target architecture in `docs/ARCHITECTURE.md` |
| **AC-04** | ADR records established | ✅ Complete | Created `docs/adr/0001`, `0002`, and `0003` covering runtime ownership, event sourcing, and action firewall |
| **AC-05** | Shared task and action schemas implemented | ✅ Complete | Zero-dependency Pydantic v2 schemas in `packages/atlas-core/src/atlas_core/contracts/` (`Task`, `ComputerAction`, `Observation`, `ExecutionEvent`, etc.) |
| **AC-06** | Task state machine implemented | ✅ Complete | Explicit 14-state machine in `packages/atlas-core/src/atlas_core/lifecycle/state_machine.py` with `InvalidStateTransitionError` |
| **AC-07** | SQLite development storage working | ✅ Complete | Event-sourced SQLite store in `packages/atlas-storage/src/atlas_storage/sqlite.py` with WAL mode, unique sequence constraints, and optimistic locking |
| **AC-08** | PostgreSQL production storage interface designed | ✅ Complete | Production DDL and asyncpg interface specification in `packages/atlas-storage/src/atlas_storage/postgres.py` |
| **AC-09** | Structured logging and event IDs working | ✅ Complete | Context-bound JSON logger in `packages/atlas-observability/src/atlas_observability/logging.py` with multi-provider secret redaction |
| **AC-10** | FastAPI health endpoint working | ✅ Complete | Service in `apps/api/src/atlas_api/` exposing `GET /health`, `GET /healthz`, and `GET /v1/status` |
| **AC-11** | CLI initializes and reports system health | ✅ Complete | Developer CLI in `apps/cli/src/atlas_cli/` with `atlas doctor`, `atlas init`, and `atlas task` commands |
| **AC-12** | Unit tests and type checking passing | ✅ Complete | 97/97 tests passing in ~4.5s; clean `ruff check` and `ruff format` |
| **AC-13** | CI workflow configured | ✅ Complete | `.github/workflows/ci.yml` matrix testing across Windows and Linux, Python 3.11 and 3.12 |
| **AC-14** | `PROJECT_STATUS.md` and `IMPLEMENTATION_PLAN.md` updated | ✅ Complete | Durable continuity tracking established and updated |

---

## 3. Architecture & ADR Changes

- **ADR-0001 (Core Runtime Ownership)**: ATLAS owns orchestration, lifecycle, and tool contracts directly. External libraries serve strictly as low-level drivers. `atlas-core` maintains zero external runtime dependencies.
- **ADR-0002 (Event Sourcing & Persistence)**: All mutations append immutable `ExecutionEvent` records to an event store alongside a synchronous materialized task view projection. Local development uses SQLite in WAL mode; production uses PostgreSQL.
- **ADR-0003 (Action Firewall & Policy Separation)**: Every computer action proposed by an AI model must pass through the `ActionFirewall` before reaching execution drivers.

---

## 4. Security Implementation Details

- **Action Firewall Multi-Gate Pipeline**:
  - Gate 1: Target domain validation against allowed and blocked domains with fail-closed handling on malformed URLs.
  - Gate 2: Destructive command pattern matching (Unix `rm -rf`, `mkfs`, `dd`, fork bombs; Windows `rmdir /s`, `del /f /s /q`, `format`, `Remove-Item -Recurse -Force`).
  - Gate 3: Custom prioritized policy rules.
  - Gate 4: Built-in category rules (`terminal.` actions require approval; low-risk observations auto-allowed).
- **Dual-Layer Secret Redaction (Constitution Rule 6)**:
  - Masking across raw log strings and structured dictionaries.
  - Redacts OpenAI, Anthropic, Gemini, AWS Access/Secret keys, GitHub tokens, JWTs, PEM private keys, Basic/Bearer authorization headers, and credential key-value pairs.
- **CORS Protection**:
  - `apps/api` disables `allow_credentials` when wildcard origins (`*`) are configured.

---

## 5. Test Results & CI Status

- **Unit & Integration Tests**: 97 tests passed across 7 test suites:
  - `tests/integration/test_cli.py`: 6 passed
  - `tests/unit/test_api_health.py`: 10 passed
  - `tests/unit/test_contracts.py`: 11 passed
  - `tests/unit/test_observability.py`: 18 passed
  - `tests/unit/test_policy_firewall.py`: 29 passed
  - `tests/unit/test_sqlite_storage.py`: 13 passed
  - `tests/unit/test_state_machine.py`: 10 passed
- **Linter & Formatter**: `ruff check .` $\to$ clean; `ruff format --check .` $\to$ clean across all 64 files.
- **CI Pipeline**: `.github/workflows/ci.yml` runs on every push and PR across `windows-latest` and `ubuntu-latest` against Python 3.11 and 3.12.

---

## 6. Known Limitations & Technical Debt (Triaged for Future Phases)

1. **AwareDatetime in Contracts**: Contract timestamps currently accept naive datetimes; will transition to `pydantic.AwareDatetime` in Phase 2.
2. **EventType Semantic Granularity**: State transition mapping currently aliases certain intermediate events (e.g. `PLANNING` $\to$ `PLAN_GENERATED`); dedicated event types (`PLANNING_STARTED`, `VERIFICATION_STARTED`, `TASK_EXPIRED`) will be added in Phase 2/3.
3. **PostgreSQL Implementation**: Only schema specification and interfaces are delivered in Phase 1; live `asyncpg` connection pool will be provisioned in Phase 4.
