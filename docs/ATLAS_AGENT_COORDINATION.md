# ATLAS Multi-Agent Coordination and Scheduling

## 1. Supervisor-Led Task Decomposition

Multi-agent coordination in ATLAS is governed by `CodingTeamSupervisor`:

1. **Objective Decomposition**:
   A high-level software goal is parsed into a multi-stage execution DAG (`TaskGraph`):
   $$\text{Objective} \longrightarrow \text{DAG}(\text{Nodes}, \text{Dependencies})$$
2. **Specialist Selection**:
   Subtasks declare required capabilities (`ARCHITECT`, `EXPLORER`, `BACKEND`, etc.). The supervisor selects eligible agents from `AgentRegistry` and acquires exclusive execution leases (`AgentLease`) with TTL limits.
3. **Dependency-Aware Parallel Scheduling**:
   Independent ready nodes are dispatched in parallel batches up to `max_parallel` (default 4 concurrent workers).
4. **Failure Propagation**:
   If a task node fails, dependent child nodes are automatically marked `CANCELLED` with an upstream failure reference, preventing wasted tokens or corrupted partial state.

---

## 2. Dynamic Conflict Detection and Dependency Serialization

A critical risk in multi-agent coding is concurrent agents modifying the same file simultaneously:

```
[Agent A: Modify src/auth.py] <── CONFLICT ──> [Agent B: Modify src/auth.py]
```

### Automatic Serialization
`ConflictManager` inspects target file parameters across all planned nodes prior to dispatch:
1. Detects overlapping write sets.
2. Automatically injects a hard dependency edge:
   $$\text{Node}_A \longrightarrow \text{Node}_B$$
3. Records an auditable resolution decision (`ConflictResolutionDecision`) documenting why serialization was applied.
4. Prevents race conditions, corrupted diffs, or lost code edits.

---

## 3. Communication, Cancellation, and Recovery

- **Message Routing**: Communication between supervisor and specialists uses `AgentMessage` packets (`TASK_ASSIGNMENT`, `TASK_RESULT`, `CANCEL_NOTICE`).
- **Cancellation Cascade**: When an operator interrupts execution or a task is cancelled, the supervisor broadcasts a `CANCEL_NOTICE` across all registered agents and halts leased workers.
- **Lease Expiration and Recovery**: If an agent hangs or encounters an unhandled exception, `AgentRegistry` expires the lease, marks the worker `UNHEALTHY`, and returns the node to recovery.
