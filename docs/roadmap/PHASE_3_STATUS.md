# Phase 3 Status Tracker: Model Provider Adapters & Planning Engine

**Target Branch:** `feat/phase-3-model-adapters-and-planning`  
**Current Status:** **READY FOR IMPLEMENTATION (Design & Architecture Complete, Gate Awaiting Approval)**  
**Start Date:** 2026-11-12  
**Target Completion:** 2026-11-13  
**Passing Tests:** 115 / 115 (Phase 1 & 2 baseline preserved)

---

## Acceptance Criteria Checklist (0/10 Complete)

- [ ] **AC-P3-01: Model Contracts in `atlas-core`**
  - Fully-typed Pydantic v2 schemas: `ModelRequest`, `ModelResponse`, `ModelMessage`, `ModelCapabilities`, `ToolDefinition`, `ToolCall`, `TokenUsage`, `ProviderHealth`, `ModelError`.
  - Zero third-party SDK dependencies in `atlas-core`.
  - Schema version `"1.0"` validation and serialization tests.

- [ ] **AC-P3-02: Universal Model Adapter Protocol & Base**
  - `ModelAdapter` abstract protocol in `packages/atlas-models`.
  - Async `complete()`, `stream()`, `health_check()`, `get_capabilities()`.
  - Sanitization of API keys and credentials before logging or errors.

- [ ] **AC-P3-03: Concrete Provider Adapters**
  - Independent normalized adapters for:
    1. OpenAI (`OpenAIAdapter`)
    2. Anthropic (`AnthropicAdapter`)
    3. Google Gemini (`GeminiAdapter`)
    4. Ollama (`OllamaAdapter`)
    5. OpenAI-Compatible local inference (`OpenAICompatibleAdapter`)
  - Tool calling, vision, and token usage normalization across all 5 adapters.

- [ ] **AC-P3-04: Resilient Model Router**
  - Capability-based routing (`vision`, `tools`, `context_window`).
  - Health check probing and dead provider exclusion.
  - Circuit breaker (closed, open, half-open states).
  - Exponential backoff with jitter on 429 rate limits.
  - Per-task token usage and USD cost tracking.

- [ ] **AC-P3-05: Structured Planner Engine (`atlas-agent`)**
  - Generates `ExecutionPlan` with typed `PlanStep` sequence and dependencies.
  - Plan step validation against driver schemas before dispatch.
  - Dynamic replanning on failure with bounded replans (`max_replans=3`).

- [ ] **AC-P3-06: 11-Step Autonomous Agent Loop**
  - Strict 11-step execution cycle: Observe $\to$ Build Context $\to$ Ask Model $\to$ Validate $\to$ Propose Action $\to$ Check Policy $\to$ Approval $\to$ Execute $\to$ Verify $\to$ Record Events $\to$ Replan/Continue.
  - Model never controls OS or browser directly.
  - Fails closed on Action Firewall `DENY`.

- [ ] **AC-P3-07: Context & Token Budget Management**
  - Context window sliding history with token budgeting.
  - DOM summarization (compacting to interactive nodes).
  - Vision screenshot optimization/downsampling.
  - Structured `TaskMemory` (scratchpad, variables, facts).

- [ ] **AC-P3-08: Safety & Loop Bounding**
  - Bounded iterations (`max_iterations=30`).
  - Action idempotency hashing and infinite loop detection.
  - Hard budgets (`max_tokens`, `max_cost_usd`, `timeout_seconds`).
  - Prompt injection defense via `<untrusted_external_content>` XML demarcation.

- [ ] **AC-P3-09: Hermetic Offline & Integration Test Suite**
  - Unit tests for all contracts, adapters, router, planner, and safety engines.
  - Mocked HTTP transports (zero paid API keys required for CI).
  - Full end-to-end autonomous agent workflow integration test with `SyntheticServer` and Playwright browser driver.

- [ ] **AC-P3-10: Architecture Documentation & ADR Records**
  - ADR-0005 (Model Provider Adapter Architecture) accepted and indexed.
  - ADR-0006 (Autonomous Planning and Execution Loop) accepted and indexed.
  - Architecture specs published in `docs/architecture/`.

---

## Phase 3 Task Progression Ledger

| Task | Component / Subsystem | Status | Assigned Step |
|---|---|:---:|:---:|
| **Task 3.1** | Phase Gate Verification & Design Documentation | **COMPLETED** | ADR-0005, ADR-0006, Specs |
| **Task 3.2** | Core Model Contracts (`packages/atlas-core`) | PENDING APPROVAL | Step 1 |
| **Task 3.3** | Package Scaffolding & Adapter Protocol (`packages/atlas-models`) | PENDING APPROVAL | Step 2 |
| **Task 3.4** | Concrete Provider Adapters (OpenAI, Anthropic, Gemini, Ollama, OpenAI-Comp) | PENDING APPROVAL | Step 3 |
| **Task 3.5** | Model Router, Circuit Breaker & Cost Tracker (`packages/atlas-models`) | PENDING APPROVAL | Step 4 |
| **Task 3.6** | Structured Planner & Dynamic Replanning (`packages/atlas-agent`) | PENDING APPROVAL | Step 5 |
| **Task 3.7** | Context Manager, DOM Summarizer & Injection Demarcation (`packages/atlas-agent`) | PENDING APPROVAL | Step 6 |
| **Task 3.8** | 11-Step Autonomous Agent Loop & Safety Engine (`packages/atlas-agent`) | PENDING APPROVAL | Step 7 |
| **Task 3.9** | End-to-End Integration Suite & Verification (`tests/integration`) | PENDING APPROVAL | Step 8 |
