# ATLAS Phase 16 Process Definition Specification

Describes declarative process definition schemas, task classification, branching logic, dependency management, and schema validation.

## 1. Task Types
- `AGENT_EXECUTION`: Task performed by an autonomous AI agent.
- `HUMAN_APPROVAL`: Human sign-off required before progression.
- `EXTERNAL_INTEGRATION`: Interaction with an ERP, CRM, or ticketing system.
- `SUBPROCESS`: Nested child process.
- `TIMER`: Time-based wait or delay.
- `COMPENSATION`: Undoing a previously completed transaction step.
- `GATEWAY_PARALLEL`: Forking parallel branches.
- `GATEWAY_JOIN`: Synchronizing parallel branches (`ALL` or `ANY`).
- `GATEWAY_CONDITIONAL`: Evaluating dynamic variables for branch selection.

## 2. Validation Rules
1. Non-empty tasks list.
2. Unique `task_def_id` across the process definition.
3. Every dependency in `dependencies` must reference a valid task.
4. Dependency graph must be a directed acyclic graph (no cycles).
5. Conditional branch targets must reference existing tasks.
6. Content-addressed hash computation for deterministic version pinning.
