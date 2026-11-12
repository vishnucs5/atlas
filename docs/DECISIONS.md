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
| [ADR-0005](adr/0005-model-provider-adapter-architecture.md) | Model Provider Adapter Architecture | Accepted | 2026-11-12 | Decoupled adapter architecture isolating OpenAI, Anthropic, Gemini, Ollama, and vLLM behind normalized contracts. |
| [ADR-0006](adr/0006-autonomous-planning-and-execution-loop.md) | Autonomous Planning and Execution Loop | Accepted | 2026-11-12 | 11-step observe-plan-act-verify cycle enforcing Action Firewall, deterministic verification, and injection defense. |
| [ADR-0007](adr/0007-durable-execution-and-recovery.md) | Durable Execution, Worker Leases, and Crash Recovery | Accepted | 2026-11-12 | Native durable checkpoints with SHA-256 hashes, worker lease fencing tokens, action ledger with UNKNOWN state, and live reconciliation. |

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

### ADR-0004: Browser Runtime and Playwright Separation
- **Problem**: Browser automation libraries tightly couple page scripts with execution, often executing uncontrolled code.
- **Decision**: Isolate Playwright behind the ATLAS `ComputerDriver` protocol; require all browser actions to be validated by the Action Firewall and verified by `VerificationEngine`.
- **Impact**: Hermetic browser control, session isolation, robust download/upload interception.

### ADR-0005: Model Provider Adapter Architecture
- **Problem**: Vendor SDK disparities, breaking API changes, and leaky abstractions threaten core stability and violate zero-dependency core rules.
- **Decision**: Define provider-independent Pydantic v2 schemas in `atlas-core` and implement normalized, decoupled adapters for OpenAI, Anthropic, Gemini, Ollama, and OpenAI-compatible endpoints in `atlas-models`.
- **Impact**: Resilient capability routing, circuit breaking, rate limit retries, zero secret leaks, and 100% offline testability.

### ADR-0006: Autonomous Planning and Execution Loop
- **Problem**: Unconstrained autonomous agent loops suffer from infinite loops, budget exhaustion, prompt injections, and unverified actions.
- **Decision**: Implement an 11-step execution cycle in `atlas-agent` ensuring the model only acts as an untrusted advisor, with mandatory Action Firewall evaluation and post-condition verification.
- **Impact**: Deterministic task execution, prompt injection defense, bounded execution budgets, and full auditability.

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
