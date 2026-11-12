# ADR-0006: Autonomous Planning and Execution Loop

## Status
Accepted

## Date
2026-11-12

## Context & Problem Statement
ATLAS transforms high-level user directives into concrete computer actions across browsers, desktop environments, and OS shells. In autonomous computer-use agents, failure modes are catastrophic if uncontrolled:
1. **Unconstrained Direct Execution**: Models proposing direct tool calls that bypass policy evaluation can execute dangerous commands or exfiltrate private credentials.
2. **Infinite Loops & Hallucinated Progress**: Models repeatedly proposing identical or failing actions without verifying real-world state transitions waste budget and risk runaway processes.
3. **Prompt Injection & Context Pollution**: Untrusted DOM content or external web pages can inject prompt override instructions that hijack the agent's task lifecycle.
4. **Context Window Exhaustion**: Raw DOM snapshots and large accessibility trees rapidly blow context windows, resulting in truncation errors and degraded reasoning.

ATLAS requires an autonomous planning and execution architecture that strictly isolates untrusted model output behind verification invariants and policy firewalls.

## Decision Drivers
- **Constitutional Rule 1 (Architecture Ownership)**: ATLAS Core and Agent own the loop, task lifecycle, and plan state; models are untrusted decision engines.
- **Constitutional Rule 2 (Action Firewall)**: No model adapter or execution worker may execute an action without authorization.
- **Constitutional Rule 7 (Verification Invariant)**: An action is never reported as successful without deterministic post-condition verification.
- **Constitutional Rule 8 (Durable Continuity)**: Every observation, plan transition, action execution, and verification check must be recorded as an immutable `ExecutionEvent`.
- **Bounded Bounding**: Hard limits on loop iterations, token budgets, execution costs, and replan attempts.
- **Defense in Depth**: Strict demarcation of untrusted external content.

## Decision Outcome
Adopt the **11-Step Autonomous Agent Execution Cycle** managed by `atlas-agent` and coordinated with `atlas-models`, `atlas-policy`, `atlas-observation`, and `atlas-verification`.

### The 11-Step Autonomous Execution Cycle

```
[1. OBSERVE] ---------> Capture Environment (DOM, A11y, Screenshot)
     |
[2. BUILD CONTEXT] ---> Summarize DOM, Redact Secrets, Demarcate Untrusted Data
     |
[3. ASK MODEL] -------> Query ModelRouter (Capability Routing, Cost Tracking)
     |
[4. VALIDATE] --------> Parse & Validate Tool Call Schema (Pydantic)
     |
[5. PROPOSE ACTION] --> Convert to Typed ATLAS ComputerAction
     |
[6. CHECK POLICY] ----> ActionFirewall.evaluate(action) [ALLOW / REQUIRE_APPROVAL / DENY]
     |                   \--> If DENY: Record Event, trigger Recovery/Replan
     v
[7. APPROVAL] --------> If REQUIRE_APPROVAL: Request Human Approval Token
     |
[8. EXECUTE] ---------> Dispatch to ComputerDriver (Playwright / OS Driver)
     |                   \--> ATLAS driver executes; model NEVER controls directly!
     v
[9. VERIFY] ----------> VerificationEngine.verify(expected_state)
     |                   \--> If Verification Fails: Emit FAILURE event, Replan
     v
[10. RECORD EVENTS] --> Append immutable ExecutionEvent to SQLite/PostgreSQL
     |
[11. REPLAN / CONT] --> Check Goal Completion, Idempotency, Budgets, Next Step
```

### Key Architectural Subsystems

1. **Structured Planner (`packages/atlas-agent/planner.py`)**:
   - Generates an `ExecutionPlan` comprising sequential or dependency-ordered `PlanStep` items.
   - Each step specifies: `step_id`, `description`, `action_name`, `target`, `parameters`, `expected_state`, and optional `rollback_action`.
   - Validates plan feasibility against available tools before dispatching any action.
   - Enforces a replan budget (`max_replans=3`) to prevent cyclic planning thrashing.
2. **Context & Memory Management (`packages/atlas-agent/context.py`)**:
   - **DOM Summarization**: Condenses extensive DOM structures into compact interactive element trees, eliminating non-essential layout wrappers.
   - **Vision Downsampling**: Resizes and compresses viewport screenshots to optimal token/detail dimensions.
   - **Prompt Injection Demarcation**: Wraps all external web/terminal text within strict XML boundaries (`<untrusted_external_content>`), paired with system instructions explicitly forbidding directive overrides.
   - **Task Memory**: Structured scratchpad, variable store, and history window with token-aware pruning.
3. **Safety & Loop Bounding (`packages/atlas-agent/safety.py`)**:
   - **Action Idempotency Hasher**: Hashes recent action targets and parameters; detects repeating action loops and forces recovery.
   - **Hard Execution Ceilings**: Enforces `max_iterations`, `max_tokens`, `max_cost_usd`, and step timeout propagation.

## Consequences

### Positive
- Guarantees Constitutional compliance: the model has zero direct execution power.
- Prevents infinite loops, runaway API costs, and silent execution failures.
- Deterministic verification ensures operations actually completed on the target application before marking steps succeeded.
- High resilience to prompt injection via structural data demarcation and strict firewall gating.

### Negative / Trade-offs
- The 11-step cycle adds slight orchestration latency (observation capture + verification polling), which is acceptable for reliable, production-grade enterprise automation.
