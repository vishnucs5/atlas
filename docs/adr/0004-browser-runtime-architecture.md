# ADR 0004: Browser Runtime Architecture & Playwright Driver Separation

- **Status:** Accepted
- **Date:** 2026-11-12
- **Author:** ATLAS Core Architecture Team
- **Context:** Phase 2 introduces the Browser Execution Runtime for ATLAS.

---

## Context and Problem Statement

AI agents operating web browsers need to perform complex workflows (navigation, form filling, clicking, dynamic DOM observation, screenshots, file downloads). However, allowing AI models or agent frameworks direct, unrestricted access to browser automation APIs (such as raw Playwright handles or Chrome DevTools Protocol) creates significant security, observability, and recoverability liabilities:
1. **Security risk**: Webpages can embed prompt injections, deceptive forms, or attempt unauthorized local filesystem downloads/uploads.
2. **Context loss & non-determinism**: Raw DOM trees are massive, noisy, and non-deterministic.
3. **Execution bypass**: Directly executing Playwright scripts bypasses policy evaluation and audit logging.
4. **Lack of post-condition verification**: Reporting success based on a click method call without verifying expected DOM or state changes causes false positives.

## Decision

We establish an isolated browser runtime architecture centered around the following principles:

1. **Owner-Driver Separation**:
   - `atlas-core` defines the abstract `ComputerDriver` protocol (`connect`, `observe`, `execute`, `health_check`, `disconnect`).
   - `packages/atlas-browser` implements the driver using Playwright Chromium as an encapsulated low-level execution engine.
   - The AI model never interacts with or receives raw Playwright instances. It only proposes `ComputerAction` contracts and receives structured `Observation` contracts.

2. **Mandatory Action Firewall Gating**:
   - Every browser action (`browser.navigate`, `browser.click`, `browser.type`, `browser.download`, etc.) must pass through `ActionFirewall.evaluate()` before reaching `PlaywrightBrowserDriver`.
   - Domain allowlists, explicit blocklists, and fail-closed malformed URL policies are enforced at runtime.

3. **Deterministic Verification Engine (`packages/atlas-verification`)**:
   - Actions support declarative `ExpectedState` contracts (e.g. `element_visible`, `text_present`, `url_matches`, `file_downloaded`).
   - Action completion is strictly separated from goal verification: `ActionResult.success` reflects driver execution, while `VerificationEngine.verify()` determines deterministic post-condition satisfaction.

4. **Hermetic Session Isolation**:
   - Each task or execution session runs in its own isolated `BrowserContext` with independent cookies, cache, storage, and custom download directories.
   - Sessions are terminated and cleaned up deterministically upon task completion or cancellation.

5. **Observation Redaction & Security**:
   - Screenshots and DOM snapshots are sanitized to prevent secret leaks (e.g., masking password input fields and bearer tokens).
   - Website content is treated as untrusted data.

## Consequences

- **Positive**: Strict adherence to the ATLAS Engineering Constitution (Rule 1: Core owns orchestration; Rule 2: Action Firewall; Rule 3: Zero-dependency core; Rule 7: Verification invariant).
- **Positive**: Full observability through immutable `ExecutionEvent` streams for every observation, proposed action, policy check, driver execution, and verification check.
- **Negative**: Adds an abstraction layer over raw Playwright; requires explicit mapping of locator strategies (`accessible_role`, `text`, `css`, `xpath`, `coordinates`).
