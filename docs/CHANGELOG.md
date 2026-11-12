# Changelog

All notable changes to the ATLAS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.0] - 2026-11-12 — Phase 3 Model Provider Adapters & Planning Engine Release

### Added
- **Core Model & Tool Contracts (`packages/atlas-core`)**:
  - Pydantic v2 domain schemas (`ModelRequest`, `ModelResponse`, `ModelMessage`, `TextPart`, `ImagePart`, `ModelCapabilities`, `ToolDefinition`, `ToolCall`, `TokenUsage`, `ProviderHealth`, `ModelError`).
  - Zero third-party SDK dependencies in `atlas-core` (Constitution Rule 3 verified via isolated subprocess tests).
- **Universal Model Adapter Framework (`packages/atlas-models`)**:
  - `ModelAdapter` abstract base protocol with async `complete()`, `stream()`, `health_check()`, and `get_capabilities()`.
  - Concrete normalized adapters for:
    1. OpenAI (`OpenAIAdapter`)
    2. Anthropic Claude (`AnthropicAdapter`)
    3. Google Gemini (`GeminiAdapter`)
    4. Ollama (`OllamaAdapter`)
    5. OpenAI-Compatible local inference endpoints (`OpenAICompatibleAdapter`)
  - Normalized multimodal input, tool/function calling, and token usage accounting.
  - Safe credential masking (`mask_credential`) preventing API key leaks in logs and exceptions.
- **Resilient Model Router (`packages/atlas-models`)**:
  - `ModelRouter` with capability-based filtering (`vision`, `tools`, `min_context_window`).
  - Per-adapter `CircuitBreaker` with 3-state tracking (`CLOSED`, `OPEN`, `HALF_OPEN`).
  - Exponential backoff with jitter on 429 rate limit responses.
  - Per-task and global token usage and USD cost tracking via `CostTracker`.
- **Autonomous Planning & Agent Engine (`packages/atlas-agent`)**:
  - `StructuredPlanner` producing typed `ExecutionPlan` with `PlanStep` sequence, driver schema validation, and dynamic bounded replanning (`max_replans=3`).
  - `ContextManager` with sliding window pruning, token budgeting, and compact `DOMSummarizer` generating clean interactive element markup.
  - Prompt injection defense via strict `<untrusted_external_content>` XML demarcation.
  - `SafetyEngine` with action idempotency hashing (breaks infinite loops after 3 consecutive identical actions) and hard resource ceilings (`max_steps`, `max_tokens`, `max_cost_usd`, `timeout_seconds`).
  - `AutonomousAgentLoop` orchestrating the 11-step execution cycle: Observe $\to$ Build Context $\to$ Ask Model $\to$ Validate $\to$ Propose Action $\to$ Check Policy $\to$ Request Approval $\to$ Execute Driver $\to$ Verify Post-Condition $\to$ Record SQLite Events $\to$ Replan/Continue.
- **Integration Test Suite & Verification (`tests/integration`, `scripts/`)**:
  - `tests/integration/test_autonomous_agent_e2e.py` verifying multi-turn login workflow and Action Firewall denial recovery.
  - Standalone executable demonstration script `scripts/demo_autonomous_agent.py`.
  - Architectural ADRs: [ADR-0005](adr/0005-model-provider-adapter-architecture.md) and [ADR-0006](adr/0006-autonomous-planning-and-execution-loop.md).
  - Final acceptance report in `docs/roadmap/PHASE_3_ACCEPTANCE_REPORT.md`.

---

## [0.2.0] - 2026-11-12 — Phase 2 Browser Execution Runtime Release

### Added
- **Browser Execution Driver (`packages/atlas-browser`)**:
  - `PlaywrightBrowserDriver` implementing the core `ComputerDriver` protocol with Chromium automation.
  - Isolated browser context creation with per-session cookies, cache, viewport settings, and health check monitoring.
  - `BrowserActionExecutor` supporting `browser.navigate`, `browser.click`, `browser.type`, `browser.fill`, `browser.select`, `browser.scroll`, `browser.press_key`, `browser.wait`, `browser.upload`.
  - Resilient locator resolution supporting accessible roles (`page.get_by_role`), text matching, placeholder, labels, test IDs, CSS, XPath, and coordinate clicking.
  - `DownloadManager` intercepting download events, preventing directory traversal, computing SHA-256 checksums, and logging file sizes.
  - `NetworkMonitor` capturing HTTP request/response metrics, status codes, and console errors.
- **Multimodal Observation Engine (`packages/atlas-observation`)**:
  - `extract_dom_snapshot` and `extract_interactive_elements` for structured DOM evaluation.
  - `extract_accessibility_tree` using Chromium CDP `Accessibility.getFullAXTree` with fallback to semantic DOM ARIA walking.
  - `capture_screenshot` and `capture_observation` generating base64-encoded PNG screenshots and structured `Observation` domain models.
- **Deterministic Verification Engine (`packages/atlas-verification`)**:
  - `VerificationEngine` evaluating declarative post-conditions against live browser state with async polling.
  - Post-condition matchers: `element_visible`, `element_hidden`, `text_present`, `url_matches`, `file_downloaded`, `value_equals`.
- **Core Runtime Driver Contracts (`packages/atlas-core`)**:
  - `ComputerDriver` abstract protocol and `DriverHealth` model in `atlas_core.runtime.driver`.
  - Browser runtime exception hierarchy (`DriverError`, `NavigationTimeoutError`, `ElementNotFoundError`, `DetachedElementError`, `BrowserCrashError`, `ActionExecutionError`).
- **Developer CLI Extensions (`apps/cli`)**:
  - `atlas doctor` extended with Playwright Chromium driver availability check.
  - `atlas environment test browser` CLI diagnostic command verifying headless Chromium launch and connectivity.
- **Hermetic Synthetic Test Fixtures (`tests/fixtures`)**:
  - Local HTTP `SyntheticServer` serving deterministic test pages (`/`, `/login`, `/interactive`, `/upload`, `/download`).
  - End-to-end integration test (`test_browser_runtime_e2e.py`) validating the full ATLAS lifecycle without external network dependencies.

---

## [0.1.0] - 2026-11-12 — Phase 1 Foundation & Core Lifecycle Release

### Added
- **Monorepo Architecture & Governance**:
  - Root monorepo workspace configuration using `uv` (`pyproject.toml`) linking packages (`atlas-core`, `atlas-storage`, `atlas-policy`, `atlas-observability`) and applications (`apps/api`, `apps/cli`).
  - Code style and linting configuration in `ruff.toml` targeting Python 3.11+.
  - Comprehensive `.gitignore` filtering out bytecode, test caches, virtual environments, and SQLite databases.
  - Engineering Constitution (`AGENTS.md`) enforcing 8 mandatory rules for contributors and AI agents.
  - Documentation suite: `ARCHITECTURE.md`, `DECISIONS.md`, `IMPLEMENTATION_PLAN.md`, `PROJECT_STATUS.md`, `TEST_RESULTS.md`, `KNOWN_ISSUES.md`.
  - Foundational Architectural Decision Records (ADRs):
    - `0001-monorepo-and-runtime-ownership.md`
    - `0002-event-sourced-task-persistence.md`
    - `0003-action-firewall-policy-separation.md`

- **Core Domain & State Machine (`packages/atlas-core`)**:
  - Zero-dependency Pydantic v2 data contracts with schema versioning (`"1.0"`) covering `TaskRequest`, `Task`, `ComputerAction`, `ActionTarget`, `ActionResult`, `ExecutionEvent`, `Observation`, `Session`, `Checkpoint`, `Model`, `Policy`.
  - Explicit 14-state Task State Machine enforcing strict transition rules and raising `InvalidStateTransitionError` on illegal moves.
  - Execution event emission hooks and runtime protocol definitions.

- **Action Firewall & Policy Engine (`packages/atlas-policy`)**:
  - Action firewall evaluation pipeline with `ALLOW`, `REQUIRE_APPROVAL`, and `DENY` decision types.
  - Risk classification (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
  - Destructive command pattern filters blocking catastrophic shell commands (`rm -rf /`, `mkfs`, format, fork bombs, PowerShell recursive deletion).
  - Domain security policies with allowlists, blocklists, wildcard matching, and fail-closed denial on malformed or unparseable URLs.

- **Contextual Observability & Structured Logging (`packages/atlas-observability`)**:
  - RFC-compliant structured JSON logging formatter with contextual attributes (`task_id`, `session_id`, `step_id`).
  - Async context propagation using Python `contextvars` and scoped context managers.
  - High-performance regex and key-based credential masking for OpenAI, Anthropic, Google AI, AWS, Bearer tokens, passwords, and PEM private keys.

- **Event-Sourced Storage Engine (`packages/atlas-storage`)**:
  - SQLite storage engine with WAL journal mode (`PRAGMA journal_mode=WAL`), busy timeout (5000ms), and foreign key integrity.
  - Append-only `execution_events` table guaranteeing monotonic sequence numbering per task.
  - Materialized `tasks` view with optimistic concurrency control (`expected_state`).
  - Concurrency safety with multi-connection WAL readers and transactional rollback on failure.
  - Abstract PostgreSQL storage interface specification.

- **FastAPI Service (`apps/api`)**:
  - Production FastAPI application with modular routers and lifespan management.
  - Liveness endpoint (`/health`, `/healthz`), readiness probe (`/readyz` with SQLite connection check), and detailed status (`/api/v1/status`).
  - Graceful degradation returning HTTP 503 when backing storage is unavailable.

- **Developer CLI Suite (`apps/cli`)**:
  - Click-powered `atlas` CLI command suite.
  - `atlas doctor`: Environment verification (Python 3.11+, SQLite WAL support, OS environment).
  - `atlas init`: Automated workspace initialization and database schema provisioning.
  - `atlas task`: Task lifecycle management (`create`, `list`, `inspect` with sensitive data redaction).

- **CI Matrix & Verification Suite (`.github/workflows/ci.yml`)**:
  - Cross-platform GitHub Actions matrix running on Windows 11 and Ubuntu across Python 3.11 and Python 3.12.
  - Enforced quality gates: Ruff linting (`uv run ruff check .`), Ruff formatting check (`uv run ruff format --check .`), and Pytest test suite (`uv run pytest -v`).
  - 97 automated unit and integration tests passing with 100% pass rate.
  - Complete verification of all 14 Phase 1 acceptance criteria (14/14).
