# ADR-0005: Model Provider Adapter Architecture

## Status
Accepted

## Date
2026-11-12

## Context & Problem Statement
ATLAS requires seamless integration with diverse Large Language Model (LLM) and multimodal providers (OpenAI, Anthropic, Google Gemini, Ollama, and OpenAI-compatible local/remote endpoints such as vLLM). Each provider features distinct API conventions, message structures, tool/function calling formats, vision/multimodal schemas, token usage reporting, rate-limiting headers, and error hierarchies.

Directly coupling agent planning logic to proprietary SDKs or third-party abstractions (e.g. LangChain, LiteLLM) introduces severe architectural vulnerabilities:
1. **Core Bloat & Dependency Pollution**: Importing heavy provider SDKs into `atlas-core` violates Constitutional Rule 3 (Zero-Dependency Core).
2. **Hidden Execution / Unsafe Direct Action**: Third-party framework wrappers often bundle autonomous execution logic inside tool wrappers, violating Constitutional Rule 2 (Action Firewall: The model makes decisions; ATLAS controls execution).
3. **Inconsistent Error Recovery & Health Probing**: Un-normalized provider exceptions make circuit breaking, fallback routing, and resilient backoff brittle and opaque.

ATLAS requires a clean, decoupled adapter architecture where provider-independent contracts are defined in `atlas-core`, and concrete normalized adapters are isolated in `atlas-models`.

## Decision Drivers
- **Constitutional Rule 1 (Architecture Ownership)**: ATLAS must own the orchestration lifecycle, model interaction boundaries, and tool definitions.
- **Constitutional Rule 3 (Zero-Dependency Core)**: `packages/atlas-core` must define pure Pydantic v2 domain schemas (`ModelRequest`, `ModelResponse`, `ModelCapabilities`, `ModelMessage`, `ToolDefinition`, `ToolCall`, `TokenUsage`, `ProviderHealth`, `ModelError`) with no SDK dependencies.
- **Constitutional Rule 6 (No Secret Leaks)**: API keys, tokens, and authorization headers must never appear in log output, prompt traces, or error messages.
- **Provider Agnosticism**: Pluggable adapters for OpenAI, Anthropic, Gemini, Ollama, and OpenAI-compatible endpoints with identical interfaces.
- **Capability-Aware Routing**: Dynamic selection of models based on vision support, tool calling, context window, and health.
- **Hermetic Offline Testing**: Complete test coverage via mocked HTTP transports with zero required API keys in CI.

## Considered Options
1. **Third-Party Unified LLM Wrappers (e.g. LiteLLM, LangChain)**:
   - *Pros*: Faster initial setup; pre-built mappings.
   - *Cons*: Heavy transitive dependency tree; unpredictable breaking upstream changes; violates Zero-Dependency Core and Architecture Ownership rules; leaks implementation details; difficult to sandbox.
2. **Direct Heavy SDK Imports in Each Driver**:
   - *Pros*: Leverages official vendor libraries (`openai`, `anthropic`, `google-genai`).
   - *Cons*: Significant version conflicts between vendor SDKs; divergent async paradigms; vendor lock-in.
3. **Decoupled Adapter Architecture with Standard HTTP Client (`httpx`)**:
   - *Pros*: Native ATLAS protocol (`ModelAdapter`); isolated package (`atlas-models`); pure HTTP request/response normalization using `httpx`; zero vendor SDK baggage required for core; complete control over header sanitization, retry backoff, and circuit breaking; trivial to mock and unit test.
   - *Cons*: Requires maintaining schema translation mappings for supported providers.

## Decision Outcome
Adopt **Option 3: Decoupled Adapter Architecture with Native Normalized Protocols**.

### Architecture Overview
1. **Core Contracts (`packages/atlas-core/contracts/model.py`)**:
   - `ModelRequest`: Unified request envelope including `request_id`, `task_id`, `model_name`, `messages`, `tools`, `temperature`, `max_tokens`.
   - `ModelResponse`: Unified response envelope including `content`, `tool_calls`, `usage`, `raw_finish_reason`, `latency_ms`.
   - `ModelMessage`: Role-based message with support for structured multimodal content (`TextPart`, `ImagePart`).
   - `ToolDefinition` & `ToolCall`: Standardized function definitions and structured call invocations.
   - `TokenUsage`: Prompt, completion, total, cached tokens, and estimated cost tracking.
   - `ProviderHealth`: Diagnostic health state (`HEALTHY`, `DEGRADED`, `UNAVAILABLE`), latency, and error tracking.
   - `ModelError`: Normalized error classification (`RATE_LIMIT`, `CONTEXT_LENGTH_EXCEEDED`, `AUTHENTICATION`, `INVALID_REQUEST`, `SERVER_ERROR`, `TIMEOUT`).
2. **Adapter Interface (`packages/atlas-models/adapter.py`)**:
   - Protocol specifying `async complete()`, `async stream()`, `async health_check()`, `get_capabilities()`.
3. **Concrete Adapters (`packages/atlas-models/adapters/`)**:
   - `OpenAIAdapter`: Native OpenAI Chat Completions API with function calling and base64 vision.
   - `AnthropicAdapter`: Claude Messages API with system prompt extraction, `input_schema` tools, and image source blocks.
   - `GeminiAdapter`: Google Gemini REST format with `functionDeclarations` and `inlineData` image parts.
   - `OllamaAdapter`: Local inference via Ollama `/api/chat` with zero external credentials.
   - `OpenAICompatibleAdapter`: Flexible endpoint for vLLM, LocalAI, Groq, Mistral, Together with configurable `base_url`.
4. **Resilient Model Router (`packages/atlas-models/router.py`)**:
   - Capability-based matching (e.g. filter models by `vision=True`, `tool_calling=True`).
   - Health-aware fallback ordering (primary provider $\to$ secondary provider on transient failures).
   - Circuit breakers to fast-fail on sustained provider outages.
   - Exponential backoff with jitter on 429 rate limits.
   - Token and cost aggregation per task and session.

## Consequences

### Positive
- Strict compliance with Constitutional Rules 1, 3, and 6.
- Total independence from proprietary framework abstractions.
- 100% testable offline with deterministic HTTP fixtures.
- Local inference (Ollama, vLLM) treated as first-class citizens alongside proprietary cloud providers.
- Secret sanitization applied deterministically before any error or log emission.

### Negative / Trade-offs
- Adding new provider API features (e.g. provider-specific tool flags) requires updating translation mappings in `atlas-models`.
