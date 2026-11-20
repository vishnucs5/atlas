# ATLAS Zero-Cost Cloud Model Catalog Implementation Plan

> **Status:** First runtime slice implemented. Remaining work: credential file fallback and automated deterministic verification. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform ATLAS into an exclusively zero-cost cloud model platform by purging paid/local model options, discovering the full zero-price inventory from enabled provider catalogs, adding hybrid OS-keyring credential onboarding, and hardening ModelRouter with a paid-routing firewall.

**Architecture:** A version-controlled provider-source registry (`config/free_model_catalogue.json`) drives non-generation inventory discovery and maintains a timestamped model cache with exact origin pinning and review expiry. Every billable price field and account entitlement must pass the zero-cost gate. A `FreeModelCatalogue` validates separate eligibility, authentication, billing-entitlement, and runtime states. `CredentialManager` discovers credentials via Environment Variables > OS Keyring > consent-gated Restricted File fallback. `ModelRouter` enforces pre-flight free-only checks and explicit free-to-free failover while preserving the existing `ActionFirewall`. The CLI `/models` command provides full catalog listing, refresh, filters, onboarding, and non-generation connectivity probes.

OpenCode's free catalog is a reference for the catalog experience, but its official API docs restrict free-tier inference to OpenCode itself and return HTTP 403 to other clients. ATLAS must not route through that gateway. A model may be enabled only through an independently audited provider route ATLAS may use at zero cost.

**Tech Stack:** Python 3.11+, Pydantic v2, `httpx`, `rich`, `prompt_toolkit`, `keyring`, `pytest`.

**Spec:** [docs/superpowers/specs/2026-11-20-free-cloud-models-design.md](file:///c:/Users/pc/Documents/antigravity/happy-meitner/docs/superpowers/specs/2026-11-20-free-cloud-models-design.md)

## Global Constraints
- Strictly zero paid commercial APIs (`gpt-4o`, `claude-3-5-sonnet`) and zero local inference runners (`ollama`, `vLLM`, `llama.cpp`) in active routing.
- Precedence: Environment Variables > OS Keyring > Restricted Config File (`0600` on POSIX / restricted DACL on Windows). Never overwrite environment variables.
- Never expose credential values or fragments in logs, output, error messages, telemetry, prompts, or exported session files; render only a fixed `[configured]` marker.
- Exact model ID matching and approved HTTPS origin pinning; no simplistic URL string prefixes.
- Zero financial surprise: fail closed with `PaidRoutingBlockedError` whenever free eligibility cannot be verified.

---

### Task 1: Free Model Catalogue Schema & Manifest

**Files:**
- Create: `config/free_model_catalogue.json`
- Create: `packages/atlas-models/src/atlas_models/free_catalogue.py`
- Create: `packages/atlas-models/src/atlas_models/catalog_discovery.py`
- Test: `tests/unit/test_free_models_catalogue.py`

**Interfaces:**
- Produces: `FreeModelCatalogue`, `CatalogDiscovery`, `ModelEntry`, `ModelEligibilityStatus`, `ProviderAuthStatus`, `ProviderBillingStatus`, `ProviderRuntimeStatus`, `PaidRoutingBlockedError`.

- [ ] **Step 1: Write failing catalogue schema & manifest tests**
  Write tests in `tests/unit/test_free_models_catalogue.py` verifying:
  - Valid manifest parsing and schema validation.
  - Rejection of entries lacking required verification fields (official URLs, rate limits, expiry dates).
  - Rejection of paid model identifiers (`gpt-4`, `claude-3-5`).
  - Exact allowlist check for `openrouter/free`; exact `:free` suffix check for any separately admitted OpenRouter fixed model.
  - Dynamic inventory parsing excludes missing/nonzero prices, paid account requirements, stale source evidence, and unsupported routes.
  - Failed refreshes and expired source evidence never promote stale entries to eligible.
- [ ] **Step 2: Run tests to verify failure**
  Run: `uv run pytest tests/unit/test_free_models_catalogue.py -v` (Expected: ModuleNotFoundError).
- [x] **Step 3: Implement `config/free_model_catalogue.json` and `free_catalogue.py`**
  Implement Pydantic models with status separation, manifest loader, and validation methods.
- [ ] **Step 4: Run tests to verify pass**
  Run: `uv run pytest tests/unit/test_free_models_catalogue.py -v` (Expected: 100% pass).
- [ ] **Step 5: Commit changes**
  Commit as `feat(models): implement free model catalogue schema and verified manifest`.

---

### Task 2: Hybrid Credential Discovery & OS Keyring Storage

**Files:**
- Create: `packages/atlas-models/src/atlas_models/credentials.py`
- Modify: `packages/atlas-models/src/atlas_models/adapter.py`
- Test: `tests/unit/test_free_credentials.py`

**Interfaces:**
- Consumes: `FreeModelCatalogue`, `redact_credential`.
- Produces: `CredentialManager.get_credential(provider)`, `CredentialManager.set_credential(provider, key)`, `CredentialManager.delete_credential(provider)`.

- [ ] **Step 1: Write failing credential resolution and security tests**
  Write tests in `tests/unit/test_free_credentials.py` verifying:
  - Resolution precedence (Env Var > Keyring > File fallback).
  - Env var immutability (setting via config never overrides env var).
  - File fallback requires explicit consent, then permission restriction (`0600` on POSIX / owner-only DACL on Windows), and fails closed if permission verification fails.
  - Credential redaction without fragments, remove semantics, and no unsupported promise of Python string zeroization.
- [ ] **Step 2: Run tests to verify failure**
  Run: `uv run pytest tests/unit/test_free_credentials.py -v` (Expected: ModuleNotFoundError).
- [~] **Step 3: Implement credential lookup and storage**
  Environment-first, OS keyring lookup and hidden CLI keyring writes/removals are implemented. Consent-gated restricted-file fallback remains outstanding. Keep credential presence separate from successful provider validation.
- [ ] **Step 4: Run tests to verify pass**
  Run: `uv run pytest tests/unit/test_free_credentials.py -v` (Expected: 100% pass).
- [ ] **Step 5: Commit changes**
  Commit as `feat(models): implement hybrid credential discovery with OS keyring and restricted file fallback`.

---

### Task 3: Free Cloud Provider Adapters with HTTPS Origin Pinning

**Files:**
- Create: `packages/atlas-models/src/atlas_models/adapters/openrouter.py`
- Create: `packages/atlas-models/src/atlas_models/adapters/sambanova.py`
- Create: `packages/atlas-models/src/atlas_models/adapters/cloudflare.py`
- Modify: `packages/atlas-models/src/atlas_models/adapters/gemini.py`
- Modify: `packages/atlas-models/src/atlas_models/adapters/__init__.py`
- Test: `tests/unit/test_free_adapters.py`

**Interfaces:**
- Consumes: `OpenAICompatibleAdapter`, `GeminiAdapter`, `ModelCapabilities`, `ModelRequest`, `ModelResponse`.
- Produces: `OpenRouterFreeAdapter`, `SambaNovaAdapter`, `CloudflareWorkersAIAdapter`. Groq remains disabled until a specific currently supported model and its free-tier billing policy pass audit.

- [ ] **Step 1: Write failing adapter connectivity and origin pinning tests**
  Write tests in `tests/unit/test_free_adapters.py` verifying:
  - Proper base URL and HTTPS origin pinning per provider.
  - Rejection of base URLs pointing to unapproved domains or HTTP endpoints.
  - Proper request header formatting and absence of billing headers.
  - Non-generation provider metadata probes; Gemini key in header, OpenRouter `GET /api/v1/key`, and Cloudflare account ID plus least-privilege token.
- [ ] **Step 2: Run tests to verify failure**
  Run: `uv run pytest tests/unit/test_free_adapters.py -v` (Expected: ModuleNotFoundError).
- [~] **Step 3: Implement provider adapters**
  Implement adapters inheriting from `OpenAICompatibleAdapter` with fixed origin validation.
  OpenRouter direct free IDs are live-price checked before inference; Gemini and Cloudflare adapters are implemented. SambaNova and Groq remain blocked pending billing and entitlement audits.
- [ ] **Step 4: Run tests to verify pass**
  Run: `uv run pytest tests/unit/test_free_adapters.py -v` (Expected: 100% pass).
- [ ] **Step 5: Commit changes**
  Commit as `feat(models): implement free cloud adapters with HTTPS origin pinning`.

---

### Task 4: ModelRouter Hard Firewall & Transparent Free-to-Free Failover

**Files:**
- Modify: `packages/atlas-models/src/atlas_models/router.py`
- Modify: `packages/atlas-models/src/atlas_models/__init__.py`
- Test: `tests/unit/test_free_models_router.py`

**Interfaces:**
- Consumes: `FreeModelCatalogue`, `CredentialManager`, `PaidRoutingBlockedError`.
- Produces: `ModelRouter.complete(..., fallback=True)` with `assert_free_eligible()`.

- [ ] **Step 1: Write failing ModelRouter firewall and failover tests**
  Write tests in `tests/unit/test_free_models_router.py` verifying:
  - Direct execution with paid model IDs (`openai:gpt-4o`, `anthropic:claude-3-5-sonnet`, `ollama:llama3`) raises `PaidRoutingBlockedError`.
  - Invocations with unverified or expired models are blocked.
  - Primary rate limit (HTTP 429) triggers bounded backoff; any switch requires per-turn user consent or an explicit saved `auto_fallback` preference.
  - Ambiguous timeout after possible provider acceptance returns `OUTCOME_UNKNOWN`; no hidden retry or model switch.
  - All-free-exhaustion halts cleanly with zero cost and no fallback to paid APIs.
- [ ] **Step 2: Run tests to verify failure**
  Run: `uv run pytest tests/unit/test_free_models_router.py -v` (Expected: FAIL on firewall assertion).
- [x] **Step 3: Implement free-only firewall and failover logic in `router.py`**
  Add `assert_free_eligible()` pre-flight gate, remove legacy paid adapter registration, and integrate catalogue-driven candidate selection.
- [ ] **Step 4: Run tests to verify pass**
  Run: `uv run pytest tests/unit/test_free_models_router.py -v` (Expected: 100% pass).
- [ ] **Step 5: Commit changes**
  Commit as `feat(models): enforce free-only routing firewall and transparent free-to-free failover`.

---

### Task 5: Redesign CLI `/models` Governance & Onboarding Experience

**Files:**
- Modify: `apps/cli/src/atlas_cli/commands/models.py`
- Modify: `apps/cli/src/atlas_cli/conversation/composer.py`
- Test: `tests/unit/test_cli_free_models.py`

**Interfaces:**
- Consumes: `FreeModelCatalogue`, `CredentialManager`, `ModelRouter`.
- Produces: `run_models_list()`, `run_models_refresh()`, `run_models_use()`, `run_models_configure()`, `run_models_test()`, `run_models_remove()`.

- [ ] **Step 1: Write failing CLI `/models` command tests**
  Write tests in `tests/unit/test_cli_free_models.py` verifying:
  - `/models` lists the full discovered catalog and separates cost eligibility, auth, billing entitlement, and runtime statuses.
  - `/models refresh` updates configured inventories and reports additions, removals, price changes, expired offers, and source failures without promoting stale data.
  - `/models --filter coding` filters rows correctly.
  - `/models configure <provider>` prompts for API key securely with hidden input and displays official signup URL.
  - `/models test <provider>` performs non-billable connectivity check.
  - `/models remove <provider>` deletes credentials.
  - Headless/non-interactive mode never hangs on stdin; returns structured `NEEDS_KEY` setup instructions and a nonzero command result.
- [ ] **Step 2: Run tests to verify failure**
  Run: `uv run pytest tests/unit/test_cli_free_models.py -v` (Expected: FAIL).
- [x] **Step 3: Implement updated `models.py` CLI commands**
  Update CLI formatting with Rich table, badge rendering, hidden input handling, and status separation.
- [ ] **Step 4: Run tests to verify pass**
  Run: `uv run pytest tests/unit/test_cli_free_models.py -v` (Expected: 100% pass).
- [ ] **Step 5: Commit changes**
  Commit as `feat(cli): redesign /models with free cloud catalogue, status separation, and key onboarding`.

---

### Task 6: Full Monorepo Regression & Release Readiness

**Files:**
- Modify: `docs/PROJECT_STATUS.md`
- Test: All unit test suites (`tests/unit/`)

- [ ] **Step 1: Run full unit test suite**
  Run: `uv run pytest tests/unit/ -v` (Verify all tests pass).
- [x] **Step 2: Run linter and formatting checks**
  Run: `uv run ruff check .` and `uv run ruff format --check .` (0 errors).
- [ ] **Step 3: Run static type checking**
  Run: `uv run mypy packages/atlas-models/src apps/cli/src --ignore-missing-imports` (0 errors).
- [ ] **Step 4: Update `docs/PROJECT_STATUS.md`**
  Record Stage 7.7 Free Cloud Models Architecture & Verification.
- [ ] **Step 5: Prepare final Git report for user review**
  Present summary of work and await explicit user authorization.
