# ATLAS Zero-Cost Cloud Model Catalog — Architecture Specification

- **Document ID:** SPEC-2026-11-20-FREE-CLOUD-MODELS
- **Feature Branch:** `feat/atlas-universal-free-model-ecosystem`
- **Status:** IMPLEMENTATION IN PROGRESS (Sections 1–4 specified; first runtime slice implemented)
- **Author:** ATLAS Architecture Team
- **Date:** 2026-11-20

---

## 1. Revised Section 1: Architecture, Core Invariants & Audited Free-Model Catalogue

### 1.1 Core Tenets & Scope
1. **Free-Cloud-Only Invariant**: ATLAS executes completions **exclusively** against verified zero-cost cloud model routes.
2. **Broad, Current Catalog**: `/models` should discover and present every model reported as zero-cost by each enabled, audited provider catalog, rather than relying on a hand-picked short list. Discovery is dynamic and records provider, exact model ID, route, price evidence, quotas, availability period, capabilities, region restrictions, privacy terms, and account entitlement. A model with incomplete or stale evidence is visible as `UNDER_REVIEW` but cannot run. There is no single authoritative catalog of every model on the internet, so coverage is defined by the enabled provider sources listed in the registry and shown to the user.
3. **OpenCode Compatibility Boundary**: OpenCode is the reference for a searchable, changing free-model catalog. Its official docs state that OpenCode free-tier inference is available only from inside OpenCode and returns HTTP 403 to other clients. Therefore OpenCode-only gateway models are not executable by ATLAS. ATLAS may list them as external offers for discovery only; it may mark them usable only if an independently audited direct provider/API route is available to ATLAS at zero cost. See `https://opencode.ai/docs/console/api/models` and `https://opencode.ai/docs/console/api/inference/`.
4. **Zero-Price Qualification**: A listing is eligible only when every applicable input, output, cached-token, modality, and auxiliary-service price is documented as zero for the selected route and its account entitlement is `VERIFIED_FREE` or explicitly `ATTESTED_FREE`. Limited-time offers remain eligible only until their published or reviewed expiry; unknown pricing and promotional conditions fail closed.
5. **Exclusion of Paid and Local Runtimes**:
   - **Purged from Model Catalogue:** Commercial paid APIs (OpenAI `gpt-4o`/`gpt-4o-mini`, Anthropic `claude-3-5-sonnet`/`claude-3-haiku`, ATLAS Pro models).
   - **Purged from Runtime:** Local inference runners (Ollama, llama.cpp, vLLM local deployment, LM Studio), local hardware profiling, and GGUF downloads.
   - **Removed Provider Offerings:** 
     - **Groq:** `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` removed from the active catalogue due to official lifecycle deprecation/shutdown. Groq provider is set to `UNDER_REVIEW`.
     - **Mistral AI:** Removed entirely from eligible API providers. Official documentation confirms that Mistral's "Free Mode" is restricted to web consumer chat and does not grant developer API access. La Plateforme developer API usage requires billing activation and pay-as-you-go credits.
     - **SambaNova Cloud:** Retained in manifest but classified as `UNDER_REVIEW` until exact production model IDs, quota caps, and billing behavior are officially audited.
6. **Preferred Default Model**: **`openrouter/free`** is the initial preferred default, only when its free-tier key entitlement is verified. The user may select any other eligible zero-cost model.
7. **Zero-Dependency Architecture Ownership**: Reuses ATLAS's existing `ModelRouter`, provider adapters, and `ActionFirewall`. No duplicate routing engines, separate credential managers, or parallel policy checks.

#### Catalog Discovery and Refresh
- The catalogue has a provider-source registry. Each enabled source defines a public or authenticated non-generation inventory endpoint, allowed HTTPS origin, pagination rules, exact pricing fields, auth requirements, source review interval, and adapter protocol.
- `/models refresh` fetches provider inventories without inference, normalizes model records, and stores a timestamped cache. `/models` shows all discovered entries grouped by provider and clearly separates eligible free models, under-review models, and ineligible paid or unavailable models.
- For each candidate, price must be zero across every billable request dimension. The scanner rejects missing prices, unknown costs, provider-paid account requirements, paid-only models, mismatched regions, unknown endpoint/protocol support, and any chargeable fallback behavior.
- Dynamic source output is evidence for discovery, not automatic proof of eligibility. Eligibility additionally requires current provider terms, account entitlement, route support, privacy disclosure, quota, and review expiry. If the source cannot expose those facts non-billably, the user must explicitly attest to provider account conditions or the entry remains blocked.
- Limited-time free offers carry `availability_class: limited_promotion`, a `known_free_until` date when published, and a short review expiry when no end date is published. They disappear from eligible results immediately on price changes, removal, or expiry.
- The provider-source registry is extensible. Adding a new provider is a configuration and adapter task, not a hard-coded limit of three providers. Current verified sources include OpenRouter, Google AI Studio, and Cloudflare Workers AI; other providers are added only after the same zero-cost and account-entitlement audit.

---

### 1.2 Threat Model & Boundary of Control

#### What ATLAS Controls (Enforced Technical Guarantees)
- **Pre-flight Origin & Model ID Whitelist**: Every request is intercepted before network transmission. Only requests matching approved HTTPS origins and exact verified model IDs are allowed to proceed.
- **Strict HTTPS Origin Pinning**: Rejects any HTTP endpoints, undocumented redirect chains, or non-whitelisted domains.
- **Zero Billing Header Injection**: Requests never include billing tokens, enterprise contract IDs, or credit card authorizations.
- **Auxiliary Feature Quarantine**: Separates token inference from auxiliary services. Any request attempting to invoke billable grounding (e.g. Google Maps grounding above free tier, Google Search grounding overages) or context caching (not available on free tiers) is blocked. A token cost of `$0.00` is **never** treated as an assumption that auxiliary services are free.
- **Fail-Closed Policy**: If an endpoint cannot prove free eligibility, review evidence has expired, billing entitlement is `UNKNOWN`/`BILLABLE`, or required user attestation is absent, ATLAS fails closed with `PaidRoutingBlockedError`. `ATTESTED_FREE` records the user's confirmation when a provider has no entitlement probe; it is not a technical guarantee against upstream billing changes, which are disclosed before use.

#### What ATLAS Does Not Control (Explicit Disclosures)
- **Upstream Billing Policies**: Upstream cloud providers may alter free allowances, change pricing tiers, or impose server-side billing rules.
- **Account-Level Entitlements**: If a user supplies an API key tied to a paid organization or credit card on file, the upstream provider may automatically bill overages. ATLAS warns the user during onboarding to use dedicated, card-free API accounts.

---

### 1.3 Independent Provider Status Dimensions

Model operational state is divided into independent, non-conflicting dimensions. Provider billing entitlement is distinct from authentication: a valid key does not prove that the account is on a no-charge tier.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                         Provider State Dimensions                        │
├──────────────────┬──────────────────┬──────────────────┬─────────────────┤
│ Eligibility      │ Authentication   │ Billing Entitle. │ Runtime         │
├──────────────────┼──────────────────┼──────────────────┼─────────────────┤
│ ● FREE_VERIFIED  │ ● CONFIGURED     │ ● VERIFIED_FREE  │ ● HEALTHY      │
│ ○ UNDER_REVIEW   │ ◐ PRESENT_UNVER. │ ◐ ATTESTED_FREE  │ ○ RATE_LIMITED │
│ ✕ INELIGIBLE     │ ○ NEEDS_KEY      │ ○ UNKNOWN        │ ✕ UNAVAILABLE  │
│                  │ ✕ INVALID_KEY    │ ✕ BILLABLE       │                │
│                  │ ✕ FORBIDDEN      │                  │                │
└───────────────────────┴───────────────────────┴────────────────────────┘
```

1. **Eligibility Status (`ModelEligibilityStatus`)**:
   - `FREE_VERIFIED`: Provider/model free policy is documented and current; account entitlement is `VERIFIED_FREE` or accepted `ATTESTED_FREE`; active within review expiry.
   - `UNDER_REVIEW`: Upstream changes reported, model under evaluation, or review expiry passed. Execution blocked.
   - `INELIGIBLE`: Deprecated, requires payment method, or failed free-tier criteria. Permanently blocked.
2. **Authentication Status (`ProviderAuthStatus`)**:
   - `PRESENT_UNVERIFIED`: Credential discovered but not yet checked upstream.
   - `CONFIGURED`: Credential accepted by a provider authentication probe.
   - `NEEDS_KEY`: Required free API key is missing.
   - `INVALID_KEY`: Upstream returned a credential-specific authentication failure (normally HTTP 401).
   - `FORBIDDEN`: Credential recognized but lacks permission, account entitlement, or method access (often HTTP 403).
3. **Billing Entitlement (`ProviderBillingStatus`)**:
   - `VERIFIED_FREE`: A non-billable control-plane probe confirms the account uses a no-charge tier and cannot incur inference overages.
   - `ATTESTED_FREE`: The provider offers no non-billable entitlement probe; the user explicitly confirms the account is on the documented free tier after seeing the residual billing limitation. Record confirmation time and require reconfirmation after review expiry or account change.
   - `UNKNOWN`: Entitlement cannot be checked or attested. Execution is blocked.
   - `BILLABLE`: Paid or overage-billable account state. Execution is blocked.
4. **Runtime Status (`ProviderRuntimeStatus`)**:
   - `HEALTHY`: Operational, latency within bounds, circuit breaker `CLOSED`.
   - `RATE_LIMITED`: Free tier RPM/TPM/RPD cap reached (HTTP 429), backoff active.
   - `DEGRADED`: High latency (>3000ms) or intermittent errors, circuit breaker `HALF_OPEN`.
   - `UNAVAILABLE`: Endpoint unreachable or returning 5xx, circuit breaker `OPEN`.

---

### 1.4 Detailed Free-Model Catalogue Manifest Schema

The version-controlled provider-source registry is maintained at `config/free_model_catalogue.json`. Its model entries are a cache of the most recently discovered candidates, not a permanently hand-curated exhaustive list. `/models refresh` rebuilds this cache from each enabled source:

```json
{
  "$schema": "https://atlas.dev/schemas/free-model-catalogue-v1.json",
  "version": "1.1.0",
  "last_audit_date": "2026-11-20",
  "default_model": "openrouter/free",
  "providers": {
    "openrouter": {
      "display_name": "OpenRouter Free",
      "signup_url": "https://openrouter.ai/keys",
      "env_var": "OPENROUTER_API_KEY",
      "approved_origins": ["https://openrouter.ai"],
      "approved_api_bases": ["https://openrouter.ai/api/v1"],
      "account_billing_policy": "free_account_required",
      "inventory_source": {
        "url": "https://openrouter.ai/api/v1/models",
        "method": "GET",
        "auth": "optional OPENROUTER_API_KEY",
        "refresh_interval_minutes": 60,
        "eligibility_filter": "Exact model ID openrouter/free or all billable pricing fields are zero and provider marks model free"
      },
      "models": [
        {
          "id": "openrouter/free",
          "name": "OpenRouter Free Meta-Router",
          "classification": "dynamic_meta_router",
          "availability_class": "community_free",
          "context_window": "dynamic",
          "max_output_tokens": "dynamic",
          "capabilities": "dynamic",
          "capability_evidence": "The meta-router chooses an available free model based on request parameters; supported capabilities, context, and output limits vary by selected upstream model.",
          "account_level_quota": "Free variants are generally limited to 20 RPM and 50 RPD without a credit purchase; limits and upstream model availability may vary. Purchasing credits can raise the daily limit and is outside ATLAS's free-only account guidance.",
          "billing_and_overage_policy": "Only the exact openrouter/free meta-router ID is allowed. The non-generation key probe must confirm a free-tier key; if account tier cannot be determined, fail closed. ATLAS never adds paid model IDs or paid fallbacks. Stop on capacity or entitlement responses; do not retry with any paid route.",
          "privacy_disclosure": "Routes dynamically to available free community endpoints; subject to individual upstream provider data retention and operational logging policies.",
          "official_verification_sources": [
            "https://openrouter.ai/collections/free-models/",
            "https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key"
          ],
          "verification_date": "2026-11-20",
          "review_expiry": "2026-12-20",
          "eligibility_status": "FREE_VERIFIED",
          "is_default": true
        }
      ]
    },
    "google": {
      "display_name": "Google AI Studio",
      "signup_url": "https://aistudio.google.com/app/apikey",
      "env_var": "GEMINI_API_KEY",
      "approved_origins": ["https://generativelanguage.googleapis.com"],
      "approved_api_bases": ["https://generativelanguage.googleapis.com/v1beta"],
      "account_billing_policy": "free_tier_attestation_required",
      "inventory_source": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models",
        "method": "GET",
        "auth": "GEMINI_API_KEY via x-goog-api-key header",
        "refresh_interval_minutes": 1440,
        "eligibility_filter": "Provider inventory presence plus zero-cost tier policy and eligible account entitlement"
      },
      "models": [
        {
          "id": "gemini-2.5-flash",
          "name": "Gemini 2.5 Flash",
          "classification": "fixed_model",
          "availability_class": "provider_free_tier",
          "context_window": 1000000,
          "max_output_tokens": 8192,
          "capabilities": ["coding", "reasoning", "general", "vision", "tools"],
          "capability_evidence": "Hybrid reasoning model supporting 1M tokens, multimodal inputs, and function calling.",
          "account_level_quota": "Variable by project, model, and tier. Read documented response quota headers when present and treat AI Studio limits as authoritative; do not assume a universal quota or infer that absent headers mean unlimited quota.",
          "billing_and_overage_policy": "Model inference input and output are free of charge on the Standard Free Tier. The non-generation model metadata probe does not prove the project's billing tier; require explicit free-tier attestation and block if missing. Auxiliary services beyond the documented free Google Maps/Search grounding allowance are separately metered and blocked by ATLAS.",
          "privacy_disclosure": "Used to improve Google products: Yes. Prompts, responses, and annotations on the free tier may be reviewed by human reviewers and used to train Google models.",
          "official_verification_sources": [
            "https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash",
            "https://aistudio.google.com/rate-limit"
          ],
          "verification_date": "2026-11-20",
          "review_expiry": "2026-12-20",
          "eligibility_status": "FREE_VERIFIED",
          "is_default": false
        },
        {
          "id": "gemini-2.5-flash-lite",
          "name": "Gemini 2.5 Flash-Lite",
          "classification": "fixed_model",
          "availability_class": "provider_free_tier",
          "context_window": 1000000,
          "max_output_tokens": 8192,
          "capabilities": ["coding", "general", "vision", "tools"],
          "capability_evidence": "High-throughput cost-effective model with native multimodal and tool capabilities.",
          "account_level_quota": "Variable by project, model, and tier. Read documented response quota headers when present and treat AI Studio limits as authoritative; do not assume a universal quota or infer that absent headers mean unlimited quota.",
          "billing_and_overage_policy": "Model inference is free of charge on the Standard Free Tier. Context caching is disabled. Auxiliary search grounding over 500 RPD is blocked.",
          "privacy_disclosure": "Used to improve Google products: Yes. Data may be used for model training.",
          "official_verification_sources": [
            "https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash-lite"
          ],
          "verification_date": "2026-11-20",
          "review_expiry": "2026-12-20",
          "eligibility_status": "FREE_VERIFIED",
          "is_default": false
        }
      ]
    },
    "cloudflare": {
      "display_name": "Cloudflare Workers AI",
      "signup_url": "https://dash.cloudflare.com/profile/api-tokens",
      "env_var": "CLOUDFLARE_API_TOKEN",
      "required_account_config": ["CLOUDFLARE_ACCOUNT_ID"],
      "approved_origins": ["https://api.cloudflare.com"],
      "approved_api_bases": ["https://api.cloudflare.com/client/v4"],
      "account_billing_policy": "workers_free_plan_attestation_required",
      "inventory_source": {
        "url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/models/search",
        "method": "GET",
        "auth": "CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID",
        "refresh_interval_minutes": 1440,
        "eligibility_filter": "Model availability plus Workers Free plan entitlement and zero-cost allocation policy"
      },
      "models": [
        {
          "id": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
          "name": "Cloudflare Llama 3.3 70B",
          "classification": "fixed_model",
          "availability_class": "provider_free_tier",
          "context_window": 24000,
          "max_output_tokens": "dynamic",
          "capabilities": ["coding", "general", "tools"],
          "capability_evidence": "Meta Llama 3.3 instruction tuned model hosted on Cloudflare global edge network.",
          "account_level_quota": "10,000 Neurons per day allocated across all Workers AI operations, resetting daily at 00:00 UTC.",
          "billing_and_overage_policy": "Strict hard cap on Workers Free plan (returns HTTP 429/error on exhaustion with zero billing). Workers Paid plan bills overages at $0.011/1k Neurons; ATLAS requires confirmation of Workers Free plan or fails closed.",
          "privacy_disclosure": "Cloudflare model listing marks this exact model as zero data retention. Do not generalize that model-specific claim to every Workers AI model or account feature.",
          "official_verification_sources": [
            "https://developers.cloudflare.com/workers-ai/platform/pricing/",
            "https://developers.cloudflare.com/workers-ai/models/llama-3.3-70b-instruct-fp8-fast/"
          ],
          "verification_date": "2026-11-20",
          "review_expiry": "2026-12-20",
          "eligibility_status": "FREE_VERIFIED",
          "is_default": false
        }
      ]
    },
    "sambanova": {
      "display_name": "SambaNova Cloud",
      "signup_url": "https://cloud.sambanova.ai/apis",
      "env_var": "SAMBANOVA_API_KEY",
      "approved_origins": ["https://api.sambanova.ai"],
      "approved_api_bases": ["https://api.sambanova.ai/v1"],
      "account_billing_policy": "unverified_under_review",
      "models": [
        {
          "id": "Meta-Llama-3.3-70B-Instruct",
          "name": "SambaNova Llama 3.3 70B",
          "classification": "fixed_model",
          "context_window": 128000,
          "max_output_tokens": 4096,
          "capabilities": ["coding", "reasoning", "general", "tools"],
          "capability_evidence": "High-speed inference on Reconfigurable Dataflow Units (RDUs).",
          "account_level_quota": "Unpublished/variable rate limits on strict card-free tier.",
          "billing_and_overage_policy": "Under review. Transition between no-card free tier and developer credit tier requires verification.",
          "privacy_disclosure": "Operational logging.",
          "official_verification_sources": [
            "https://docs.sambanova.ai/cloud/docs/rate-limits"
          ],
          "verification_date": "2026-11-20",
          "review_expiry": "2026-11-25",
          "eligibility_status": "UNDER_REVIEW",
          "is_default": false
        }
      ]
    },
    "groq": {
      "display_name": "Groq Cloud",
      "signup_url": "https://console.groq.com/keys",
      "env_var": "GROQ_API_KEY",
      "approved_origins": ["https://api.groq.com"],
      "approved_api_bases": ["https://api.groq.com/openai/v1"],
      "account_billing_policy": "under_review",
      "provider_status": "UNDER_REVIEW",
      "inventory_source": {
        "url": "https://api.groq.com/openai/v1/models",
        "method": "GET",
        "auth": "GROQ_API_KEY",
        "refresh_interval_minutes": 1440,
        "eligibility_filter": "Discover active IDs, then require current Groq Free-tier no-charge policy, account entitlement, and per-model availability evidence before eligibility"
      },
      "models": []
    }
  }
}
```

---

## 2. Section 2: Hybrid Credential Discovery & Keyring Storage Architecture

### 2.1 Resolution Precedence & Immutability
When determining the API key or token for a provider, ATLAS resolves credentials strictly through `CredentialManager`:

```text
1. Environment Variable (e.g. OPENROUTER_API_KEY, GEMINI_API_KEY, CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID)
   │  [Found?] ── YES ──> Return Credential (READ-ONLY, NEVER OVERWRITTEN)
   └── NO
2. OS Secure Keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service)
   │  [Found?] ── YES ──> Return Decrypted Credential
   └── NO
3. User-Scoped Restricted Config File (~/.atlas/credentials.json)
   │  [Found?] ── YES ──> Verify Permissions (0600 on POSIX / Restricted DACL on Windows)
   │                      Return Stored Credential
   └── NO
4. Mark Provider as NEEDS_KEY
```

- **Environment Variable Immutability**: If an environment variable is present, setup warns that it takes precedence and does not modify the environment or create a redundant stored credential. `/models remove` reports that the environment variable is externally managed and cannot be removed by ATLAS.
- **Consent Before File Fallback**: OS keyring via `keyring` is the default persistence layer. If unavailable, ATLAS asks before writing a plaintext fallback to `~/.atlas/credentials.json`; refusal leaves the key only in memory for the current process. Before writing, POSIX permissions are restricted to `0600`; Windows uses a verified owner-only DACL. If restriction cannot be verified, storage fails closed.

### 2.2 Interactive Onboarding Workflow

When a user selects a model or provider whose authentication status is `NEEDS_KEY`:

```text
╭─ ATLAS Provider Authentication ──────────────────────────────────────────────╮
│ Provider: Google AI Studio                                                  │
│ Model:    gemini-2.5-flash (FREE_VERIFIED)                                  │
│                                                                              │
│ To use this model without charge, generate a free API key at:               │
│ ➜ https://aistudio.google.com/app/apikey                                     │
│                                                                              │
│ [Enter API Key (hidden)]: ••••••••••••••••••••••••••••••••••••••••          │
│ [S] Skip and select another free provider                                    │
│ [C] Cancel                                                                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

1. **Hidden Terminal Input**: Uses `prompt_toolkit` with `is_password=True` (or Python standard `getpass`) so keys never echo to the terminal screen or scrollback buffer.
2. **Voluntary Registration**: Users can press `[S]` or `[Enter]` without input to skip onboarding and switch to another configured free provider (e.g. OpenRouter Free). ATLAS never forces registration with any specific provider.
3. **Headless Execution Guard**: If `not sys.stdin.isatty()` (e.g. CI pipeline or headless background task), onboarding prompts are suppressed. ATLAS returns a structured `NEEDS_KEY` result containing the signup URL and environment variable name; the command exits nonzero without blocking stdin. The parent CLI owns process exit behavior.

### 2.3 Non-Billable Preflight Connectivity & Health Verification

Upon receiving a credential or executing `/models test <provider>`, ATLAS executes a strictly non-billable preflight check:

```python
async def verify_connectivity(self, provider: str, credential: str) -> ProviderHealth:
    """Execute a minimal, non-billable preflight probe against the approved HTTPS origin."""
    ...
```

- **Google AI Studio**: Performs a lightweight `models.get` request for `models/gemini-2.5-flash` against `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash` and sends the key in the `x-goog-api-key` header. Never put the key in a URL, exception text, or request log. This reads metadata without generation-token consumption.
- **OpenRouter Free**: Queries `GET https://openrouter.ai/api/v1/key` with `Authorization: Bearer <key>`. This is a key metadata probe and uses no inference tokens.
- **Cloudflare Workers AI**: Requires `CLOUDFLARE_ACCOUNT_ID` plus a token with the minimum required account permission. Executes `GET https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/models/search?search=@cf/meta/llama-3.3-70b-instruct-fp8-fast` with `Bearer <token>` to verify access without invoking model compute. Missing account ID is a structured setup issue, not a guessed value. Cloudflare Free plan exhaustion returns a 429; `403` can indicate a plan or permission restriction and is mapped to `FORBIDDEN` unless the structured error confirms invalid credentials.
- **Diagnostic Mapping**:
  - Credential-specific `HTTP 401`: Sets status to `INVALID_KEY` with a sanitized actionable message.
  - `HTTP 403`: Sets status to `FORBIDDEN` unless the structured provider error explicitly identifies an invalid credential; distinguish missing permissions, account entitlement, and policy blocks.
  - `HTTP 429`: Sets status to `RATE_LIMITED` and honors valid `Retry-After` information.
  - `HTTP 5xx`: Sets status to `UNAVAILABLE`; retry only under the bounded retry policy, never indefinitely.
  - `Network Failure / Connection Timeout`: Sets status to `UNAVAILABLE` without retrying indefinitely.

### 2.4 Credential Governance & Lifecycle Commands

The CLI and conversation prompt expose discrete governance commands:

| Command | Action |
| :--- | :--- |
| `/models configure <provider>` | Launch the secure hidden input prompt with official signup URL. |
| `/models test <provider>` | Run the non-billable preflight check and output latency and quota status. |
| `/models remove <provider>` | Remove the credential from OS keyring and restricted file storage. Report environment variables as externally managed; do not claim guaranteed memory zeroization. |

- **Credential Presentation**: Never render any portion of a credential in logs, telemetry, tables, prompts, traces, or exported session JSON. Use a fixed marker such as `[configured]`; redaction applies to upstream request and exception data before any output.

---

## 3. ModelRouter Hard Firewall & Transparent Failover

### 3.1 Pre-Flight Free-Only Gate
Every request entering `ModelRouter.complete()` must pass the pre-flight verification gate before adapter selection or network transmission. The gate checks the exact catalogue ID, `FREE_VERIFIED` eligibility, non-expired review evidence, credential validation, `VERIFIED_FREE` or accepted `ATTESTED_FREE` billing entitlement, request capabilities, auxiliary-service policy, account billing policy, and approved HTTPS origin. `UNKNOWN` or `BILLABLE` entitlement raises `PaidRoutingBlockedError` before transmission.

The catalogue distinguishes fixed model IDs from the one approved dynamic router ID, `openrouter/free`. Dynamic routing is allowed only through that exact ID. OpenRouter's non-generation key probe must confirm a free-tier key; if this cannot be established, the provider is not eligible. ATLAS must not accept a caller-supplied upstream model override, paid fallback, arbitrary base URL, or unapproved redirect. Adapter response metadata is recorded as evidence of the selected upstream model when available; missing or contradictory evidence fails the completion closed.

Every model completion is advisory data. It does not itself authorize or execute a tool action: any proposed action still passes the existing `ActionFirewall` authorization and deterministic post-condition verification.

```python
def assert_free_eligible(self, model_id: str, request: ModelRequest) -> ModelEntry:
    entry = self.catalogue.get_model(model_id)
    if not entry:
        raise PaidRoutingBlockedError(f"Model '{model_id}' is not present in the verified free catalogue.")
    if entry.eligibility_status != ModelEligibilityStatus.FREE_VERIFIED:
        raise PaidRoutingBlockedError(
            f"Model '{model_id}' is {entry.eligibility_status} and cannot be executed."
        )
    if datetime.now(UTC) > entry.review_expiry:
        raise PaidRoutingBlockedError(
            f"Model '{model_id}' review expired on {entry.review_expiry.isoformat()}. Re-audit required."
        )
    return entry
```

The implementation must also enforce provider-specific account constraints and reject auxiliary features unless each service has an independently verified free allowance and remaining quota. Transport errors, malformed provider metadata, or undocumented redirects never downgrade these checks.

### 3.2 Transparent Free-to-Free Failover Policy
- **No Silent Model Mutation**: Once a task begins with a selected model, ATLAS will not secretly switch models mid-execution.
- **Rate Limit Handshake**: For an explicit HTTP 429, honor `Retry-After` when valid; otherwise use bounded backoff (maximum two retries). Do not retry 401/403, 5xx, connection errors, or timeouts indefinitely. If the limit persists, enumerate only non-expired `FREE_VERIFIED` models that meet the request requirements, then show the user the proposed model and provider disclosure. Switch only after explicit confirmation or a previously configured `auto_fallback: true` preference. Record the selected model in the turn transcript before issuing the fallback request.
- **Ambiguous Completion**: If the request may have reached the provider but no response was received, report `OUTCOME_UNKNOWN`; do not automatically retry or switch providers, since that can duplicate usage and conceal which endpoint processed the request.
- **Fail-Closed Halt**: If all free models are exhausted, execution halts immediately with an explanatory report. Under no circumstances will a paid endpoint or paid fallback be consulted.

---

## 4. CLI/TUI Interaction & Verification Strategy

### 4.1 `/models` User Workflows
- `/models` lists the full discovered catalog across enabled providers and shows eligible models first; under-review and ineligible entries are available through filters with the reason they cannot run. Each row shows exact model/provider ID, provider, route type, cost evidence, account entitlement state, availability period, capabilities, eligibility, authentication, and runtime state.
- `/models refresh` refreshes all configured provider inventories using non-generation metadata calls. It reports source timestamp, source failures, additions, removals, price changes, expired promotions, and any newly blocked models. A failed refresh never upgrades a stale entry to eligible.
- `/models --free` displays candidates whose complete cost metadata is zero; `/models --provider <provider>` and `/models --filter <capability>` narrow the full list.
- `/models use <model-id>` validates the exact catalogue ID, then uses the credential onboarding flow only when needed. No model is silently selected because another provider is unavailable.
- `/models configure <provider>` displays the official signup URL, accepts hidden input, validates the credential with the non-billable provider probe, and asks before plaintext file fallback when keyring storage is unavailable.
- `/models test <provider>` displays probe result, latency, and available documented quota information. It redacts all credentials and does not generate model output.
- `/models remove <provider>` removes ATLAS-managed stored credentials and reports any still-active environment variable without attempting to mutate it.
- Headless calls return structured status and actionable setup fields without prompting or hanging. Interactive commands provide skip and cancel paths.

### 4.2 TUI Status and Consent
The conversation header shows the selected provider/model and whether fallback is enabled. A fallback prompt names the candidate, its privacy disclosure, and any capability differences. A user choice is recorded for that turn; a saved automatic-fallback preference is explicit, visible, and reversible. Credential values and fragments never appear in the TUI, screenshots, session exports, or diagnostic traces.

### 4.3 Verification Matrix
Implementation must add deterministic tests for:
- Catalogue schema parsing, discovery pagination, source timeout/staleness, exact all-billable-fields-zero filtering, audit expiry, promotion expiry, provider status independence, exact IDs, and rejection of paid/local/under-review entries.
- Credential precedence, immutable environment variables, opt-in file fallback, POSIX and Windows permission enforcement, keyring failures, redaction, remove semantics, and headless behavior.
- Provider probe URLs, headers, required Cloudflare account ID, non-generation behavior, status mapping (`401`, `403`, `429`, `5xx`, timeout), bounded retries, and secret-free logs.
- Origin and redirect rejection, auxiliary-service quarantine, default selection, ActionFirewall separation, and dynamic-router response handling.
- User-confirmed fallback, configured automatic fallback, capability mismatch, expired candidates, ambiguous outcomes, and total free-provider exhaustion.
- CLI/TUI rendering and exports to ensure statuses remain distinct and no credential value or fragment leaks.

Tests use mocked HTTP transports and deterministic clocks; no test may invoke a paid endpoint, perform generation as a preflight, or require a live secret. Provider documentation audits are a separate manual release gate and must record source URL, checked date, account assumptions, quota/billing evidence, and reviewer.

### 4.4 Completion and Release Gate
Sections 1–4 and the implementation plan now define the broad catalog, credential lifecycle, routing firewall/fallback behavior, and CLI/TUI verification requirements. This is a specification only: no production code, tests, commits, or deployments are claimed by this document. Provider account, quota, and privacy evidence must be refreshed before each provider is marked eligible. Implementation verification and project status updates remain required by `docs/PROJECT_STATUS.md` and `docs/IMPLEMENTATION_PLAN.md`.
