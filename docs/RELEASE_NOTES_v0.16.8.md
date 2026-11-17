# ATLAS CLI v0.16.8 Release Notes

**Release Version**: `v0.16.8`  
**Target Architecture**: Open-Source Autonomous Developer Environment & Enterprise Coding Agent  
**Release Date**: 2026-11-17  
**Build Target**: `atlas_cli-0.16.8-py3-none-any.whl`, `atlas_cli-0.16.8.tar.gz`  
**License**: Apache-2.0  

---

## Highlights

ATLAS CLI v0.16.8 transforms the ATLAS platform into a native, cross-platform autonomous developer environment comparable to OpenCode and Kilo Code. It features dual interaction modes, a transactional autonomous coding engine, multi-language repository intelligence, 11 specialized engineering agents, Model Context Protocol (MCP) tool integrations, and enterprise connectivity—while maintaining a 100% offline-ready open-source core.

---

## Detailed Capabilities

### 1. Dual-Mode Terminal Experience
- **Minimal Mode (`atlas`, `atlas --minimal`)**:
  - Interactive REPL with streaming markdown responses and Pygments syntax highlighting.
  - Colorized diff previews and real-time tool indicators.
  - Slash commands: `/help`, `/diff`, `/plan`, `/test`, `/status`, `/approvals`.
- **Advanced TUI Dashboard (`atlas --tui`)**:
  - 8 operational panels: Conversation, Agent Activity, Task Graph, Terminal, File Changes, Approvals, Timeline, Runtime.
  - Responsive terminal scaling (80x24 minimum), keyboard shortcuts `1-8`, `Tab`, `a`, `d`, `r`, `q`.

### 2. Autonomous Coding Engine
- **8-Stage Execution Loop**: `OBSERVE -> PLAN -> FIREWALL -> APPROVAL -> EXECUTE -> VERIFY -> CHECKPOINT -> COMPLETE`.
- **Transactional Patch Engine**: Unified diff parsing with dry-runs and automated multi-file rollback.
- **Optimistic Concurrency**: SHA-256 pre-condition matching prevents silent file overwrites.
- **Safe Git Integration**: Non-destructive porcelain operations (status, diff, branch, log); zero auto-pushes, zero master branch mutations.
- **Automated Test Verification**: Automated runner supporting `pytest`, `npm`, `cargo`, and `go`.

### 3. Repository Intelligence & Context Engine
- **8-Phase Safe Indexing Pipeline**: Fast discovery, classification, parsing, and persistence to `.atlas/index/`.
- **Multi-Language Parsing**: Python native AST parsing (`EXACT_AST`) plus structural parsing for JS/TS, Go, Rust, Java, and C/C++.
- **Symbol Intelligence & Graph**: Function, class, method, variable lookups, cross-module import tracking, cycle detection, and test-to-source mapping.
- **Local Code Search**: Substring, bounded regex, symbol lookup, glob, and BM25 local ranking without external embedding APIs.

### 4. Multi-Agent Specialist Engineering
- **11 Specialist Engineering Roles**:
  Software Architect, Repository Explorer, Backend Engineer, Frontend Engineer, Database Engineer, Infrastructure Engineer, Testing Engineer, Security Auditor, Code Reviewer, Documentation Engineer, Debugging Engineer.
- **Supervisory DAG Orchestration**: Task decomposition, dynamic collision prevention, and failure cancellation cascades.
- **Independent Adversarial Code Review**: Automated checks for security vulnerabilities, shell escapes, secret leaks, and unhandled logic branches.

### 5. Extensibility, Skills & MCP
- **Model Context Protocol (MCP)**: Local and remote server integrations over stdio/sse with Action Firewall enforcement (`mcp.<tool>`).
- **Cryptographic Plugin Ecosystem**: SHA-256 archive checksums and publisher trust verification.
- **Prompt-Defended Skill SDK**: 7 standard built-in engineering workflows with regex pre-screening against prompt injection attacks.
- **Workspace Profiles**: 6 built-in development profiles with strict privilege ceiling enforcement.

### 6. Enterprise Integration & Offline Core
- **100% Offline Core**: Zero cloud or proprietary service dependencies required.
- **Optional Enterprise Features**: Centralized IAM (RBAC/ABAC), fleet security policy distribution, remote worker federation, and cryptographic tamper-evident centralized audit ledgers.

---

## Performance Summary

| Metric | Measured Median | Measured P95 |
| :--- | :---: | :---: |
| **CLI Process Startup** | 666.56 ms | 688.43 ms |
| **Session Restoration** | 0.08 ms | 0.24 ms |
| **Repository Indexing (40 Modules)** | 20.09 ms | 22.91 ms |
| **Context Retrieval** | 2.26 ms | 3.24 ms |
| **Firewall + Tool Overhead** | 0.01 ms | 0.02 ms |
| **Multi-Agent Scheduling** | 0.01 ms | 0.02 ms |
| **Base Memory Footprint (RSS)** | 54.48 MB | 54.51 MB |

---

## Security Invariants

- **Zero Vulnerabilities**: `pip-audit 2.10.1` scanned all 25 runtime dependencies with 0 CVEs.
- **Action Firewall**: Every action is pre-authorized by policy.
- **Secret Redaction**: Dynamic masking on all outputs and prompts.
- **No Direct Shell**: Subprocesses execute via `shell=False` tokenized argument vectors.
