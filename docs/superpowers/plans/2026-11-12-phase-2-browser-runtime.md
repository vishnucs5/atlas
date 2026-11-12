# Phase 2: Browser Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build ATLAS Phase 2 (Browser Runtime & Verification Engine): Implement Playwright-based browser session management, DOM & accessibility observation extraction, screenshot capture, semantic & coordinate action execution (click, type, scroll, navigate), file download monitoring, and deterministic post-condition verification.

**Architecture:** `packages/atlas-browser` implements the `ComputerDriver` protocol using Playwright Chromium behind an isolated context boundary. `packages/atlas-observation` extracts structured DOM snapshots and accessibility trees. `packages/atlas-verification` confirms expected state changes before declaring action success. Every action strictly passes through the `atlas-policy` Action Firewall before reaching the browser driver.

**Tech Stack:** Python 3.11+, Playwright, Pillow, Pydantic v2, Pytest, Pytest-asyncio, uv.

**Spec:** [docs/superpowers/specs/2026-11-12-phase-1-foundation-design.md](file:///c:/Users/pc/Documents/antigravity/happy-meitner/docs/superpowers/specs/2026-11-12-phase-1-foundation-design.md)

## Global Constraints

- `atlas-core` must remain zero-dependency; driver protocols live in `atlas-core`, but Playwright is isolated to `packages/atlas-browser`.
- Every browser action MUST pass through `ActionFirewall.evaluate()` before execution.
- Every completed action must be verified against its `ExpectedState` via `VerificationEngine`.
- Actions must emit structured `ExecutionEvent` records (e.g. `ACTION_PROPOSED`, `POLICY_EVALUATED`, `ACTION_STARTED`, `ACTION_COMPLETED`, `VERIFICATION_COMPLETED`).
- Local Playwright executions must run headless by default with configurable `--headed` debug mode.
- Sensitive values (passwords, tokens) typed into fields must be masked in action logs and screenshots.

---

### Task 1: Computer Driver Protocol & Browser Package Scaffolding

**Files:**
- Create: `packages/atlas-core/src/atlas_core/runtime/driver.py`
- Modify: `packages/atlas-core/src/atlas_core/runtime/__init__.py`
- Create: `packages/atlas-browser/pyproject.toml`
- Create: `packages/atlas-browser/src/atlas_browser/__init__.py`
- Create: `packages/atlas-browser/src/atlas_browser/driver.py`
- Test: `tests/unit/test_browser_driver_lifecycle.py`

**Interfaces:**
- Produces: `ComputerDriver(Protocol)`, `PlaywrightBrowserDriver` managing browser and context lifecycles.

- [ ] **Step 1: Write failing test for ComputerDriver protocol and PlaywrightBrowserDriver initialization**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement ComputerDriver protocol in atlas-core and PlaywrightBrowserDriver in atlas-browser**
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit scaffolding**

---

### Task 2: Observation Engine (DOM, Accessibility Tree & Screenshots)

**Files:**
- Create: `packages/atlas-observation/pyproject.toml`
- Create: `packages/atlas-observation/src/atlas_observation/__init__.py`
- Create: `packages/atlas-observation/src/atlas_observation/dom.py`
- Create: `packages/atlas-observation/src/atlas_observation/accessibility.py`
- Create: `packages/atlas-observation/src/atlas_observation/capture.py`
- Test: `tests/unit/test_observation_engine.py`

**Interfaces:**
- Consumes: Playwright `Page`
- Produces: `Observation` containing serialized DOM snapshot, accessibility tree nodes, and viewport/full-page screenshot references.

- [ ] **Step 1: Write failing test for DOM, accessibility tree, and screenshot capture**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement observation extractors and screenshot compressor**
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit observation engine**

---

### Task 3: Resilient Browser Action Execution

**Files:**
- Create: `packages/atlas-browser/src/atlas_browser/actions.py`
- Create: `packages/atlas-browser/src/atlas_browser/locators.py`
- Test: `tests/unit/test_browser_actions.py`

**Interfaces:**
- Consumes: `ComputerAction`, `ActionTarget`
- Produces: `BrowserActionExecutor` executing `browser.navigate`, `browser.click` (by role, text, selector, or coordinates), `browser.type`, `browser.press_key`, `browser.scroll` with auto-waiting and actionability verification.

- [ ] **Step 1: Write failing test for resilient locators and semantic clicking/typing**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement BrowserActionExecutor and locator strategies**
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit browser action executor**

---

### Task 4: Download Monitoring & Network Error Interception

**Files:**
- Create: `packages/atlas-browser/src/atlas_browser/downloads.py`
- Create: `packages/atlas-browser/src/atlas_browser/network.py`
- Test: `tests/unit/test_browser_downloads_and_network.py`

**Interfaces:**
- Produces: `DownloadManager` tracking downloaded file paths, checksums, and size; `NetworkMonitor` capturing HTTP status codes and failed requests.

- [ ] **Step 1: Write failing test for file download capture and HTTP error tracking**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement download interceptor and network listener**
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit download and network monitoring**

---

### Task 5: Deterministic Action Verification Engine

**Files:**
- Create: `packages/atlas-verification/pyproject.toml`
- Create: `packages/atlas-verification/src/atlas_verification/__init__.py`
- Create: `packages/atlas-verification/src/atlas_verification/engine.py`
- Create: `packages/atlas-verification/src/atlas_verification/matchers.py`
- Test: `tests/unit/test_verification_engine.py`

**Interfaces:**
- Consumes: `ExpectedState`, `Observation`, `ActionResult`
- Produces: `VerificationEngine`, evaluating:
  - `element_visible`: target selector/role appears
  - `text_present`: expected text exists in DOM/page
  - `url_matches`: URL equals or matches regex
  - `file_downloaded`: file exists on disk and has non-zero size
  - Returns `VerificationResult(verified=True/False, evidence=...)`.

- [ ] **Step 1: Write failing test for verification matchers and engine**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement VerificationEngine and condition matchers**
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit verification engine**

---

### Task 6: End-to-End Synthetic Browser Integration Suite

**Files:**
- Create: `tests/fixtures/synthetic_site/` (static HTML pages with buttons, inputs, downloads, and popups)
- Create: `tests/integration/test_browser_runtime_e2e.py`

**Interfaces:**
- Executes complete lifecycle:
  1. Task submitted $\to$ `TaskStateMachine` sets `RUNNING`
  2. Browser allocated $\to$ Observation captured
  3. Action proposed $\to$ `ActionFirewall` validates
  4. `PlaywrightBrowserDriver` executes
  5. `VerificationEngine` verifies expected outcome
  6. Transactional event sourcing records all steps.

- [ ] **Step 1: Create synthetic test fixture pages**
- [ ] **Step 2: Write end-to-end integration test exercising full cycle**
- [ ] **Step 3: Run test suite to verify full integration pass**
- [ ] **Step 4: Commit integration test suite**

---

### Task 7: CLI Browser Diagnostics & Phase 2 Documentation

**Files:**
- Modify: `apps/cli/src/atlas_cli/commands/doctor.py` (add Playwright browser readiness check)
- Create: `apps/cli/src/atlas_cli/commands/browser.py`
- Modify: `docs/PROJECT_STATUS.md`
- Modify: `docs/IMPLEMENTATION_PLAN.md`

- [ ] **Step 1: Add browser verification command to CLI**
- [ ] **Step 2: Run CLI tests**
- [ ] **Step 3: Update PROJECT_STATUS and IMPLEMENTATION_PLAN**
- [ ] **Step 4: Commit CLI updates and documentation**
