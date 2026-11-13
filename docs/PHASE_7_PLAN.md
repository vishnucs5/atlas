# ATLAS Phase 7 Master Implementation Plan: Multi-Agent Intelligence & Autonomous Orchestration

**Target Branch:** `feat/phase-7-multi-agent-orchestration`  
**Base Commit (Phase 6.1):** `569dbb5`  
**Start Date:** 2026-11-13  
**Status:** **IN PROGRESS (Milestone 0 Started)**

---

## 1. Executive Objectives

1. Create a zero-dependency domain contract foundation for multi-agent systems (`atlas-core`).
2. Build the `atlas-orchestration` package containing:
   - Agent Registry (`AgentRegistry`)
   - Task Graph Engine (`TaskGraphEngine`)
   - Inter-Agent Communication Protocol (`AgentMessageRouter`)
   - Shared Memory Engine (`SharedMemoryEngine`)
   - Modular Specialist Agents (Research, Browser, Desktop, Coding, Data, QA)
   - Agent Supervisor (`AgentSupervisor`)
   - Independent QA Reviewer (`IndependentReviewer`)
   - Multi-Agent Recovery Coordinator (`MultiAgentRecoveryManager`)
3. Extend REST API (`apps/api`) with versioned endpoints for multi-agent orchestration.
4. Extend the Operator Dashboard with multi-agent DAG visualization and message tracing.
5. Create comprehensive acceptance tests (`tests/integration/test_phase7_acceptance.py`) verifying all multi-agent requirements.
6. Verify 100% green regression across all previous phases (Phases 1–6.1).

---

## 2. Milestone Breakdown & Delivery Plan

### Milestone 0: Audit, Baseline Verification & Phase 7 Architecture
- Verify Phase 6.1 baseline (320 tests green).
- Create `docs/PHASE_7_ARCHITECTURE.md`, `docs/PHASE_7_PLAN.md`, `docs/PHASE_7_STATUS.md`, `docs/PHASE_7_RISK_REGISTER.md`.
- Register `packages/atlas-orchestration` in `pyproject.toml`.

### Milestone 1: Multi-Agent Core Contracts & Agent Registry
- Define core multi-agent schemas in `packages/atlas-core/src/atlas_core/contracts/agent.py`:
  - `AgentDescriptor`, `AgentCapability`, `AgentStatus`, `AgentBudget`, `AgentLease`.
- Implement `AgentRegistry` in `packages/atlas-orchestration/src/atlas_orchestration/registry.py`:
  - Agent enrollment, capability mapping, health monitoring, concurrency controls, token budget enforcement.
- Unit tests for contract validation and registry operations (`tests/unit/test_agent_registry.py`).

### Milestone 2: Task Graph Engine & Versioned DAG Execution
- Define graph contracts in `packages/atlas-core/src/atlas_core/contracts/graph.py`:
  - `TaskNode`, `TaskEdge`, `TaskGraph`, `NodeStatus`, `DependencyType`.
- Implement `TaskGraphEngine` in `packages/atlas-orchestration/src/atlas_orchestration/graph_engine.py`:
  - DAG construction, cycle detection (Kahn's algorithm), topological sorting, parallel branch resolution, failure propagation, conditional branching, replanning, and graph serialization.
- Unit tests for DAG operations, cycle rejection, and parallel resolution (`tests/unit/test_task_graph_engine.py`).

### Milestone 3: Inter-Agent Communication Protocol & Shared Memory Engine
- Define message and memory contracts in `packages/atlas-core/src/atlas_core/contracts/message.py` & `memory.py`:
  - `AgentMessage`, `AgentMessageType`, `MemoryScope`, `MemoryEntry`.
- Implement `AgentMessageRouter` in `packages/atlas-orchestration/src/atlas_orchestration/messaging.py`:
  - Typed message routing, cryptographic ID, delegation call-stack tracking, circular delegation detection, TTL expiration, cross-task message rejection.
- Implement `SharedMemoryEngine` in `packages/atlas-orchestration/src/atlas_orchestration/memory.py`:
  - Scoped storage (`TASK`, `AGENT`, `PROJECT`), access control matrix, memory versioning, context summarization, untrusted content marking (`is_untrusted`).
- Unit tests for messaging, anti-looping guards, and memory scoping (`tests/unit/test_agent_messaging_and_memory.py`).

### Milestone 4: Specialist Agents & Capability-Based Routing
- Implement `SpecialistAgent` base class in `packages/atlas-orchestration/src/atlas_orchestration/specialist.py`.
- Implement concrete specialist agents:
  - `ResearchSpecialist`: query formulation and synthesis.
  - `BrowserSpecialist`: browser automation via existing `ComputerDriver`.
  - `DesktopSpecialist`: desktop automation via existing `DesktopDriver`.
  - `CodingSpecialist`: code and workspace modification.
  - `DataAnalysisSpecialist`: structured metrics and data transformations.
  - `QASpecialist`: validation and verification.
- Model router integration: capability-based model selection (`atlas-models`).
- Unit tests for specialists and execution routing (`tests/unit/test_specialist_agents.py`).

### Milestone 5: Agent Supervisor, Independent QA Reviewer & Recovery Coordinator
- Implement `AgentSupervisor` in `packages/atlas-orchestration/src/atlas_orchestration/supervisor.py`:
  - Task decomposition, subtask dispatch, parallel scheduling, dependency resolution, cancellation bus.
- Implement `IndependentReviewer` in `packages/atlas-orchestration/src/atlas_orchestration/reviewer.py`:
  - Verification of task completion, artifact inspection, policy compliance check, feedback loops for replanning.
- Implement `MultiAgentRecoveryManager` in `packages/atlas-orchestration/src/atlas_orchestration/recovery.py`:
  - Specialist crash detection, lease expiration handling, safe task reassignment, state hydration, side-effect reconciliation.
- Unit tests for supervisor orchestration, reviewer rejection, and recovery (`tests/unit/test_agent_supervisor.py`).

### Milestone 6: REST API, Dashboard Integration & End-to-End Acceptance Suite
- Implement API routes in `apps/api/src/atlas_api/routes/orchestration.py`:
  - `/api/v1/orchestration/agents`
  - `/api/v1/orchestration/graphs`
  - `/api/v1/orchestration/messages`
  - `/api/v1/orchestration/memory`
- Update dashboard with multi-agent orchestration views.
- Implement comprehensive 15-scenario Phase 7 acceptance suite (`tests/integration/test_phase7_acceptance.py`).
- Run full monorepo regression suite (Phases 1–7).
- Update documentation: `docs/CHANGELOG.md`, `docs/PROJECT_STATUS.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/PHASE_7_ACCEPTANCE_REPORT.md`.
