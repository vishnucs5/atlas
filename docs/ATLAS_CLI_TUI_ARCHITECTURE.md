# ATLAS CLI — Advanced Interactive TUI Dashboard Architecture

## 1. Architectural Mission and Invariants

The ATLAS Interactive Terminal Dashboard (`atlas --tui`, `atlas_cli.tui`) provides an 8-panel real-time operational interface for monitoring, orchestrating, and authorizing autonomous developer workflows.

### Architectural Invariants
1. **Zero New Heavy Dependencies**: Built using standard ANSI terminal escape sequences, terminal dimension introspection (`shutil.get_terminal_size()`), and existing formatting utilities, ensuring portability across Windows, macOS, and Linux without requiring heavy C extensions.
2. **Identical Core Services**: The TUI is a presentation adapter over the exact same `CodingEngine`, `AtlasClient`, and `ActionFirewall` services that power minimal and scripting modes.
3. **Deterministic State Projection**: UI state is projected from ordered `ExecutionEvent` streams, ensuring exact consistency across reconnections.
4. **No Direct Driver Execution**: TUI presentation components never invoke filesystem, subprocess, or network drivers directly; all requests route through `CodingEngine` or `AtlasClient`.
5. **No Hallucinated Telemetry**: Provider metrics (tokens, context usage, cost) display exact reported values or clear `N/A` notices when unavailable.

---

## 2. The 8 Operational Panels

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ ATLAS DASHBOARD | Session: cli_sess_1234 | Status: [ONLINE]                            │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ [1. Conversation] | [2. Agent Activity] | [3. Task Graph] | [4. Terminal]              │
│ [5. File Changes] | [6. Approvals]      | [7. Timeline]   | [8. Runtime]               │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│                               ACTIVE PANEL VIEWPORT                                    │
│                                                                                        │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Keys: [1-8] Focus Panel | [Tab] Next Panel | [a] Approve | [d] Deny | [r] Refresh      │
│ Commands: run <goal> | approve <id> | switch <1-8>                                     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Detailed Panel Specifications:

1. **Main Conversation Panel (`render_conversation_panel`)**:
   - Operator prompts, autonomous responses, tool execution summaries, streaming indicators.
2. **Agent Activity Panel (`render_agent_activity_panel`)**:
   - Specialist agent identity, role, active task, execution state (`READY`, `BUSY`, `WAITING_APPROVAL`), token telemetry.
3. **Task Graph Panel (`render_task_graph_panel`)**:
   - Hierarchical DAG representation of subtasks, dependencies, completion status, risk badges, and recovery states.
4. **Terminal Panel (`render_terminal_panel`)**:
   - Live stream of authorized commands (`shell=False`), stdout, stderr, exit codes, and execution durations.
5. **File Changes Panel (`render_file_changes_panel`)**:
   - Modified, new, and deleted files in the working directory, plus unified colored diff previews.
6. **Approval Panel (`render_approval_panel`)**:
   - Action Firewall approval cards with exact operation, target, parameters, risk level, scope, and expiration.
7. **Execution Timeline (`render_timeline_panel`)**:
   - Monotonic event sequence log (`TASK_CREATED`, `PLAN_GENERATED`, `ACTION_PROPOSED`, `APPROVAL_GRANTED`, `VERIFICATION_COMPLETED`, `TASK_COMPLETED`).
8. **Runtime Panel (`render_runtime_panel`)**:
   - Model provider, active model, session persistence mode, context usage, token accounting, and worker fleet health.

---

## 3. Event Streaming & Sequence Ordering

The TUI integrates with `EventStreamSubscriber` and `reconstruct_state_from_events`:
- **Deduplication**: Events are tracked by `event_id` in a hash set.
- **Monotonic Ordering**: Ingested batches are sorted by `sequence`. Stale events (`sequence <= last_sequence`) are dropped.
- **Resynchronization**: Upon reconnecting to an ATLAS server or resuming a session, full history is ingested and state is deterministically reconstructed.
