# ATLAS Phase 2: Browser Execution Runtime — Implementation Plan

- **Status:** APPROVED & ACTIVE
- **Target OS:** Windows 11 (primary) / Cross-platform (Linux & macOS)
- **Branch:** `feat/phase-2-browser-runtime`
- **Architectural Directive:** Own orchestration, action lifecycle, security firewall, and verification. Playwright serves solely as low-level browser automation driver.

---

## 1. Scope & Core Modules

Phase 2 introduces the complete Browser Execution Runtime for ATLAS across four focused modules:

1. **`packages/atlas-core` (Extensions)**:
   - Define `ComputerDriver` protocol in `atlas_core.runtime.driver`.
   - Add browser-specific error types (`DriverError`, `NavigationTimeoutError`, `ElementNotFoundError`, `DetachedElementError`, `BrowserCrashError`).
   - Add new event types (`ACTION_PROPOSED`, `ACTION_STARTED`, `ACTION_COMPLETED`, `ACTION_FAILED`, `VERIFICATION_COMPLETED`, `ACTION_ABORTED`).

2. **`packages/atlas-browser`**:
   - `PlaywrightBrowserDriver`: Lifecycle management (launch, isolated contexts, tabs, health checks, shutdown).
   - `BrowserActionExecutor`: Resilient execution of `browser.navigate`, `browser.click`, `browser.type`, `browser.fill`, `browser.select`, `browser.scroll`, `browser.press_key`, `browser.wait`.
   - `DownloadManager`: Interception of file downloads, verification of file path within designated download directory, SHA256 checksum, and size recording.
   - `UploadManager`: Secure validation and file upload to inputs.
   - `NetworkMonitor`: Interception of network requests, status codes, and console error logging.

3. **`packages/atlas-observation`**:
   - `DOMExtractor`: Extract structured DOM snapshots and visible interactive elements.
   - `AccessibilityExtractor`: Accessibility tree snapshots for semantic targeting.
   - `ScreenshotCapture`: Viewport and full-page PNG screenshots with file reference/base64 handling.

4. **`packages/atlas-verification`**:
   - `VerificationEngine`: Deterministic post-condition verification matching `ExpectedState` (`element_visible`, `element_hidden`, `text_present`, `url_matches`, `file_downloaded`, `value_equals`).

5. **`tests/fixtures/synthetic_site` & Integration Suites**:
   - Hermetic local HTTP test server serving deterministic test pages (no external network dependencies in CI).
   - End-to-end integration verifying: Task Submission $\to$ State Machine $\to$ Observation $\to$ Action Proposal $\to$ Action Firewall $\to$ Driver Execution $\to$ Verification $\to$ Event Store.

---

## 2. Phased Tasks & Acceptance Milestones

- [x] **Task 2.1**: Scaffolding, `ComputerDriver` Protocol & ADR-0004
- [x] **Task 2.2**: Observation Engine (`packages/atlas-observation`)
- [x] **Task 2.3**: Resilient Browser Driver & Action Execution (`packages/atlas-browser`)
- [x] **Task 2.4**: File Downloads, Uploads & Network Monitoring (`packages/atlas-browser`)
- [x] **Task 2.5**: Deterministic Post-Condition Verification Engine (`packages/atlas-verification`)
- [x] **Task 2.6**: Hermetic Synthetic Fixtures & End-to-End Integration Suite
- [x] **Task 2.7**: Documentation, Status Updates & Acceptance Verification
