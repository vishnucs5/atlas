# Model Provider Adapter Architecture

## 1. Executive Summary

ATLAS provides an independent, provider-agnostic model interaction layer that isolates AI models behind typed contracts. The design enforces strict boundaries:
- **`packages/atlas-core`** defines domain schemas and abstract protocols without importing any external vendor SDKs (OpenAI, Anthropic, Google GenAI, etc.).
- **`packages/atlas-models`** implements concrete adapters for OpenAI, Anthropic, Google Gemini, Ollama, and OpenAI-compatible local/remote servers (vLLM, LocalAI, etc.) alongside capability-aware routing, circuit breakers, and cost tracking.

---

## 2. Component Architecture

```
+-----------------------------------------------------------------------------------+
|                               packages/atlas-agent                                |
|   (Autonomous Agent Loop, Structured Planner, Context Manager, Prompt Injection) |
+-----------------------------------------+-----------------------------------------+
                                          |
                              ModelRequest / ModelResponse
                                          v
+-----------------------------------------------------------------------------------+
|                               packages/atlas-models                               |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  |                                ModelRouter                                  |  |
|  |   - Capability Filtering (Vision, Tools, Context Window, Modalities)        |  |
|  |   - Health & Latency Monitoring                                             |  |
|  |   - Circuit Breakers & Exponential Backoff Retry                            |  |
|  |   - Cost & Token Aggregation Tracking                                       |  |
|  |   - Fallback Cascade (Primary -> Secondary -> Local)                        |  |
|  +-----------------------------------------------------------------------------+  |
|                                         |                                         |
|         +---------------+---------------+---------------+---------------+         |
|         |               |               |               |               |         |
|         v               v               v               v               v         |
|  +-------------+ +-------------+ +-------------+ +-------------+ +-------------+  |
|  |   OpenAI    | |  Anthropic  | |   Gemini    | |   Ollama    | |  OpenAI-    |  |
|  |   Adapter   | |   Adapter   | |   Adapter   | |   Adapter   | | Compatible  |  |
|  +-------------+ +-------------+ +-------------+ +-------------+ +-------------+  |
|         |               |               |               |               |         |
|         | HTTP (httpx)  | HTTP (httpx)  | HTTP (httpx)  | HTTP (httpx)  | HTTP    |
+---------+---------------+---------------+---------------+---------------+---------+
          |               |               |               |               |
          v               v               v               v               v
    api.openai.com api.anthropic.com   Google API   localhost:11434    vLLM / Groq
```

---

## 3. Data Contracts (`packages/atlas-core/contracts/model.py`)

All model exchanges are governed by Pydantic v2 data models with `schema_version = "1.0"`:

### 3.1. Messages & Multimodal Content
- **`ModelMessage`**: Contains `role` (`system`, `user`, `assistant`, `tool`), `content` (string or list of `ContentPart`), optional `tool_call_id`, `name`.
- **`ContentPart`**: Polymorphic container supporting:
  - `TextPart`: Pure text prompt or reasoning output.
  - `ImagePart`: Base64 encoded or URL reference, `media_type` (`image/png`, `image/jpeg`, `image/webp`), and `detail` (`auto`, `low`, `high`).

### 3.2. Tools & Function Calling
- **`ToolDefinition`**: Standardized JSON schema specification (`name`, `description`, `parameters`).
- **`ToolCall`**: Invocation identifier, function `name`, and parsed JSON `arguments` (dictionary).

### 3.3. Request & Response Envelopes
- **`ModelRequest`**:
  - `request_id`: Unique correlation UUID.
  - `task_id`: Parent task identifier for event tracing.
  - `model_name`: Requested model identifier (e.g. `gpt-4o`, `claude-3-5-sonnet-20241022`, `gemini-1.5-pro`, `llama3.2`).
  - `messages`: List of `ModelMessage`.
  - `tools`: List of `ToolDefinition`.
  - `temperature`: Sampling temperature (0.0 to 1.0).
  - `max_tokens`: Maximum completion tokens.
  - `system_prompt`: High-priority system instructions.
- **`ModelResponse`**:
  - `response_id`: Model response UUID.
  - `request_id`: Originating request ID.
  - `model_name`: Responding model name.
  - `content`: Generated text response (or None if pure tool call).
  - `tool_calls`: List of validated `ToolCall` instances.
  - `raw_finish_reason`: Provider raw reason (`stop`, `tool_calls`, `length`, etc.).
  - `usage`: `TokenUsage` metrics (prompt, completion, total, cached tokens, and USD cost).
  - `latency_ms`: Round-trip execution latency in milliseconds.

### 3.4. Errors & Health Contracts
- **`ModelError`**:
  - `error_type`: Normalized enum: `RATE_LIMIT` (429), `CONTEXT_LENGTH_EXCEEDED`, `AUTHENTICATION` (401/403), `INVALID_REQUEST` (400), `SERVER_ERROR` (500/503), `TIMEOUT`, `UNKNOWN`.
  - `message`: Sanitized error message (secrets redacted).
  - `provider`: Provider identifier.
  - `status_code`: HTTP status code (if applicable).
  - `retryable`: Boolean indicating whether backoff retry is warranted.
- **`ProviderHealth`**:
  - `status`: `HEALTHY`, `DEGRADED`, `UNAVAILABLE`.
  - `provider_id`: Identifier of the provider adapter.
  - `latency_ms`: Ping/probe latency.
  - `error`: Diagnostics message if degraded or unavailable.

---

## 4. Supported Providers & Normalization Strategy

| Provider | Authentication | Tool Call Format | Vision Ingestion | Error Normalization |
|---|---|---|---|---|
| **OpenAI** | Bearer Token (`OPENAI_API_KEY`) | `tools[].function`, `tool_calls[]` | Data URL / Base64 in `image_url` | RateLimitError, BadRequestError, AuthenticationError |
| **Anthropic** | `x-api-key`, `anthropic-version` | `tools[].input_schema`, `tool_use` blocks | Source block: `{"type": "base64", "media_type": ..., "data": ...}` | 429 rate_limit_error, 400 invalid_request |
| **Google Gemini** | Query param `key` or Bearer header | `tools[].function_declarations`, `functionCall` | `inlineData` with `mimeType` and `data` | ResourceExhausted (429), InvalidArgument (400) |
| **Ollama** | None (Local HTTP endpoint) | `/api/chat` `tools` format | `images` base64 array per message | Local socket connection errors, OOM |
| **OpenAI-Compatible** | Configurable Bearer or Header | OpenAI ChatCompletions standard | OpenAI Data URL standard | Generic HTTP status mapping |

---

## 5. Resilient Routing & Circuit Breakers

The `ModelRouter` manages provider selection and execution resilience:

1. **Capability Matching**:
   Agents specify required capabilities (e.g. `requires_vision=True`, `requires_tools=True`, `min_context_window=64000`). The router filters candidate adapters against their declared `ModelCapabilities`.
2. **Circuit Breaking**:
   Each adapter maintains an internal circuit state:
   - `CLOSED`: Normal operation. Failures increment an error counter.
   - `OPEN`: Triggered when failure threshold (e.g. 5 consecutive errors) is exceeded within the evaluation window. Immediately redirects requests to fallback adapters without network timeout penalty.
   - `HALF-OPEN`: After a cool-down period (e.g. 60s), a probe request is permitted. Success resets to `CLOSED`; failure returns to `OPEN`.
3. **Rate-Limit Retry with Jitter**:
   HTTP 429 and transient 503 errors trigger exponential backoff:
   $$\text{delay} = \min(\text{max\_backoff}, \text{base} \times 2^{\text{attempt}}) + \text{jitter}$$
4. **Token & Cost Accounting**:
   Every response's `TokenUsage` is recorded, computing costs according to declared per-1K input/output rates, enabling per-task budget monitoring.
