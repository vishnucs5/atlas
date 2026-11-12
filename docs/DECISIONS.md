# Architectural Decisions Log

This document tracks Architectural Decision Records (ADRs) adopted in ATLAS. Every significant technical choice, boundary definition, and architectural pivot is documented here.

---

## Decision Register

| ID | Title | Status | Date | Decision Summary |
| :--- | :--- | :--- | :--- | :--- |
| [ADR-0001](adr/0001-monorepo-and-runtime-ownership.md) | Monorepo Workspace & Runtime Ownership | Accepted | 2026-11-12 | Maintain complete ownership of runtime orchestration; organize as a `uv` workspace; no third-party framework wrappers. |
| [ADR-0002](adr/0002-event-sourced-task-persistence.md) | Event-Sourced Task Persistence | Accepted | 2026-11-12 | Implement append-only event sourcing for all task mutations; SQLite (WAL) for local dev, PostgreSQL for production. |
| [ADR-0003](adr/0003-action-firewall-policy-separation.md) | Action Firewall & Policy Separation | Accepted | 2026-11-12 | Decouple model decision-making from execution drivers via an explicit pre-execution Action Firewall policy engine. |
| [ADR-0004](adr/0004-browser-runtime-architecture.md) | Browser Runtime & Playwright Separation | Accepted | 2026-11-12 | Isolate Playwright behind ComputerDriver protocol; enforce Action Firewall gating and deterministic verification. |

---

## Architectural Decision Summaries

### ADR-0001: Monorepo Workspace and Runtime Ownership
- **Problem**: Third-party agent frameworks (LangChain, AutoGen, CrewAI) couple orchestration, driver invocation, and memory, making deterministic verification, strict state transition enforcement, and security auditing difficult.
- **Decision**: ATLAS maintains full ownership of the runtime loop, task state machine, and driver contracts within a Python `uv` monorepo.
- **Impact**: Zero dependency bloat in `atlas-core`, strict security control, full auditability.

### ADR-0002: Event-Sourced Task Persistence
- **Problem**: Autonomous agent operations require point-in-time reconstruction, post-mortem failure analysis, and audit trails. Direct in-place updates destroy execution history.
- **Decision**: Persist every task mutation as an immutable `ExecutionEvent` in an append-only log with strictly increasing sequence numbers. Maintain a materialized `tasks` table for high-speed state lookups.
- **Impact**: Deterministic replayability, crash recovery, clean event publishing.

### ADR-0003: Action Firewall and Policy Separation
- **Problem**: AI models proposing direct operating system, file system, or browser actions can cause destructive side effects or security breaches if unconstrained.
- **Decision**: All computer action requests must be evaluated by `atlas-policy` before being dispatched to any low-level driver. Configurable policies dictate whether an action is allowed, requires approval, blocked, or dry-run.
- **Impact**: Strict enforcement of the principle "The model makes decisions; ATLAS controls execution."

---

## Contributing New ADRs

To propose an architectural decision:
1. Create a new markdown file in `docs/adr/XXXX-title-in-kebab-case.md` using the standard format:
   - Status (`Proposed`, `Accepted`, `Superseded`, `Deprecated`)
   - Context & Problem Statement
   - Decision Drivers
   - Considered Options
   - Decision Outcome
   - Pros and Cons
2. Register the entry in this document (`docs/DECISIONS.md`).
