# ADR-0001: Monorepo Workspace and Runtime Ownership

- **Status**: Accepted
- **Date**: 2026-11-12
- **Deciders**: ATLAS Core Architecture Team
- **Technical Story**: Phase 1 Foundation

---

## Context and Problem Statement

When building autonomous AI systems that interact directly with web browsers, desktop applications, and operating systems, development teams often turn to third-party agent frameworks (e.g., LangChain, AutoGen, CrewAI). While these frameworks offer rapid prototyping abstractions, they introduce critical structural risks for production computer-use runtimes:

1. **Coupled Execution and Planning**: Third-party frameworks frequently bundle prompt engineering, planning, tool dispatch, and runtime execution into monolithic classes or leaky abstractions.
2. **Lack of Deterministic Safety Guarantees**: Framework-level tool invocations often lack pre-execution policy enforcement and transactional state tracking.
3. **Dependency Bloat and Instability**: Framework dependencies introduce rapid breaking API changes, extensive dependency trees, and security vulnerabilities.
4. **Poor OS and Environment Control**: Autonomous computer-use requires tight, deterministic integration with OS process trees, accessibility trees, and local database storage—capabilities poorly handled by generic LLM pipeline wrappers.

We need an architecture that gives ATLAS total ownership over the task lifecycle, action authorization, and execution verification, while organizing code cleanly across modular packages.

---

## Decision Drivers

- **Security & Safety Invariants**: The system must enforce that the AI model makes decisions, but ATLAS controls execution.
- **Modularity & Isolation**: Core domain logic must remain pure and free from framework lock-in or heavyweight database drivers.
- **Developer Ergonomics**: Fast package resolution, testing, and unified formatting across packages and applications.
- **Cross-Platform Target**: First-class support for Windows 11 while remaining extensible to macOS and Linux.

---

## Considered Options

1. **Option A: Wrap an existing framework (LangChain / AutoGen)**.
2. **Option B: Multi-repo architecture** (separate git repositories for core, storage, policy, and apps).
3. **Option C: Unified Python monorepo using `uv` workspace with custom runtime engine**.

---

## Decision Outcome

**Chosen Option: Option C (Unified Python monorepo using `uv` workspace with custom runtime engine)**.

ATLAS maintains complete, first-principles ownership of its runtime engine, state machine, and contracts. The codebase is organized as a Python monorepo managed with the `uv` package manager.

### Package Hierarchy & Layering Rules

```
packages/atlas-core (Zero external dependencies)
    ▲                ▲                 ▲
    │                │                 │
packages/         packages/         packages/
atlas-storage     atlas-policy      atlas-observability
    ▲                ▲                 ▲
    └────────┬───────┴─────────────────┘
             │
      apps/api & apps/cli
```

1. **Zero-Dependency Core (`packages/atlas-core`)**:
   - Contains domain models, Pydantic v2 schemas, lifecycle state machine, and interface definitions.
   - May only depend on the Python Standard Library and `pydantic`.
   - Never imports storage implementations, policy engines, OS drivers, or API frameworks.
2. **Domain Extensions (`packages/atlas-storage`, `packages/atlas-policy`, `packages/atlas-observability`)**:
   - Depend only on `packages/atlas-core`.
   - May not have circular dependencies among themselves.
3. **Applications Layer (`apps/api`, `apps/cli`)**:
   - Orchestrate the packages to provide HTTP endpoints and developer CLI interfaces.

---

## Consequences

### Positive
- **Complete Safety Control**: Every action dispatch passes through our internal firewall and lifecycle machine.
- **Fast Build & Test Cycles**: `uv` provides sub-second virtualenv syncs and deterministic resolution across all workspace members.
- **Clean Boundaries**: Strict dependency rules prevent spaghetti architecture and architectural drift.
- **Long-Term Maintainability**: Independent of third-party framework churn.

### Negative / Risks
- **Higher Initial Engineering Investment**: Core orchestration, state management, and driver abstractions must be designed and maintained in-house.
- **Workspace Tooling Management**: Requires developers to utilize modern tooling (`uv`, `ruff`) capable of handling Python workspace structures.

---

## Compliance & Verification

- CI workflow enforces `ruff` linting across all workspace packages.
- Static analysis checks ensure `packages/atlas-core` has no imports outside standard library and `pydantic`.
- Unit tests run across all workspace packages via the root `pytest.ini_options`.
