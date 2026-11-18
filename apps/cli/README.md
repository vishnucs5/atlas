# ATLAS CLI — Autonomous Developer Environment & Enterprise Coding Agent

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

ATLAS CLI is a model-agnostic, open-source autonomous coding agent and developer environment. It understands complex codebases, plans engineering work, writes and tests code, coordinates specialist agents, and recovers interrupted execution safely under the **Action Firewall**.

---

## Key Capabilities

- **Dual Interaction Modes**:
  - `atlas` / `atlas --minimal`: Clean, scriptable terminal conversation with streaming markdown and syntax highlighting.
  - `atlas --tui`: Rich 8-panel interactive Textual dashboard for comprehensive operational awareness.
- **Autonomous Coding Engine**:
  - `OBSERVE -> PLAN -> FIREWALL -> APPROVAL -> EXECUTE -> VERIFY -> CHECKPOINT -> COMPLETE`.
  - Transactional patch application with dry-runs and automated multi-file rollback.
- **Repository Intelligence**:
  - Multi-language AST symbol extraction, dependency graph analysis, cycle detection, and BM25 local code search.
- **Multi-Agent Specialist Engineering**:
  - 11 specialized agent roles coordinated by a supervisory task-graph engine with dynamic collision prevention.
- **Extensible Ecosystem**:
  - Model Context Protocol (MCP) integrations over stdio/sse.
  - Cryptographically verified plugins with SHA-256 integrity and publisher trust checks.
  - Adversarially defended skill SDK pre-loaded with 7 engineering workflows.
  - Workspace development profiles with strict privilege ceiling enforcement.
- **100% Offline Independence**:
  - Open-source core operates completely offline without proprietary external cloud dependencies.
  - Optional enterprise extensions for centralized IAM, compliance audit ledgers, and remote federation.

---

## Quickstart

### Installation

```bash
# Using uv (recommended)
uv tool install atlas-cli

# Using pip
pip install atlas-cli
```

### Initializing a Project

```bash
cd /path/to/your/repository
atlas init
```

### Starting an Autonomous Coding Task

```bash
# Direct objective prompt
atlas "Implement JWT authentication middleware with refresh token rotation"

# Minimal interactive REPL
atlas --minimal

# Advanced interactive dashboard
atlas --tui
```

---

## Command Reference

| Command | Description |
| :--- | :--- |
| `atlas run "<goal>"` | Execute an autonomous coding task with specified goal. |
| `atlas -p "<goal>"` | Execute an autonomous coding task with prompt flag. |
| `atlas plan "<goal>"` | Generate a structured engineering implementation plan without executing modifications. |
| `atlas review [--diff]` | Run independent adversarial code review on active working tree or diff. |
| `atlas test` | Run project test suites with automated framework detection (`pytest`, `npm`, `cargo`, `go`). |
| `atlas debug` | Inspect failed test runs and generate reproduction hypotheses. |
| `atlas skills list` | View registered engineering workflow skills. |
| `atlas profiles list` | View workspace profiles and active privilege ceilings. |
| `atlas plugins list` | Inspect installed plugins and verification states. |
| `atlas mcp list` | Inspect Model Context Protocol (MCP) servers and tools. |
| `atlas edition` | Display product edition and offline feature availability report. |
| `atlas doctor` | Run environment diagnostics, SQLite WAL checks, and platform verification. |

---

## Security Invariants

1. **Core Ownership**: Core owns planning and orchestration; drivers only execute authorized interfaces.
2. **Action Firewall**: Every action is gated by deterministic policy checks; model descriptions cannot bypass permissions.
3. **No Direct OS Execution**: Shell commands execute via `shell=False` argument vectors with secret scrubbing.
4. **Zero Silent Overwrites**: Optimistic concurrency checks prevent overwriting out-of-date files.

For full architectural documentation, refer to the [`docs/`](../../docs/) directory.
