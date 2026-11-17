# ATLAS CLI — Stage 1 Foundation Implementation Report

**Branch**: `feat/atlas-cli-foundation`  
**Base Commit**: `5775285086aa3ce690b7fd3e648d3ac075dee2da`  
**Protected Master**: `5632b661abeb517b7683623a699342f960e5310f` (`Untouched`)  
**Stage Status**: `COMPLETED & VERIFIED`  
**Test Verdict**: `12/12 CLI Foundation & Worker tests PASSED (100%)`

---

## 1. Executive Summary

Stage 1 establishes the native, installable developer command-line interface for the ATLAS platform. Rather than building a decoupled shell or wrapper agent, the ATLAS CLI acts as a native presentation and client interface directly connected to the verified `ProductionRuntime`, `ActionFirewall`, and `AgentSupervisor` engines.

All 8 Stage 1 core foundation requirements have been implemented, tested, and validated:
1. **Installable `atlas` Command**: Registered under `[project.scripts]` in `apps/cli/pyproject.toml`.
2. **Command Router & Signal Handling**: Graceful shutdown on `SIGINT` (Ctrl+C) and `SIGTERM` with clean exit code `130`.
3. **Configuration Precedence**: Environment variables (`ATLAS_<KEY>`) take precedence over `~/.atlas/config.json` with secure, safe defaults and zero plaintext credential leakage.
4. **Model Selection**: Multi-vendor selection (`atlas:hermetic-default`, `openai/gpt-4o`, `anthropic/claude-3-5-sonnet`, `gemini/gemini-2.5-pro`, `ollama/llama3`) integrated with `ModelRouter`.
5. **Session Durability & Replay**: Persistent JSON session state records under `~/.atlas/sessions/` with JSON and Markdown export capabilities.
6. **Streaming & Terminal Formatting**: High-fidelity ANSI colors, aligned tables, syntax-highlighted code blocks, unified diffs, and badges with automatic terminal width adaptation (`shutil.get_terminal_size()`).
7. **Minimal Headless Runner**: CI/CD and pipeline mode (`atlas --minimal`) supporting piped stdin and structured NDJSON output.
8. **Interactive Terminal UI**: Full-screen live control plane dashboard (`atlas --tui`) with specialist agent status, task deliverables, and interactive command dispatch.

---

## 2. Directory Architecture & Modular Boundaries

Stage 1 organizes `apps/cli/src/atlas_cli/` into strictly bounded architectural modules:

```
apps/cli/src/atlas_cli/
  ├── __init__.py
  ├── main.py                     # Top-level CLI entry point, argument parsing, signal trapping
  ├── config.py                   # Legacy config bindings
  ├── adapters/
  │   ├── __init__.py
  │   └── client.py               # AtlasClient: Local HTTP/IPC client with embedded fallback
  ├── approvals/
  │   ├── __init__.py
  │   └── interactive.py          # Interactive Action Firewall approval prompting
  ├── commands/
  │   ├── agents.py               # atlas agents (list, inspect, run)
  │   ├── approval.py             # atlas approval (list, grant, deny)
  │   ├── coding.py               # atlas "prompt", plan, review, debug, test
  │   ├── doctor.py               # atlas doctor diagnostics
  │   ├── environment.py          # atlas environment test browser
  │   ├── governance.py           # atlas config, permissions, status
  │   ├── init.py                 # atlas init scaffolding
  │   ├── models.py               # atlas models (list, use, configure)
  │   ├── runtime.py              # atlas server status, workers list, logs
  │   ├── sessions_cmd.py         # atlas sessions (list, resume, export)
  │   ├── task.py                 # atlas task (create, list, inspect, pause, resume, cancel)
  │   ├── tools_plugins.py        # atlas tools, plugins, mcp
  │   └── worker.py               # atlas worker daemon launcher
  ├── configuration/
  │   ├── __init__.py
  │   └── manager.py              # ConfigManager: Precedence, validation, zero secret leaks
  ├── minimal/
  │   ├── __init__.py
  │   └── runner.py               # Headless runner for CI/CD scripting
  ├── rendering/
  │   ├── __init__.py
  │   └── formatters.py           # ANSI colors, dynamic tables, markdown, diffs, badges
  ├── sessions/
  │   ├── __init__.py
  │   └── manager.py              # SessionManager: Durable session state, history, export
  └── tui/
      ├── __init__.py
      └── app.py                  # Interactive Terminal User Interface dashboard
```

---

## 3. Command Surface Verification

All target Stage 1 commands were tested directly against the running runtime:

```bash
# Launch & Diagnostics
atlas --version         # [VERIFIED] ATLAS v0.16.8 (Autonomous Task & Lifecycle Automation System)
atlas --help            # [VERIFIED] Formatted usage guide with all subcommands
atlas status            # [VERIFIED] Control Plane ONLINE, Active Model, Worker count
atlas doctor            # [VERIFIED] Python version, OS platform, and SQLite WAL capability

# Model Selection
atlas models list       # [VERIFIED] Displays 5 registered model adapters and active marker
atlas models use ...    # [VERIFIED] Switches and persists default active model
atlas models configure  # [VERIFIED] Displays provider key status without leaking secrets

# Governance & Security
atlas permissions       # [VERIFIED] Displays Action Firewall policies and risk ratings
atlas approvals         # [VERIFIED] Interactive Action Firewall authorization prompt

# Sessions & History
atlas sessions list     # [VERIFIED] Lists chronological saved CLI sessions
atlas sessions export   # [VERIFIED] Exports session trace as JSON or Markdown

# Tools, Plugins & Runtime
atlas tools list        # [VERIFIED] Lists 7 core tools with driver bindings and risk ratings
atlas plugins list      # [VERIFIED] Lists installed workflow & skill plugins
atlas mcp list          # [VERIFIED] Lists registered Model Context Protocol servers
atlas server status     # [VERIFIED] Pings local FastAPI daemon on port 8000
atlas workers list      # [VERIFIED] Displays connected execution worker fleet
atlas logs              # [VERIFIED] Streams chronological execution events
```

---

## 4. Test Evidence & Quality Invariants

The Stage 1 unit test suite (`tests/unit/test_cli_foundation.py`) was executed with 100% pass rate:

```
tests/unit/test_cli_foundation.py::test_cli_entrypoint_help_and_version PASSED [  8%]
tests/unit/test_cli_foundation.py::test_cli_default_invocation_shows_banner_and_help PASSED [ 16%]
tests/unit/test_cli_foundation.py::test_cli_command_routing PASSED       [ 25%]
tests/unit/test_cli_foundation.py::test_configuration_precedence_and_security PASSED [ 33%]
tests/unit/test_cli_foundation.py::test_model_selection_commands PASSED  [ 41%]
tests/unit/test_cli_foundation.py::test_session_lifecycle_and_export PASSED [ 50%]
tests/unit/test_cli_foundation.py::test_terminal_rendering_formatters PASSED [ 58%]
tests/unit/test_cli_foundation.py::test_minimal_mode_headless_execution PASSED [ 66%]
tests/unit/test_cli_foundation.py::test_cross_platform_and_signal_handling PASSED [ 75%]
tests/unit/test_worker_cli.py::test_worker_daemon_processing_and_lease PASSED [ 83%]
tests/unit/test_worker_cli.py::test_cli_task_pause_resume_cancel PASSED  [ 91%]
tests/unit/test_worker_cli.py::test_cli_approval_commands PASSED         [100%]
============================= 12 passed in 10.82s =============================
```

* **Static Analysis**: `uv run ruff check .` passed with 0 errors.
* **Code Formatting**: `uv run ruff format .` passed clean across all monorepo files.
* **Action Firewall Invariant**: All action calls pass through policy evaluation.
* **Master Invariant**: Protected branch `master` remains pristine at `5632b661abeb517b7683623a699342f960e5310f`.

---

**STAGE 1 COMPLETE — AWAITING HUMAN REVIEW & APPROVAL TO PROCEED TO STAGE 2.**
