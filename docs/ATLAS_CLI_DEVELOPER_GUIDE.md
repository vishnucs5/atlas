# ATLAS CLI Core Developer & Contributor Guide

Guidelines for contributing to the ATLAS CLI monorepo codebase.

---

## 1. Monorepo Structure & Package Boundaries

```
happy-meitner/
├── apps/
│   ├── api/                      # Production REST API & Operator Dashboard
│   ├── cli/                      # ATLAS Developer CLI (apps/cli)
│   │   ├── pyproject.toml        # Hatchling build specification
│   │   └── src/atlas_cli/        # Core CLI modules
│   │       ├── approvals/        # Interactive approval cards & UX
│   │       ├── commands/         # Subcommand dispatchers
│   │       ├── configuration/    # Precedence hierarchy & settings
│   │       ├── ecosystem/        # MCP, plugins, skills, profiles, enterprise
│   │       ├── events/           # Event streaming & state reconstruction
│   │       ├── minimal/          # Headless REPL runner & syntax highlighting
│   │       ├── rendering/        # Terminal tables, badges, and colors
│   │       ├── sessions/         # Session persistence & SQLite storage
│   │       └── tui/              # Textual 8-panel interactive dashboard
│   └── worker/                   # Standalone background execution daemon
└── packages/
    ├── atlas-core/               # Zero-dependency contracts & state machine
    ├── atlas-storage/            # SQLite & PostgreSQL persistence
    ├── atlas-policy/             # Action Firewall & security governor
    ├── atlas-coding/             # File ops, patch engine, terminal runner
    ├── atlas-code-intelligence/  # AST symbol indexing, graph, code search
    ├── atlas-orchestration/      # 11 specialist agents & team supervisor
    ├── atlas-marketplace/        # Package manifests & SemVer resolver
    ├── atlas-skills/             # Skill SDK contracts & execution
    ├── atlas-enterprise/         # IAM, RBAC, tenant isolation, audit ledger
    └── atlas-federation/         # Remote worker discovery & session leasing
```

---

## 2. Invariants for Contributors

1. **Zero-Dependency Core**: `packages/atlas-core` must **NEVER** import external drivers, OS-specific APIs, or database engines.
2. **Action Firewall**: Every action must be authorized by policy before execution.
3. **No Placeholders**: Never write dummy or placeholder implementations in production code paths.
4. **No Swallowing Exceptions**: Errors must be structured, logged with context, and handled via recovery transitions.
5. **Secret Redaction**: Credentials, tokens, and keys must never appear in logs, prompts, or screen buffers.
6. **Verification Invariant**: Actions are never reported as successful without deterministic post-condition verification.

---

## 3. Running Tests Locally

Use `uv` for fast, hermetic test execution:

```bash
# Run all unit tests for the CLI and its core dependencies
uv run pytest tests/unit/test_cli_foundation.py \
              tests/unit/test_coding_engine.py \
              tests/unit/test_cli_interfaces.py \
              tests/unit/test_code_intelligence.py \
              tests/unit/test_multi_agent.py \
              tests/unit/test_enterprise_ecosystem.py -v

# Run the complete monorepo test suite (928+ tests)
uv run pytest -v
```

---

## 4. Code Formatting & Linting

All contributions must pass Ruff checks cleanly:

```bash
# Linting
uv run ruff check .

# Formatting check
uv run ruff format --check .

# Auto-format
uv run ruff format .
```
