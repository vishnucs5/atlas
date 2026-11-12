# Phase 3 Implementation Plan: Model Provider Adapters & Planning Engine

## Overview & Goal
Phase 3 builds the model interaction layer and autonomous planning harness for ATLAS.
The system enables provider-agnostic LLM reasoning across OpenAI, Anthropic, Google Gemini, Ollama, and OpenAI-compatible local models, while strictly enforcing ATLAS ownership over orchestration, tool execution, safety boundaries, and post-condition verification.

---

## Architecture Boundaries & Monorepo Packages

```
packages/
  ├── atlas-core/           # Zero-dependency domain contracts & protocols
  │   └── contracts/model.py  # ModelRequest, ModelResponse, ModelMessage, ToolDefinition, etc.
  ├── atlas-models/         # Provider adapters, ModelRouter, circuit breaker, cost tracker
  │   ├── adapter.py        # ModelAdapter abstract base class / protocol
  │   ├── adapters/         # OpenAI, Anthropic, Gemini, Ollama, OpenAI-Compatible
  │   └── router.py         # Capability filtering, fallback cascade, circuit breakers
  └── atlas-agent/          # Autonomous planning engine, agent loop, context, safety
      ├── planner.py        # StructuredPlanner, ExecutionPlan, PlanStep, replanning
      ├── loop.py           # 11-step AutonomousAgentLoop
      ├── context.py        # ContextManager, DOM summarization, injection demarcation
      └── safety.py         # SafetyEngine, loop detection, budget tracking
```

---

## Detailed Task Breakdown

### Task 3.1: Model Contracts (`packages/atlas-core`)
- Enhance `packages/atlas-core/src/atlas_core/contracts/model.py`:
  - `ModelMessage` (roles: `system`, `user`, `assistant`, `tool`; multimodal parts: `TextPart`, `ImagePart`).
  - `ToolDefinition` (JSON schema parameters) and `ToolCall` (parsed arguments).
  - `TokenUsage` (prompt, completion, total, cached tokens, USD cost).
  - `ProviderHealth` (status enum, latency, diagnostics).
  - `ModelError` (normalized error enum, retryable flag, secret-sanitized message).
  - Updated `ModelRequest` and `ModelResponse`.
- Update `packages/atlas-core/src/atlas_core/contracts/__init__.py`.
- Unit tests in `tests/unit/test_model_contracts.py`.

### Task 3.2: Scaffolding `packages/atlas-models` & Adapter Protocol
- Create package structure `packages/atlas-models/pyproject.toml` and `src/atlas_models/`.
- Add `packages/atlas-models` to root workspace in `pyproject.toml` and `[tool.pyright]`.
- Define `ModelAdapter` abstract base class with async methods:
  - `complete(request: ModelRequest) -> ModelResponse`
  - `stream(request: ModelRequest) -> AsyncIterator[ModelResponseChunk]`
  - `health_check() -> ProviderHealth`
  - `get_capabilities() -> ModelCapabilities`
  - `name() -> str`
- Implement common credential validation and header sanitization.

### Task 3.3: Concrete Provider Adapters
- Implement `packages/atlas-models/src/atlas_models/adapters/`:
  1. `openai.py`: `OpenAIAdapter` using `httpx` targeting OpenAI Chat Completions API.
  2. `anthropic.py`: `AnthropicAdapter` using `httpx` targeting Claude Messages API.
  3. `gemini.py`: `GeminiAdapter` using `httpx` targeting Google Gemini REST API.
  4. `ollama.py`: `OllamaAdapter` targeting local `/api/chat`.
  5. `openai_compatible.py`: `OpenAICompatibleAdapter` with configurable `base_url`.
- Implement normalization for tool calling schemas and vision inputs across each adapter.
- Unit tests in `tests/unit/test_model_adapters.py` with mock HTTP transports (`httpx.MockTransport`).

### Task 3.4: Model Router, Circuit Breaker & Cost Accounting
- Implement `packages/atlas-models/src/atlas_models/router.py`:
  - Capability-based filtering (matching request requirements against adapter capabilities).
  - Health check probing and dead adapter skipping.
  - Fallback cascade (Primary $\to$ Secondary $\to$ Local).
  - Circuit breaker (CLOSED, OPEN, HALF-OPEN states with configurable thresholds).
  - Exponential backoff with jitter on 429 rate limits.
  - Aggregated token usage and cost accounting.
- Unit tests in `tests/unit/test_model_router.py`.

### Task 3.5: Structured Planner Engine (`packages/atlas-agent`)
- Create package structure `packages/atlas-agent/pyproject.toml` and `src/atlas_agent/`.
- Add `packages/atlas-agent` to root workspace in `pyproject.toml` and `[tool.pyright]`.
- Implement `packages/atlas-agent/src/atlas_agent/planner.py`:
  - Domain models: `PlanStep`, `ExecutionPlan`, `PlanBudget`, `StepStatus`, `PlanStatus`.
  - `StructuredPlanner`: generates plan from task goal and initial observation.
  - Plan step validation against registered tool schemas.
  - Dynamic replanning on step failure with bounded attempts (`max_replans=3`).
- Unit tests in `tests/unit/test_planner.py`.

### Task 3.6: Context & Memory Management
- Implement `packages/atlas-agent/src/atlas_agent/context.py`:
  - `ContextManager`: sliding conversation history window with token budget pruning.
  - `DOMSummarizer`: compresses verbose DOM trees into clean interactive node hierarchies.
  - `ScreenshotOptimizer`: downsampling and compression for vision models.
  - `TaskMemory`: structured scratchpad, variable store, and persistent observations.
  - Prompt Injection Demarcation: encapsulates external untrusted content in `<untrusted_external_content>` tags.
- Unit tests in `tests/unit/test_context_manager.py`.

### Task 3.7: 11-Step Autonomous Agent Loop & Safety Engine
- Implement `packages/atlas-agent/src/atlas_agent/safety.py`:
  - Action idempotency hashing (detects repeating action loops and halts).
  - Hard budgets: `max_iterations`, `max_tokens`, `max_cost_usd`, `timeout_seconds`.
- Implement `packages/atlas-agent/src/atlas_agent/loop.py`:
  - `AutonomousAgentLoop`: executes the 11-step cycle (Observe $\to$ Build Context $\to$ Ask Model $\to$ Validate $\to$ Propose Action $\to$ Check Policy $\to$ Request Approval $\to$ Execute via Driver $\to$ Verify $\to$ Record Events $\to$ Replan/Continue).
  - Coordinates `ModelRouter`, `ActionFirewall`, `ComputerDriver`, `VerificationEngine`, and `EventStore`.
  - Ensures the model never controls the environment directly.
- Unit tests in `tests/unit/test_agent_loop.py` and `tests/unit/test_agent_safety.py`.

### Task 3.8: End-to-End Integration Suite & Verification
- Implement `tests/integration/test_autonomous_agent_e2e.py`:
  - End-to-end integration test with mock LLM adapter, `AutonomousAgentLoop`, `PlaywrightBrowserDriver`, and `SyntheticServer`.
  - Executes full multi-step workflow: Form navigation, typing, submission, file download, and deterministic verification.
  - Validates Action Firewall gating (rejection on unauthorized actions) and recovery loops.
- Verify full test suite, Ruff linting, formatting, and Pyright typing.

---

## Acceptance Verification Criteria
1. Monorepo builds cleanly with `atlas-models` and `atlas-agent` packages.
2. Zero external vendor SDK imports in `packages/atlas-core`.
3. All 5 provider adapters normalize requests, responses, tools, vision, and errors.
4. Model Router correctly filters by capability, executes fallbacks, and tracks costs.
5. Autonomous Agent Loop strictly follows the 11-step cycle and passes all actions through the Action Firewall.
6. All tests run hermetically offline with zero required paid API keys.
7. 100% of tests pass across unit and integration suites.
