# ATLAS Observability (`packages/atlas-observability`)

Context-bound structured JSON logging, execution tracing, and high-speed secret redaction for the ATLAS system.

## Key Capabilities

1. **Context-Bound Metadata**: Uses standard Python `contextvars` to attach execution context (`task_id`, `session_id`, `correlation_id`, `step_id`, etc.) across asynchronous and multi-threaded call chains without manual parameter passing.
2. **Zero Leaks Secret Redaction (Constitution Rule 6)**: High-performance regular expression pattern matching redacting API keys (OpenAI, Anthropic, Gemini), bearer tokens, AWS credentials, GitHub tokens, PEM private keys, and sensitive key-value pairs before writing to output streams.
3. **Structured JSON Output**: Emits newline-delimited JSON with ISO 8601 UTC timestamps, log levels, logger identifiers, and structured attributes.
4. **Zero External Dependencies**: Implemented strictly using the Python 3.11+ standard library.
