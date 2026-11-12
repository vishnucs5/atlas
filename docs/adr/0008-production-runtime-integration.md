# ADR-0008: Production Runtime Integration, Orchestration, and Unified Lifecycle Management

- **Status:** Proposed & Accepted
- **Date:** 2026-11-12
- **Authors:** ATLAS Engineering Team
- **Deciders:** Principal Architect, Core & Runtime Engineering Leads
- **Supercedes:** N/A (Builds on ADR-0001 through ADR-0007)

---

## Context

Across Phases 1 through 4, the ATLAS project established critical individual subsystems:
1. **Phase 1:** Zero-dependency core contracts, 14-state task lifecycle state machine, append-only event-sourced storage (`atlas-storage`), structured JSON logging (`atlas-observability`), Action Firewall policy evaluation (`atlas-policy`), and initial health API (`apps/api`).
2. **Phase 2:** Isolated Playwright browser execution engine (`atlas-browser`), structured observation & accessibility tree extraction (`atlas-observation`), and deterministic post-condition verification (`atlas-verification`).
3. **Phase 3:** Universal model provider adapters for OpenAI, Anthropic, Gemini, Ollama, and OpenAI-compatible local models (`atlas-models`), capability-based model routing, dynamic planning, context sliding-window compaction, and the 11-step autonomous agent loop (`atlas-agent`).
4. **Phase 4:** Durable execution infrastructure (`atlas-coordination`), versioned checkpoints with SHA-256 integrity sealing (`CheckpointManager`), worker registry with heartbeat tracking, monotonic lease fencing tokens (`WorkerLeaseManager`), durable action ledger with tri-state `UNKNOWN` tracking, physical environment reconciliation (`EnvironmentReconciler`), 8-stage automated crash recovery (`RecoveryCoordinator`), and time-travel replay (`ExecutionReplayEngine`).

While each subsystem is tested and functionally complete, they currently operate as modular building blocks. The system lacks a single unified, production-oriented runtime orchestrator that binds them into a cohesive end-to-end platform. Furthermore, production deployment demands:
- A unified runtime (`ProductionRuntime`) that implements the `AtlasRuntime` contract and drives tasks through the actual 14-state machine without taking architectural shortcuts.
- A multi-driver registry supporting both browser and desktop automation drivers.
- An explicit human-in-the-loop approval management subsystem for high-risk operations.
- A secure artifact manager for screenshots, DOM dumps, and download containment.
- A production REST API, streaming event endpoints (SSE / WebSocket), and an operator dashboard.
- A secure worker communication protocol and standalone worker daemon.
- Role-based access control (RBAC) and API authentication.

---

## Architectural Decision

We decide to implement the **Phase 5 Production Runtime Integration & Orchestration** architecture with the following pillars:

### 1. Unified `ProductionRuntime` (`packages/atlas-agent` / `atlas_core.runtime`)
We implement a single runtime class, `ProductionRuntime`, implementing `AtlasRuntime`. It acts as the primary orchestrator that composes:
- **Task Lifecycle:** `TaskStateMachine` managing valid transitions across all 14 task states.
- **Planning:** `StructuredPlanner` generating typed `ExecutionPlan` steps.
- **Model Intelligence:** `ModelRouter` selecting adapters based on capability and health.
- **Context Construction:** `ContextManager` compiling compact interactive DOM summaries and history with prompt injection defense (`<untrusted_external_content>`).
- **Policy Enforcement:** `ActionFirewall` evaluating actions before execution and classifying risk levels.
- **Human Approval:** `ApprovalManager` pausing tasks into `WAITING_APPROVAL` when high-risk actions are proposed.
- **Worker Allocation:** `WorkerScheduler` assigning tasks to idle workers matching required capabilities.
- **Driver Dispatch:** `DriverRegistry` routing actions to appropriate low-level drivers (`browser.*` vs `desktop.*`).
- **Verification:** `VerificationEngine` deterministically asserting post-conditions.
- **Durable Checkpointing:** `CheckpointManager` creating sealed SHA-256 snapshots at step boundaries.
- **Fault Recovery:** `RecoveryCoordinator` executing the 8-stage recovery lifecycle on crashes or disconnects.
- **Event Sourcing:** `TaskStoreProtocol` and `EventStoreProtocol` persisting state and monotonic event streams.
- **Artifact Management:** `ArtifactManager` securely capturing screenshots, DOM snapshots, and execution logs.

### 2. Multi-Driver Abstraction (`DriverRegistry` & `DesktopDriver`)
The runtime must execute actions across multiple environments without tightly coupling the core to specific automation technologies. We introduce:
- `DriverRegistry`: Maps action type prefixes (`browser.*`, `desktop.*`) to registered `ComputerDriver` implementations.
- `DesktopDriver`: An implementation of the `ComputerDriver` protocol supporting desktop automation actions (`desktop.click`, `desktop.type`, `desktop.press_key`, `desktop.focus_window`, `desktop.screenshot`) with mockable/synthetic capabilities for hermetic testing.

### 3. Human Approval Workflow (`ApprovalManager`)
When `ActionFirewall` evaluates an action as `REQUIRE_APPROVAL` (or when recovery on an uncertain non-idempotent action demands operator intervention):
- The runtime transitions the task to `TaskStatus.WAITING_APPROVAL`.
- An `ApprovalRequest` is generated containing action ID, parameters, risk level, policy rationale, and expiration deadline.
- The runtime suspends execution until an authorized operator issues an approval grant or denial via the API or CLI.
- On grant: execution resumes cleanly from the current step.
- On denial: the task transitions to `CANCELLED` or replans with an alternative approach.

### 4. Production REST API, SSE, and Operator Dashboard (`apps/api`)
We expand `apps/api` from basic health checks into a production control plane:
- **Authentication & RBAC:** Header-based API keys (`X-Atlas-API-Key`) and Bearer tokens mapping to roles: `admin`, `operator`, `worker`, `viewer`.
- **Task CRUD & Control:** `/api/v1/tasks` (submit, get, list, cancel, pause, resume).
- **Approval Inbox:** `/api/v1/approvals` (list pending, grant, deny).
- **Real-Time Streaming:** Server-Sent Events (SSE) at `/api/v1/tasks/{task_id}/events/stream` and WebSocket streaming for live progress and timeline updates.
- **Checkpoints & Replay:** `/api/v1/tasks/{task_id}/checkpoints` and `/api/v1/tasks/{task_id}/timeline`.
- **Artifact Downloads:** `/api/v1/artifacts/{artifact_id}` with path traversal safeguards.
- **Worker Management:** `/api/v1/workers` (registration, heartbeats, status listing).
- **Embedded Operator Dashboard:** Lightweight, single-file HTML/JS dashboard at `/dashboard` displaying active tasks, worker fleet health, approval requests, and execution timelines.

### 5. Worker Daemon (`apps/cli` / `atlas worker run`)
A standalone background worker daemon process:
- Registers its hostname and capabilities (`browser`, `desktop`) with the ATLAS coordinator.
- Maintains periodic heartbeat pings to avoid lease expiration.
- Polls for assigned tasks or receives lease assignments.
- Executes actions under monotonic fencing tokens, rejecting stale commands.
- Uploads artifacts and reports execution results back to the control plane.

### 6. Artifact Management & Security
All artifacts (screenshots, DOM snapshots, logs) are managed via `ArtifactManager`:
- Stored under a configurable root directory with sanitized, UUID-based file paths preventing path traversal (`../`) attacks.
- Enforces strict file size quotas (e.g., 10MB per artifact, 100MB per task).
- Recursive secret sanitization ensures zero token or credential leakage into persistent files.

---

## Consequences

### Positive
- **Cohesive Platform:** Replaces fragmented unit components with an end-to-end, enterprise-ready orchestration runtime.
- **Guaranteed Constitution Compliance:** Every action passes through the Action Firewall (Rule 2); Core remains zero-dependency (Rule 3); verification is mandatory (Rule 7); secrets are never leaked (Rule 6).
- **True Multi-Environment Automation:** Supports both web browser and desktop computer-use workflows seamlessly.
- **Safe Human-in-the-Loop:** High-risk actions cannot execute silently without explicit operator consent.
- **Operational Visibility:** Real-time event streaming and dashboard provide complete operational transparency.

### Negative / Trade-offs
- Increased orchestration complexity requiring careful lifecycle state transitions.
- Additional background workers and API endpoints require comprehensive integration test suites and security sandboxing.

---

## References
- ADR-0001: Monorepo & Runtime Ownership
- ADR-0002: Event-Sourced Task Persistence
- ADR-0003: Action Firewall Policy Separation
- ADR-0004: Browser Runtime Architecture
- ADR-0005: Model Provider Adapter Architecture
- ADR-0006: Autonomous Planning and Execution Loop
- ADR-0007: Durable Execution and Recovery
- Constitution: `AGENTS.md`
