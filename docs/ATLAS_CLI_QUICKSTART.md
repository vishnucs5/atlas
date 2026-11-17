# ATLAS CLI Quickstart Guide

Get up and running with ATLAS CLI in under 3 minutes.

---

## 1. Initialize Your Workspace

Navigate to any software engineering project directory and run:

```bash
cd /path/to/your/project
atlas init
```

This scaffolds the local `.atlas/` control directory:
- `.atlas/config.json`: Local project configuration overrides.
- `.atlas/sessions.db`: WAL-mode SQLite database tracking conversational turns, diffs, and audit events.
- `.atlas/index/`: Cached AST symbol index and dependency graph.

---

## 2. Your First Autonomous Coding Task

### Option 1: Direct Prompt Execution
Invoke ATLAS directly with a task objective from your terminal:

```bash
atlas "Write unit tests for the user authentication service using pytest"
```

ATLAS will:
1. **Discover**: Index relevant codebase files using AST intelligence.
2. **Plan**: Generate a multi-step execution plan with risk ratings.
3. **Firewall**: Evaluate each proposed file write and command against the Action Firewall.
4. **Execute**: Modify files using transactional unified diff patches.
5. **Verify**: Run tests to confirm zero regressions before marking the task complete.

---

### Option 2: Minimal Interactive Mode
For an interactive, conversational developer experience:

```bash
atlas --minimal
```

In minimal mode, you can type natural-language objectives, review colorized streaming diffs, grant human-in-the-loop approvals, and use interactive slash commands:
- `/help`: Display available commands.
- `/diff`: View staged file changes.
- `/plan`: Inspect current task execution graph.
- `/test`: Run test suite verification.
- `/status`: Check runtime health.

---

### Option 3: Advanced TUI Dashboard
For comprehensive visual observability across multi-agent workflows:

```bash
atlas --tui
```

Features 8 live panels:
1. **Conversation**: Streaming model responses and markdown output.
2. **Agent Activity**: Specialist roster assignments and lease durations.
3. **Task Graph**: Topological DAG node states.
4. **Terminal**: Live stdout/stderr execution streams.
5. **File Changes**: Staged unified diffs with line-by-line inspection.
6. **Approvals**: High-integrity approval cards for risky actions.
7. **Timeline**: Monotonic event sequence history.
8. **Runtime**: Resource consumption and model latency telemetry.

---

## 3. Working with Specialist Agents

For complex, multi-faceted engineering projects:

```bash
# View all 11 specialist roles
atlas agents list

# Inspect a specific specialist's capability contract
atlas agents inspect software_architect
atlas agents inspect security_auditor
```
