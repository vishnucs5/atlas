# ATLAS Phase 7 Architecture: Multi-Agent Intelligence & Autonomous Orchestration

**Document Version:** 1.0.0  
**Phase:** Phase 7 — Multi-Agent Intelligence & Autonomous Orchestration  
**Status:** Architecture Specification  
**Package Target:** `packages/atlas-orchestration`, `packages/atlas-core`

---

## 1. System Vision & Architectural Invariants

Phase 7 evolves ATLAS from a single-agent autonomous runtime into a **hierarchical, fault-tolerant, multi-agent autonomous orchestration system**. In this architecture, complex tasks are decomposed into versioned Directed Acyclic Graphs (DAGs) and executed by cooperative specialist agents under strict supervisor governance, shared memory boundaries, deterministic policy firewalls, and independent quality assurance verification.

### Core Architectural Invariants:
1. **Constitutional Invariant 1 (Architecture Ownership):** Core owns orchestration, lifecycle, and tool contracts. Low-level drivers implement interfaces; they never own planning or planning state.
2. **Constitutional Invariant 2 (Action Firewall):** The model makes proposals; ATLAS controls execution. No specialist agent, model adapter, or execution worker may execute an action without explicit policy authorization.
3. **Constitutional Invariant 3 (Zero-Dependency Core):** `packages/atlas-core` contracts must never import external drivers, OS APIs, or network clients.
4. **Deterministic Subtask Boundary:** Specialist agents operate strictly within assigned subtask scopes. Cross-task memory access and unauthorized inter-agent messaging are blocked at the router layer.
5. **Independent QA Gate:** No orchestrated task can reach `COMPLETED` based solely on an agent's self-reported success. An independent `IndependentReviewer` must verify execution evidence, output artifacts, and policy compliance.
6. **Side-Effect Safety:** Non-idempotent actions in an `UNKNOWN` state are never blindly repeated during multi-agent recovery without deterministic operator reconciliation.

---

## 2. Multi-Agent Topology & Subsystems

```
                                  ┌──────────────────────────┐
                                  │      Client / API        │
                                  │  (TaskRequest / REST)    │
                                  └─────────────┬────────────┘
                                                │
                                                ▼
                                  ┌──────────────────────────┐
                                  │     Agent Supervisor     │
                                  │  - Task Decomposition    │
                                  │  - DAG Lifecycle Owner   │
                                  │  - Cancellation Bus      │
                                  └──────┬────────────┬──────┘
                                         │            │
                     ┌───────────────────┘            └────────────────────┐
                     ▼                                                     ▼
        ┌─────────────────────────┐                           ┌─────────────────────────┐
        │    Task Graph Engine    │                           │     Agent Registry      │
        │  - Versioned DAG Nodes  │                           │  - Identity & Caps      │
        │  - Dependency Tracker   │                           │  - Health & Leases      │
        │  - Parallel Branches    │                           │  - Resource Budgets     │
        └────────────┬────────────┘                           └────────────┬────────────┘
                     │                                                     │
                     └───────────────────┬─────────────────────────────────┘
                                         │
                                         ▼
                        ┌─────────────────────────────────┐
                        │    Message & Memory Router      │
                        │  - Inter-Agent Messaging (TTL)  │
                        │  - Circular Delegation Guard    │
                        │  - Task/Agent Scoped Memory     │
                        │  - Untrusted Input Sanitizer    │
                        └────────────────┬────────────────┘
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        │                                │                                │
        ▼                                ▼                                ▼
┌───────────────┐                ┌───────────────┐                ┌───────────────┐
│   Research    │                │    Browser    │                │    Desktop    │
│  Specialist   │                │  Specialist   │                │  Specialist   │
└───────┬───────┘                └───────┬───────┘                └───────┬───────┘
        │                                │                                │
        ▼                                ▼                                ▼
┌───────────────┐                ┌───────────────┐                ┌───────────────┐
│    Coding     │                │ Data Analysis │                │  Independent  │
│  Specialist   │                │  Specialist   │                │  QA Reviewer  │
└───────┬───────┘                └───────┬───────┘                └───────┬───────┘
        │                                │                                │
        └────────────────────────────────┴────────────────────────────────┘
                                         │
                                         ▼
                        ┌─────────────────────────────────┐
                        │      ATLAS ACTION FIREWALL      │
                        │  - Domain Allow/Blocklist       │
                        │  - Multi-tier SSRF Filters      │
                        │  - Approval Manager Gating      │
                        └────────────────┬────────────────┘
                                         │
                                         ▼
                        ┌─────────────────────────────────┐
                        │        Execution Drivers        │
                        │  - Playwright Browser Driver    │
                        │  - Windows Desktop Driver       │
                        └─────────────────────────────────┘
```

---

## 3. Component Specifications

### 3.1. Agent Registry (`AgentRegistry`)
- **Identity & Capabilities:** Registers agents with unique `agent_id`, human-readable `name`, declared `capabilities` (`["research", "browser", "desktop", "code", "data", "qa"]`), and supported model families.
- **Resource Bounds:** Tracks per-agent token budgets, step limits, maximum concurrency, and execution cost.
- **Lifecycle & Health:** Monitors agent states (`INITIALIZING`, `IDLE`, `BUSY`, `UNHEALTHY`, `TERMINATED`), heartbeat freshness, and automatic eviction upon lease expiration.

### 3.2. Task Graph Engine (`TaskGraphEngine`)
- **Versioned DAG Schema:** Tasks are modeled as graphs of `TaskNode` objects with directed dependency edges.
- **Execution Semantics:**
  - Sequential nodes: Execute in strict dependency order.
  - Parallel branches: Dispatch concurrently when all parent dependencies reach `COMPLETED`.
  - Conditional branches: Evaluate predicate against parent output artifacts.
  - Failure propagation: If a node fails and retry policy is exhausted, child nodes enter `CANCELLED` unless marked as optional or fallback branches.
- **Topological Integrity:** Validates cycle-free graphs using Tarjan/Kahn topological sorting before execution begins.

### 3.3. Communication Protocol (`AgentMessageRouter`)
- **Typed Message Contract:** `AgentMessage` contains `message_id`, `task_id`, `sender_id`, `recipient_id`, `correlation_id`, `message_type` (`TASK_ASSIGNMENT`, `TASK_RESULT`, `STATUS_UPDATE`, `DELEGATION_REQUEST`, `MEMORY_QUERY`, `REVIEW_FEEDBACK`), `payload`, `timestamp`, and optional `expires_at`.
- **Anti-Looping & Delegation Guards:** Tracks delegation call stacks (`delegation_path`); rejects any message cycle where an agent delegates back to an ancestor (`CircularDelegationError`).
- **Cross-Task Isolation:** Strictly forbids messages between different root `task_id` workflows.

### 3.4. Shared Memory Engine (`SharedMemoryEngine`)
- **Memory Scopes:**
  1. `TASK_SCOPED`: Ephemeral memory accessible to all specialists working on the same parent task.
  2. `AGENT_SCOPED`: Private scratchpad memory accessible only to the specific agent instance.
  3. `PROJECT_SCOPED`: Read-only curated reference knowledge across the project.
- **Untrusted Content Barrier:** Information extracted from external web pages or unverified LLM responses is marked `is_untrusted=True` and cannot override system prompts, policy rules, or task objectives.
- **Memory Versioning:** All updates produce immutable revision records with timestamp and contributor provenance.

### 3.5. Specialist Agents
All specialists inherit from `SpecialistAgent` and execute via existing ATLAS contracts (`ComputerAction`, `ModelRouter`, `ActionFirewall`):
- **Research Specialist:** Performs query formulation, synthesis, and summarization.
- **Browser Specialist:** Interacts with web applications via `PlaywrightBrowserDriver`.
- **Desktop Specialist:** Operates GUI applications via `DesktopDriver` on verified interactive desktop sessions.
- **Coding Specialist:** Generates, edits, and validates code and file artifacts.
- **Data Analysis Specialist:** Performs tabular calculations, transformations, and schema verification.
- **Independent QA Reviewer:** Analyzes deliverables against original requirements, validates evidence, and checks policy conformance.

### 3.6. Multi-Agent Recovery Coordinator (`MultiAgentRecoveryManager`)
- **Heartbeat & Lease Expiration:** Detects failed or frozen specialists using monotonic heartbeats and task leases.
- **Safe Subtask Reassignment:** Reassigns incomplete nodes to available healthy agents with identical capabilities.
- **Context Reconstruction:** Hydrates the replacement agent with the exact checkpoint state, subtask parameters, and shared task memory.
- **Idempotency Reconciliation:** Guarantees non-idempotent actions in `UNKNOWN` state require operator approval before replay.
