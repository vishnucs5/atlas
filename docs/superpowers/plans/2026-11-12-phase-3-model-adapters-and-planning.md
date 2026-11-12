# Phase 3: Model Provider Adapters & Autonomous Planning Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the provider-agnostic model interaction layer (supporting OpenAI, Anthropic, Gemini, Ollama, and OpenAI-compatible endpoints) and the 11-step autonomous planning engine for ATLAS.

**Architecture:** Decouple core model contracts in `atlas-core` with zero vendor SDKs, implement normalized adapters and resilient routing in `atlas-models`, and build the structured planner, context manager, and 11-step agent loop in `atlas-agent` with strict Action Firewall gating and deterministic verification.

**Tech Stack:** Python 3.11+, Pydantic v2, `httpx`, Playwright Chromium, SQLite WAL.

**Spec:** `docs/architecture/model-provider-architecture.md`, `docs/architecture/planning-engine.md`, `docs/adr/0005-model-provider-adapter-architecture.md`, `docs/adr/0006-autonomous-planning-and-execution-loop.md`.

## Global Constraints
- `packages/atlas-core` must NEVER import external driver or vendor SDK libraries (Rule 3).
- The model makes decisions; ATLAS controls execution (Rule 2). All actions must pass through `ActionFirewall.evaluate(action)`.
- Every action must be verified deterministically via `VerificationEngine` (Rule 7).
- All credentials, tokens, and keys must be redacted from logs, errors, and traces (Rule 6).
- All tests must run 100% offline without requiring paid API keys.
- Do not merge to master or push to remote without explicit user authorization.

---

### Task 1: Core Model Contracts (`packages/atlas-core`)

**Files:**
- Modify: `packages/atlas-core/src/atlas_core/contracts/model.py`
- Modify: `packages/atlas-core/src/atlas_core/contracts/__init__.py`
- Create: `tests/unit/test_model_contracts.py`

**Interfaces:**
- Consumes: Standard Python types, `pydantic.BaseModel`.
- Produces: `ModelMessage`, `TextPart`, `ImagePart`, `ToolDefinition`, `ToolCall`, `TokenUsage`, `ProviderHealth`, `ModelError`, enhanced `ModelRequest` and `ModelResponse`.

- [ ] **Step 1: Write failing unit tests for model contracts**
  Create `tests/unit/test_model_contracts.py` testing creation, serialization, validation, and schema version `"1.0"` for all new and enhanced model contracts.
- [ ] **Step 2: Run test to confirm failure**
  Run `uv run pytest tests/unit/test_model_contracts.py` and observe `ImportError` or `AttributeError`.
- [ ] **Step 3: Implement model contracts in `packages/atlas-core`**
  Update `packages/atlas-core/src/atlas_core/contracts/model.py` and `__init__.py` to export the new contracts.
- [ ] **Step 4: Run tests to confirm pass**
  Run `uv run pytest tests/unit/test_model_contracts.py` and verify all tests pass.
- [ ] **Step 5: Commit changes**
  Commit as `feat(core): implement typed model and tool contracts in atlas-core`.

---

### Task 2: Package Scaffolding & Adapter Protocol (`packages/atlas-models`)

**Files:**
- Create: `packages/atlas-models/pyproject.toml`
- Create: `packages/atlas-models/src/atlas_models/__init__.py`
- Create: `packages/atlas-models/src/atlas_models/adapter.py`
- Modify: `pyproject.toml` (workspace members, pythonpath, pyright extraPaths)
- Create: `tests/unit/test_adapter_protocol.py`

**Interfaces:**
- Consumes: `atlas_core.contracts.model.*`
- Produces: `ModelAdapter` abstract base class with async `complete()`, `stream()`, `health_check()`, `get_capabilities()`, and credential sanitization helpers.

- [ ] **Step 1: Write failing test for adapter protocol**
  Create `tests/unit/test_adapter_protocol.py` verifying that subclassing `ModelAdapter` requires implementing the interface.
- [ ] **Step 2: Run test to confirm failure**
  Run `uv run pytest tests/unit/test_adapter_protocol.py`.
- [ ] **Step 3: Scaffold package and implement `ModelAdapter`**
  Create `packages/atlas-models` package and implement `ModelAdapter` in `adapter.py`. Update root `pyproject.toml` workspace members and pythonpath.
- [ ] **Step 4: Run tests and type check**
  Run `uv run pytest tests/unit/test_adapter_protocol.py` and `uv run --with pyright pyright`.
- [ ] **Step 5: Commit changes**
  Commit as `feat(models): scaffold atlas-models package and define ModelAdapter protocol`.

---

### Task 3: Provider Adapters (OpenAI, Anthropic, Gemini, Ollama, OpenAI-Compatible)

**Files:**
- Create: `packages/atlas-models/src/atlas_models/adapters/openai.py`
- Create: `packages/atlas-models/src/atlas_models/adapters/anthropic.py`
- Create: `packages/atlas-models/src/atlas_models/adapters/gemini.py`
- Create: `packages/atlas-models/src/atlas_models/adapters/ollama.py`
- Create: `packages/atlas-models/src/atlas_models/adapters/openai_compatible.py`
- Create: `packages/atlas-models/src/atlas_models/adapters/__init__.py`
- Create: `tests/unit/test_model_adapters.py`

**Interfaces:**
- Consumes: `ModelAdapter`, `ModelRequest`, `httpx`
- Produces: `OpenAIAdapter`, `AnthropicAdapter`, `GeminiAdapter`, `OllamaAdapter`, `OpenAICompatibleAdapter`.

- [ ] **Step 1: Write mock-based unit tests for all 5 adapters**
  Create `tests/unit/test_model_adapters.py` using `httpx.MockTransport` covering text completion, tool calling, vision payloads, token usage extraction, and error normalization for each provider.
- [ ] **Step 2: Run tests to confirm failure**
  Run `uv run pytest tests/unit/test_model_adapters.py`.
- [ ] **Step 3: Implement concrete adapters**
  Implement each adapter with payload translation, tool calling schema mappings, image part encoding, and secret redaction.
- [ ] **Step 4: Run tests to confirm pass**
  Run `uv run pytest tests/unit/test_model_adapters.py` and verify all tests pass offline.
- [ ] **Step 5: Commit changes**
  Commit as `feat(models): implement normalized adapters for OpenAI, Anthropic, Gemini, Ollama, and OpenAI-compatible`.

---

### Task 4: Model Router, Circuit Breakers & Cost Tracker

**Files:**
- Create: `packages/atlas-models/src/atlas_models/router.py`
- Create: `tests/unit/test_model_router.py`

**Interfaces:**
- Consumes: `ModelAdapter`, `ModelRequest`, `ModelResponse`, `ModelCapabilities`.
- Produces: `ModelRouter`, `CircuitBreaker`, `CostTracker`.

- [ ] **Step 1: Write unit tests for ModelRouter**
  Create `tests/unit/test_model_router.py` testing capability filtering, circuit breaker trip/reset, rate-limit retry with backoff, fallback cascade, and token/cost accumulation.
- [ ] **Step 2: Run tests to confirm failure**
  Run `uv run pytest tests/unit/test_model_router.py`.
- [ ] **Step 3: Implement ModelRouter, CircuitBreaker, and CostTracker**
  Implement in `packages/atlas-models/src/atlas_models/router.py`.
- [ ] **Step 4: Run tests to confirm pass**
  Run `uv run pytest tests/unit/test_model_router.py`.
- [ ] **Step 5: Commit changes**
  Commit as `feat(models): implement capability-aware ModelRouter with circuit breaker and cost tracking`.

---

### Task 5: Structured Planner Engine (`packages/atlas-agent`)

**Files:**
- Create: `packages/atlas-agent/pyproject.toml`
- Create: `packages/atlas-agent/src/atlas_agent/__init__.py`
- Create: `packages/atlas-agent/src/atlas_agent/planner.py`
- Modify: `pyproject.toml` (workspace members, pythonpath, pyright extraPaths)
- Create: `tests/unit/test_planner.py`

**Interfaces:**
- Consumes: `Task`, `Observation`, `ComputerAction`, `ExpectedState`.
- Produces: `ExecutionPlan`, `PlanStep`, `PlanBudget`, `StructuredPlanner`.

- [ ] **Step 1: Write unit tests for StructuredPlanner**
  Create `tests/unit/test_planner.py` testing plan decomposition, step validation against action schemas, dynamic replanning on failure, and replan budget limits.
- [ ] **Step 2: Run tests to confirm failure**
  Run `uv run pytest tests/unit/test_planner.py`.
- [ ] **Step 3: Scaffold package and implement StructuredPlanner**
  Create `packages/atlas-agent` and implement `planner.py`. Update root `pyproject.toml`.
- [ ] **Step 4: Run tests to confirm pass**
  Run `uv run pytest tests/unit/test_planner.py`.
- [ ] **Step 5: Commit changes**
  Commit as `feat(agent): scaffold atlas-agent package and implement StructuredPlanner`.

---

### Task 6: Context & Memory Management

**Files:**
- Create: `packages/atlas-agent/src/atlas_agent/context.py`
- Create: `tests/unit/test_context_manager.py`

**Interfaces:**
- Consumes: `Observation`, `ModelMessage`, `Task`.
- Produces: `ContextManager`, `DOMSummarizer`, `TaskMemory`, and prompt injection demarcation utilities.

- [ ] **Step 1: Write unit tests for ContextManager**
  Create `tests/unit/test_context_manager.py` testing sliding window pruning, DOM summarization to interactive nodes, prompt injection `<untrusted_external_content>` demarcation, and memory scratchpad.
- [ ] **Step 2: Run tests to confirm failure**
  Run `uv run pytest tests/unit/test_context_manager.py`.
- [ ] **Step 3: Implement ContextManager, DOMSummarizer, and TaskMemory**
  Implement in `packages/atlas-agent/src/atlas_agent/context.py`.
- [ ] **Step 4: Run tests to confirm pass**
  Run `uv run pytest tests/unit/test_context_manager.py`.
- [ ] **Step 5: Commit changes**
  Commit as `feat(agent): implement ContextManager, DOM summarization, and prompt injection defense`.

---

### Task 7: 11-Step Autonomous Agent Loop & Safety Engine

**Files:**
- Create: `packages/atlas-agent/src/atlas_agent/safety.py`
- Create: `packages/atlas-agent/src/atlas_agent/loop.py`
- Create: `tests/unit/test_agent_safety.py`
- Create: `tests/unit/test_agent_loop.py`

**Interfaces:**
- Consumes: `ModelRouter`, `ActionFirewall`, `ComputerDriver`, `VerificationEngine`, `EventStore`, `StructuredPlanner`, `ContextManager`.
- Produces: `AutonomousAgentLoop`, `SafetyEngine`, loop execution events.

- [ ] **Step 1: Write unit tests for SafetyEngine and AutonomousAgentLoop**
  Create `tests/unit/test_agent_safety.py` and `tests/unit/test_agent_loop.py` testing iteration bounds, action idempotency loop breaking, firewall DENY containment, and the 11-step execution sequence.
- [ ] **Step 2: Run tests to confirm failure**
  Run `uv run pytest tests/unit/test_agent_safety.py tests/unit/test_agent_loop.py`.
- [ ] **Step 3: Implement SafetyEngine and AutonomousAgentLoop**
  Implement `safety.py` and `loop.py` enforcing the 11-step cycle and strict Action Firewall checks before driver execution.
- [ ] **Step 4: Run tests to confirm pass**
  Run `uv run pytest tests/unit/test_agent_safety.py tests/unit/test_agent_loop.py`.
- [ ] **Step 5: Commit changes**
  Commit as `feat(agent): implement 11-step AutonomousAgentLoop and SafetyEngine`.

---

### Task 8: End-to-End Integration Test Suite

**Files:**
- Create: `tests/integration/test_autonomous_agent_e2e.py`
- Create: `scripts/demo_autonomous_agent.py`

**Interfaces:**
- Consumes: `AutonomousAgentLoop`, `PlaywrightBrowserDriver`, `SyntheticServer`, `ActionFirewall`, `VerificationEngine`, `SQLiteEventStore`.
- Produces: Verifiable end-to-end autonomous agent workflow evidence.

- [ ] **Step 1: Write end-to-end integration test**
  Create `tests/integration/test_autonomous_agent_e2e.py` simulating an end-to-end browser workflow where an agent observes a synthetic login/form page, requests model actions, passes firewall gating, executes actions, verifies expected states, and records events into SQLite.
- [ ] **Step 2: Run integration tests**
  Run `uv run pytest tests/integration/test_autonomous_agent_e2e.py -v`.
- [ ] **Step 3: Create executable demo script**
  Create `scripts/demo_autonomous_agent.py` for standalone verification and visual inspection.
- [ ] **Step 4: Verify complete test suite and code quality**
  Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run --with pyright pyright`, and `uv run pytest -v`.
- [ ] **Step 5: Commit changes**
  Commit as `test(agent): add autonomous agent end-to-end integration suite and demo workflow`.

---

### Task 9: Phase 3 Acceptance Verification & Documentation Update

**Files:**
- Modify: `docs/roadmap/PHASE_3_STATUS.md`
- Modify: `docs/IMPLEMENTATION_PLAN.md`
- Modify: `docs/PROJECT_STATUS.md`
- Modify: `docs/CHANGELOG.md`

- [ ] **Step 1: Update status trackers with test counts and verification evidence**
- [ ] **Step 2: Ensure working tree is clean**
- [ ] **Step 3: Commit documentation updates**
