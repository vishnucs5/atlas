# ATLAS CLI — Minimal Mode Specification & Architecture

## 1. Overview and Operational Modes

ATLAS CLI Minimal Mode (`atlas_cli.minimal`) provides a lightweight, distraction-free terminal conversation experience. It operates in two modes:

1. **Interactive REPL Mode** (`atlas`, `atlas --minimal` in an interactive terminal):
   - Conversation history maintained across turns.
   - Live token/word streaming simulation.
   - Rich Markdown formatting and syntax-highlighted code blocks via Pygments.
   - In-line tool execution indicators and file change cards.
   - Interactive Action Firewall approval cards.
   - Slash command system for rapid control (`/diff`, `/status`, `/plan`, `/test`, `/approvals`, `/sessions`).
2. **Headless / Non-Interactive Mode** (`atlas --minimal "<objective>"`, or piped stdin `echo "..." | atlas --minimal`):
   - Single-shot execution for shell scripts, GitHub Actions, and CI/CD pipelines.
   - Structured JSON output support (`--json`).
   - Clean Unix exit codes (0 for success, non-zero for failure).

---

## 2. Interactive Features & Rendering

### A. Markdown and Pygments Code Highlighting
Markdown output is parsed and rendered with:
- Top-level and section headers (`#`, `##`, `###`) highlighted in bold colored ANSI.
- Lists formatted with clean bullet characters (`•`).
- Fenced code blocks (` ```python ... ``` `) rendered through Pygments lexers with terminal syntax highlighting and framed borders:
  ```
  ┌─[ PYTHON ]────────────────────────────────────────
  def add(a: int, b: int) -> int:
      return a + b
  └──────────────────────────────────────────────────
  ```

### B. Tool Execution Indicators & File Changes
When an agent invokes tools, minimal mode surfaces clear execution badges:
```
[TOOL] file.modify src/main.py
[TOOL] terminal.execute pytest tests/unit -q

Files Modified (1):
  [MODIFY] src/main.py +2/-1 (SHA: c1f7a80b)
```

### C. Keyboard Interrupt & Cancellation Invariant
Pressing `Ctrl+C` cancels the current interactive input turn without aborting background task execution on the ATLAS daemon/cluster:
```
[Interrupt] Turn cancelled by operator. Durable background tasks preserved.
```
To cancel durable work, operators explicitly run `atlas task cancel <task_id>`.

---

## 3. Slash Commands Reference

| Slash Command | Description |
|---|---|
| `/help` | Display minimal mode command reference |
| `/diff` | Preview colored unified diff of working tree changes |
| `/status` | Query git porcelain status and workspace clean state |
| `/plan <goal>` | Synthesize structured execution plan without disk modifications |
| `/test` | Discover and run repository tests with metrics |
| `/approvals` | Review and grant/deny pending Action Firewall authorizations |
| `/sessions` | List active and historical developer sessions |
| `/resume <id>` | Switch context to an existing session |
| `/clear` | Clear terminal screen and redraw welcome banner |
| `/exit`, `/quit` | Cleanly exit minimal REPL mode |
