# ATLAS CLI Model Providers & Adapter Specification

## 1. Architectural Invariant: Provider Agnosticism

ATLAS CLI interacts with Large Language Models exclusively through the `ModelAdapter` abstract contract defined in `packages/atlas-models`. The CLI never communicates with raw proprietary HTTP APIs directly.

```
┌────────────────────────────────────────────────────────┐
│                      ATLAS CLI                         │
│                                                        │
│  ┌───────────────────┐        ┌─────────────────────┐  │
│  │   Coding Engine   │───────>│    Model Router     │  │
│  └───────────────────┘        └──────────┬──────────┘  │
│                                          │             │
│                 ┌────────────────────────┴───────────┐ │
│                 ▼                                    ▼ │
│      ┌───────────────────────┐            ┌──────────────┐
│      │  Hermetic Mock Engine │            │ Remote APIs  │
│      │  (100% Offline Core)  │            │ (Authorized) │
│      └───────────────────────┘            └──────────────┘
└────────────────────────────────────────────────────────┘
```

---

## 2. Supported Model Adapters

ATLAS CLI supports multiple model backends:

1. **Hermetic Mock Provider (Default Offline)**:
   - Zero network connection required.
   - Provides deterministic, syntactically valid code patches, execution plans, and architectural decompositions.
   - Used for air-gapped CI/CD, local testing, and offline workstations.

2. **Google Gemini Provider**:
   - High-speed multimodal understanding, repository reasoning, and code patch synthesis.
   - Supports streaming token chunks into the minimal REPL and TUI dashboard.

3. **Anthropic Claude Provider**:
   - Long-context code generation and rigorous structural refactoring.

4. **OpenAI Provider**:
   - General-purpose autonomous reasoning and test synthesis.

5. **Local Ollama / vLLM / Llama.cpp Provider**:
   - Connects to self-hosted open-weights models (e.g. Qwen 2.5 Coder, Llama 3) over local HTTP endpoints (`http://localhost:11434/v1`).

---

## 3. Configuring Models via CLI

```bash
# List available configured model adapters
atlas models list

# Switch the active model
atlas models use gemini-1.5-pro

# Interactively configure API keys or local endpoints
atlas models configure
```

### Secure Credential Storage

API keys and secrets configured through `atlas models configure` are stored in your user configuration directory with restricted file permissions (`chmod 600`), masked in logs, and excluded from repository commits.
